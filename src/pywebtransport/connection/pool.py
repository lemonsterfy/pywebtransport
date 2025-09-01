"""
WebTransport connection pooling implementation.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
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
        if max_size <= 0:
            raise ValueError("max_size must be a positive integer.")

        self._max_size = max_size
        self._max_idle_time = max_idle_time
        self._cleanup_interval = cleanup_interval
        self._pool: dict[str, list[tuple[WebTransportConnection, float]]] = defaultdict(list)
        self._conditions: defaultdict[str, asyncio.Condition] | None = None
        self._total_connections: defaultdict[str, int] = defaultdict(int)
        self._cleanup_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        """Enter async context, initializing resources and starting background tasks."""
        self._conditions = defaultdict(asyncio.Condition)
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

    async def close_all(self) -> None:
        """Close all idle connections and shut down the pool."""
        if self._conditions is None:
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

        connections_to_close: list[WebTransportConnection] = []
        for pool_key in list(self._pool.keys()):
            condition = self._conditions[pool_key]
            async with condition:
                connections = self._pool.pop(pool_key, [])
                connections_to_close.extend(conn for conn, _ in connections)
                self._total_connections[pool_key] = 0

        if connections_to_close:
            try:
                async with asyncio.TaskGroup() as tg:
                    for conn in connections_to_close:
                        tg.create_task(conn.close())
            except* Exception as eg:
                logger.error(f"Errors occurred while closing pooled connections: {eg.exceptions}")

    async def get_connection(
        self,
        *,
        config: ClientConfig,
        host: str,
        port: int,
        path: str = "/",
    ) -> WebTransportConnection:
        """Get a connection from the pool or create a new one."""
        if self._conditions is None:
            raise ConnectionError(
                "ConnectionPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        pool_key = self._get_pool_key(host, port)
        condition = self._conditions[pool_key]

        async with condition:
            while True:
                pool = self._pool[pool_key]
                while pool:
                    connection, _ = pool.pop(0)
                    if connection.is_connected:
                        logger.debug(f"Reusing pooled connection to {host}:{port}")
                        return connection
                    else:
                        logger.debug(f"Discarding stale connection to {host}:{port}")
                        self._total_connections[pool_key] -= 1

                if self._total_connections[pool_key] < self._max_size:
                    self._total_connections[pool_key] += 1
                    break

                logger.debug(f"Pool for {pool_key} is full. Waiting for a connection.")
                await condition.wait()

        try:
            logger.debug(f"Creating new connection to {host}:{port}")
            connection = WebTransportConnection(config)
            await connection.connect(host=host, port=port, path=path)
            return connection
        except Exception:
            async with condition:
                self._total_connections[pool_key] -= 1
                condition.notify()
            raise

    async def return_connection(self, connection: WebTransportConnection) -> None:
        """Return a connection to the pool for potential reuse."""
        if self._conditions is None:
            raise ConnectionError(
                "ConnectionPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        if not (remote_addr := connection.remote_address):
            await connection.close()
            return

        pool_key = self._get_pool_key(remote_addr[0], remote_addr[1])
        condition = self._conditions[pool_key]
        should_close = not connection.is_connected

        if not should_close:
            async with condition:
                if len(self._pool[pool_key]) >= self._max_size:
                    should_close = True
                else:
                    self._pool[pool_key].append((connection, time.time()))
                    logger.debug(f"Returned connection to pool for {pool_key}")
                    condition.notify()

        if should_close:
            async with condition:
                self._total_connections[pool_key] -= 1
                condition.notify()
            await connection.close()

    def get_stats(self) -> dict[str, Any]:
        """Get current statistics about the connection pool."""
        if self._conditions is None:
            raise ConnectionError(
                "ConnectionPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        total_pooled = sum(len(conns) for conns in self._pool.values())
        total_active = sum(self._total_connections.values())
        return {
            "total_pooled_connections": total_pooled,
            "total_active_connections": total_active,
            "active_pools": len(self._pool),
            "max_size_per_pool": self._max_size,
        }

    async def _cleanup_idle_connections(self) -> None:
        """Periodically find and remove idle connections from the pool."""
        if self._conditions is None:
            return

        try:
            while True:
                await asyncio.sleep(self._cleanup_interval)
                current_time = time.time()
                connections_to_close: list[WebTransportConnection] = []

                for pool_key in list(self._pool.keys()):
                    condition = self._conditions[pool_key]
                    async with condition:
                        connections = self._pool.get(pool_key)
                        if not connections:
                            continue

                        pruned_count = 0
                        for i in range(len(connections) - 1, -1, -1):
                            conn, idle_time = connections[i]
                            if (current_time - idle_time) > self._max_idle_time:
                                connections.pop(i)
                                connections_to_close.append(conn)
                                pruned_count += 1

                        if pruned_count > 0:
                            self._total_connections[pool_key] -= pruned_count
                            for _ in range(pruned_count):
                                condition.notify()

                if connections_to_close:
                    logger.debug(f"Closing {len(connections_to_close)} idle connections")
                    try:
                        async with asyncio.TaskGroup() as tg:
                            for conn in connections_to_close:
                                tg.create_task(conn.close())
                    except* Exception as eg:
                        logger.warning(f"Errors closing idle connections: {eg.exceptions}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Pool cleanup task error: {e}", exc_info=e)

    def _get_pool_key(self, host: str, port: int) -> str:
        """Generate a unique key for a given host and port."""
        return f"{host}:{port}"

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task if it is not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            coro = self._cleanup_idle_connections()
            try:
                self._cleanup_task = asyncio.create_task(coro)
            except RuntimeError:
                coro.close()
                self._cleanup_task = None
                logger.warning("Could not start pool cleanup task: no running event loop.")
