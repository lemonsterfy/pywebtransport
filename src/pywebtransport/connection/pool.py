"""
WebTransport connection pooling implementation.

This module provides a ConnectionPool class for managing and reusing
WebTransport connections to reduce connection setup latency.
"""

import asyncio
import time
from types import TracebackType
from typing import Any, Dict, List, Optional, Tuple, Type

from ..config import ClientConfig
from ..utils import get_logger
from .connection import WebTransportConnection

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
        self._pool: Dict[str, List[Tuple[WebTransportConnection, float]]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    async def __aenter__(self) -> "ConnectionPool":
        """Enter async context, starting background tasks."""
        self._start_cleanup_task()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
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

    def get_stats(self) -> Dict[str, Any]:
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
            try:
                self._cleanup_task = asyncio.create_task(self._cleanup_idle_connections())
            except RuntimeError:
                self._cleanup_task = None
                logger.warning("Could not start pool cleanup task: no running event loop.")

    async def _cleanup_idle_connections(self) -> None:
        """Periodically find and remove idle connections from the pool."""
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
