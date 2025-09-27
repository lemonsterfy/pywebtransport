"""WebTransport Pooled Client."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from types import TracebackType
from typing import Self

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.exceptions import ClientError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import URL
from pywebtransport.utils import get_logger, parse_webtransport_url

__all__ = ["PooledClient"]

logger = get_logger(name="client.pooled")


class PooledClient:
    """A client that manages pools of reusable WebTransport sessions."""

    def __init__(
        self,
        *,
        config: ClientConfig | None = None,
        pool_size: int = 10,
        cleanup_interval: float = 60.0,
    ) -> None:
        """Initialize the pooled client."""
        if pool_size <= 0:
            raise ValueError("pool_size must be a positive integer.")

        self._client = WebTransportClient(config=config)
        self._pool_size = pool_size
        self._cleanup_interval = cleanup_interval
        self._pools: dict[str, list[WebTransportSession]] = defaultdict(list)
        self._conditions: defaultdict[str, asyncio.Condition] | None = None
        self._total_sessions: defaultdict[str, int] = defaultdict(int)
        self._cleanup_task: asyncio.Task[None] | None = None

    @classmethod
    def create(
        cls,
        *,
        config: ClientConfig | None = None,
        pool_size: int = 10,
        cleanup_interval: float = 60.0,
    ) -> Self:
        """Create a new pooled client instance."""
        return cls(config=config, pool_size=pool_size, cleanup_interval=cleanup_interval)

    async def __aenter__(self) -> Self:
        """Enter the async context, activating the client and background tasks."""
        self._conditions = defaultdict(asyncio.Condition)
        await self._client.__aenter__()
        self._start_cleanup_task()
        logger.info("PooledClient started and is active.")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context, closing all resources."""
        await self.close()

    async def close(self) -> None:
        """Close all pooled sessions and the underlying client."""
        if self._conditions is None:
            raise ClientError(
                message=(
                    "PooledClient has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        logger.info("Closing PooledClient...")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        sessions_to_close: list[WebTransportSession] = []
        for pool_key in list(self._pools.keys()):
            condition = self._conditions[pool_key]
            async with condition:
                sessions = self._pools.pop(pool_key, [])
                sessions_to_close.extend(sessions)
                self._total_sessions[pool_key] = 0

        if sessions_to_close:
            try:
                async with asyncio.TaskGroup() as tg:
                    for session in sessions_to_close:
                        tg.create_task(session.close())
            except* Exception as eg:
                logger.error("Errors occurred while closing pooled sessions: %s", eg.exceptions, exc_info=eg)

        await self._client.close()
        logger.info("PooledClient has been closed.")

    async def get_session(self, *, url: URL) -> WebTransportSession:
        """Get a session from the pool or create a new one."""
        if self._conditions is None:
            raise ClientError(
                message=(
                    "PooledClient has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        pool_key = self._get_pool_key(url=url)
        condition = self._conditions[pool_key]

        async with condition:
            while True:
                pool = self._pools[pool_key]
                while pool:
                    session = pool.pop(0)
                    if session.is_ready:
                        logger.debug("Reusing session from pool for %s", pool_key)
                        return session
                    else:
                        logger.debug("Discarding stale session for %s", pool_key)
                        self._total_sessions[pool_key] -= 1

                if self._total_sessions[pool_key] < self._pool_size:
                    self._total_sessions[pool_key] += 1
                    break

                logger.debug("Pool for %s is full. Waiting for a session to be returned.", pool_key)
                await condition.wait()

        try:
            logger.debug("Creating new session for %s", pool_key)
            session = await self._client.connect(url=url)
            return session
        except Exception:
            async with condition:
                self._total_sessions[pool_key] -= 1
                condition.notify()
            raise

    async def return_session(self, *, session: WebTransportSession) -> None:
        """Return a session to the pool for potential reuse."""
        if self._conditions is None:
            raise ClientError(
                message=(
                    "PooledClient has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        pool_key = self._get_pool_key_from_session(session=session)
        should_close = not session.is_ready or not pool_key

        if not should_close and pool_key:
            condition = self._conditions[pool_key]
            async with condition:
                pool = self._pools[pool_key]
                if len(pool) >= self._pool_size:
                    should_close = True
                else:
                    pool.append(session)
                    logger.debug("Returned session to pool for %s", pool_key)
                    condition.notify()

        if should_close:
            if pool_key:
                condition = self._conditions[pool_key]
                async with condition:
                    self._total_sessions[pool_key] -= 1
                    condition.notify()
            await session.close()

    def _get_pool_key(self, *, url: URL) -> str:
        """Get a normalized pool key from a URL."""
        try:
            host, port, path = parse_webtransport_url(url=url)
            return f"{host}:{port}{path}"
        except Exception:
            return str(url)

    def _get_pool_key_from_session(self, *, session: WebTransportSession) -> str | None:
        """Get a pool key from an active session."""
        if session.connection and session.connection.remote_address:
            host, port = session.connection.remote_address
            path = session.path
            return f"{host}:{port}{path}"
        return None

    async def _periodic_cleanup(self) -> None:
        """Periodically remove stale sessions from all pools."""
        if self._conditions is None:
            return

        while True:
            await asyncio.sleep(self._cleanup_interval)
            logger.debug("Running stale session cleanup for all pools...")

            for pool_key in list(self._pools.keys()):
                condition = self._conditions[pool_key]
                async with condition:
                    sessions = self._pools.get(pool_key)
                    if not sessions:
                        continue

                    original_len = len(sessions)
                    ready_sessions = [s for s in sessions if s.is_ready]

                    if len(ready_sessions) < original_len:
                        pruned_count = original_len - len(ready_sessions)
                        logger.info("Pruned %d stale sessions from pool '%s'", pruned_count, pool_key)
                        self._pools[pool_key] = ready_sessions
                        self._total_sessions[pool_key] -= pruned_count
                        for _ in range(pruned_count):
                            condition.notify()

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
