"""
WebTransport Pooled Client.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from types import TracebackType
from typing import Self, Type

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.exceptions import ClientError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import URL
from pywebtransport.utils import get_logger, parse_webtransport_url

__all__ = ["PooledClient"]

logger = get_logger("client.pooled")


class PooledClient:
    """A client that manages pools of reusable WebTransport sessions."""

    def __init__(
        self,
        *,
        config: ClientConfig | None = None,
        pool_size: int = 10,
        cleanup_interval: float = 60.0,
    ):
        """Initialize the pooled client."""
        self._client = WebTransportClient.create(config=config)
        self._pool_size = pool_size
        self._cleanup_interval = cleanup_interval
        self._pools: dict[str, list[WebTransportSession]] = defaultdict(list)
        self._lock: asyncio.Lock | None = None
        self._cleanup_task: asyncio.Task[None] | None = None

    @classmethod
    def create(
        cls,
        *,
        config: ClientConfig | None = None,
        pool_size: int = 10,
        cleanup_interval: float = 60.0,
    ) -> Self:
        """Factory method to create a new pooled client instance."""
        return cls(config=config, pool_size=pool_size, cleanup_interval=cleanup_interval)

    async def __aenter__(self) -> Self:
        """Enter the async context, activating the client and background tasks."""
        self._lock = asyncio.Lock()
        await self._client.__aenter__()
        self._start_cleanup_task()
        logger.info("PooledClient started and is active.")
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context, closing all resources."""
        await self.close()

    async def close(self) -> None:
        """Close all pooled sessions and the underlying client."""
        if self._lock is None:
            raise ClientError(
                "PooledClient has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        logger.info("Closing PooledClient...")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            close_tasks = [session.close() for sessions in self._pools.values() for session in sessions]
            if close_tasks:
                await asyncio.gather(*close_tasks, return_exceptions=True)
            self._pools.clear()

        await self._client.close()
        logger.info("PooledClient has been closed.")

    async def get_session(self, url: URL) -> WebTransportSession:
        """Get a session from the pool or create a new one."""
        if self._lock is None:
            raise ClientError(
                "PooledClient has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        pool_key = self._get_pool_key(url)

        async with self._lock:
            pool = self._pools[pool_key]
            while pool:
                session = pool.pop(0)
                if session.is_ready:
                    logger.debug(f"Reusing session from pool for {pool_key}")
                    return session
                else:
                    logger.debug(f"Discarding stale session for {pool_key}")

        logger.debug(f"Pool for {pool_key} is empty, creating new session.")
        return await self._client.connect(url)

    async def return_session(self, session: WebTransportSession) -> None:
        """Return a session to the pool for potential reuse."""
        if self._lock is None:
            raise ClientError(
                "PooledClient has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        if not session.is_ready:
            await session.close()
            return

        pool_key = self._get_pool_key_from_session(session)
        if not pool_key:
            await session.close()
            return

        async with self._lock:
            pool = self._pools[pool_key]
            if len(pool) >= self._pool_size:
                logger.debug(f"Pool for {pool_key} is full, closing returned session.")
                await session.close()
                return
            pool.append(session)
            logger.debug(f"Returned session to pool for {pool_key}")

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task if not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        """Periodically check for and remove stale sessions from all pools."""
        if self._lock is None:
            return
        while True:
            await asyncio.sleep(self._cleanup_interval)
            logger.debug("Running stale session cleanup for all pools...")
            async with self._lock:
                for pool_key, sessions in self._pools.items():
                    ready_sessions = [s for s in sessions if s.is_ready]
                    if len(ready_sessions) < len(sessions):
                        logger.info(
                            f"Pruned {len(sessions) - len(ready_sessions)} stale sessions from pool '{pool_key}'"
                        )
                        self._pools[pool_key] = ready_sessions

    def _get_pool_key(self, url: URL) -> str:
        """Get a normalized pool key from a URL."""
        try:
            host, port, path = parse_webtransport_url(url)
            return f"{host}:{port}{path}"
        except Exception:
            return url

    def _get_pool_key_from_session(self, session: WebTransportSession) -> str | None:
        """Get a pool key from an active session."""
        if session.connection and session.connection.remote_address:
            host, port = session.connection.remote_address
            path = session.path
            return f"{host}:{port}{path}"
        return None
