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
        self._locks: defaultdict[str, asyncio.Lock] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._pending_creations: dict[str, asyncio.Event] = {}

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
        self._locks = defaultdict(asyncio.Lock)
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
        if self._locks is None:
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

        sessions_to_close: list[WebTransportSession] = []
        pool_keys = list(self._pools.keys())
        for pool_key in pool_keys:
            async with self._locks[pool_key]:
                sessions = self._pools.pop(pool_key, [])
                sessions_to_close.extend(sessions)

        if sessions_to_close:
            try:
                async with asyncio.TaskGroup() as tg:
                    for session in sessions_to_close:
                        tg.create_task(session.close())
            except* Exception as eg:
                logger.error(f"Errors occurred while closing pooled sessions: {eg.exceptions}")

        await self._client.close()
        logger.info("PooledClient has been closed.")

    async def get_session(self, url: URL) -> WebTransportSession:
        """Get a session from the pool or create a new one."""
        if self._locks is None:
            raise ClientError(
                "PooledClient has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        pool_key = self._get_pool_key(url)

        while True:
            is_creator = False
            lock = self._locks[pool_key]
            event = None
            async with lock:
                pool = self._pools[pool_key]
                while pool:
                    session = pool.pop(0)
                    if session.is_ready:
                        logger.debug(f"Reusing session from pool for {pool_key}")
                        return session
                    else:
                        logger.debug(f"Discarding stale session for {pool_key}")

                if event := self._pending_creations.get(pool_key):
                    pass
                else:
                    is_creator = True
                    event = asyncio.Event()
                    self._pending_creations[pool_key] = event

            if not is_creator:
                await event.wait()
                continue

            try:
                logger.debug(f"Pool for {pool_key} is empty, creating new session.")
                session = await self._client.connect(url)
                return session
            finally:
                async with lock:
                    self._pending_creations.pop(pool_key, None)
                    event.set()

    async def return_session(self, session: WebTransportSession) -> None:
        """Return a session to the pool for potential reuse."""
        if self._locks is None:
            raise ClientError(
                "PooledClient has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        if not session.is_ready:
            await session.close()
            return

        if not (pool_key := self._get_pool_key_from_session(session)):
            await session.close()
            return

        session_to_close: WebTransportSession | None = None
        async with self._locks[pool_key]:
            pool = self._pools[pool_key]
            if len(pool) >= self._pool_size:
                logger.debug(f"Pool for {pool_key} is full, closing returned session.")
                session_to_close = session
            else:
                pool.append(session)
                logger.debug(f"Returned session to pool for {pool_key}")

        if session_to_close:
            await session_to_close.close()

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

    async def _periodic_cleanup(self) -> None:
        """Periodically check for and remove stale sessions from all pools."""
        if self._locks is None:
            return

        while True:
            await asyncio.sleep(self._cleanup_interval)
            logger.debug("Running stale session cleanup for all pools...")

            stale_sessions_to_close: list[WebTransportSession] = []
            pool_keys = list(self._pools.keys())

            for pool_key in pool_keys:
                async with self._locks[pool_key]:
                    sessions = self._pools.get(pool_key)
                    if not sessions:
                        continue

                    ready_sessions: list[WebTransportSession] = []
                    for s in sessions:
                        if s.is_ready:
                            ready_sessions.append(s)
                        else:
                            stale_sessions_to_close.append(s)

                    if len(ready_sessions) < len(sessions):
                        logger.info(
                            f"Pruned {len(sessions) - len(ready_sessions)} stale sessions from pool '{pool_key}'"
                        )
                        self._pools[pool_key] = ready_sessions

            if stale_sessions_to_close:
                try:
                    async with asyncio.TaskGroup() as tg:
                        for s in stale_sessions_to_close:
                            tg.create_task(s.close())
                except* Exception as eg:
                    logger.warning(f"Errors closing stale sessions during cleanup: {eg.exceptions}")

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task if not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
