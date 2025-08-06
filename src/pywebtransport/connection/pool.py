"""
WebTransport connection pooling implementation.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any, Self, Type

from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.exceptions import ConnectionError
from pywebtransport.utils import get_logger

__all__ = ["ConnectionPool"]

logger = get_logger("connection.pool")


class ConnectionPool:
    """Manages a pool of reusable WebTransport connections."""

    def __init__(
        self,
        *,
        max_size: int = 10,
        max_idle_time: float = 300.0,
        cleanup_interval: float = 60.0,
    ):
        """Initialize the connection pool."""
        self._max_size = max_size
        self._max_idle_time = max_idle_time
        self._cleanup_interval = cleanup_interval
        self._pool: dict[str, list[tuple[WebTransportConnection, float]]] = {}
        self._lock: asyncio.Lock | None = None
        self._cleanup_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        """Enter async context, initializing resources and starting background tasks."""
        self._lock = asyncio.Lock()
        self._start_cleanup_task()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, closing all pooled connections."""
        await self.close_all()

    async def get_connection(
        self,
        *,
        config: ClientConfig,
        host: str,
        port: int,
        path: str = "/",
    ) -> WebTransportConnection:
        """Get a connection from the pool or create a new one."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        pool_key = self._get_pool_key(host, port)
        async with self._lock:
            if pool_key in self._pool and self._pool[pool_key]:
                connection, _ = self._pool[pool_key].pop(0)
                if connection.is_connected:
                    logger.debug(f"Reusing pooled connection to {host}:{port}")
                    return connection
                else:
                    logger.debug(f"Discarding stale connection to {host}:{port}")
                    await connection.close()

        logger.debug(f"Creating new connection to {host}:{port}")
        connection = WebTransportConnection(config)
        await connection.connect(host=host, port=port, path=path)
        return connection

    async def return_connection(self, connection: WebTransportConnection) -> None:
        """Return a connection to the pool for potential reuse."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        if not connection.is_connected:
            await connection.close()
            return

        remote_addr = connection.remote_address
        if not remote_addr:
            await connection.close()
            return

        pool_key = self._get_pool_key(remote_addr[0], remote_addr[1])
        async with self._lock:
            if pool_key not in self._pool:
                self._pool[pool_key] = []

            if len(self._pool[pool_key]) >= self._max_size:
                logger.debug(f"Pool full for {pool_key}, closing returned connection")
                await connection.close()
                return

            self._pool[pool_key].append((connection, time.time()))
            logger.debug(f"Returned connection to pool for {pool_key}")

    async def close_all(self) -> None:
        """Close all idle connections and shut down the pool."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        close_tasks = []
        async with self._lock:
            for connections in self._pool.values():
                for connection, _ in connections:
                    close_tasks.append(asyncio.create_task(connection.close()))
            self._pool.clear()

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

    def get_stats(self) -> dict[str, Any]:
        """Get current statistics about the connection pool."""
        total_connections = sum(len(conns) for conns in self._pool.values())
        return {
            "total_pooled_connections": total_connections,
            "active_pools": len(self._pool),
            "max_size_per_pool": self._max_size,
            "max_idle_time_seconds": self._max_idle_time,
        }

    def _get_pool_key(self, host: str, port: int) -> str:
        """Generate a unique key for a given host and port."""
        return f"{host}:{port}"

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task if it is not already running."""
        if self._cleanup_task is None:
            coro = self._cleanup_idle_connections()
            try:
                self._cleanup_task = asyncio.create_task(coro)
            except RuntimeError:
                coro.close()
                self._cleanup_task = None
                logger.warning("Could not start pool cleanup task: no running event loop.")

    async def _cleanup_idle_connections(self) -> None:
        """Periodically find and remove idle connections from the pool."""
        if self._lock is None:
            return
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval)
                current_time = time.time()
                connections_to_close = []

                async with self._lock:
                    for pool_key, connections in list(self._pool.items()):
                        for i in range(len(connections) - 1, -1, -1):
                            connection, idle_time = connections[i]
                            if (current_time - idle_time) > self._max_idle_time:
                                connections.pop(i)
                                connections_to_close.append(connection)
                        if not connections:
                            del self._pool[pool_key]

                if connections_to_close:
                    logger.debug(f"Closing {len(connections_to_close)} idle connections")
                    for connection in connections_to_close:
                        try:
                            await connection.close()
                        except Exception as e:
                            logger.warning(f"Error closing idle connection: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Pool cleanup task error: {e}", exc_info=e)
