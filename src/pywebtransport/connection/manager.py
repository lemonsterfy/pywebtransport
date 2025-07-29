"""
WebTransport connection manager implementation.
"""

import asyncio
from collections import defaultdict
from types import TracebackType
from typing import Any, Dict, List, Optional, Type

from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.exceptions import ConnectionError
from pywebtransport.types import ConnectionId
from pywebtransport.utils import get_logger

__all__ = ["ConnectionManager"]

logger = get_logger("connection.manager")


class ConnectionManager:
    """Manages multiple WebTransport connections with concurrency safety."""

    def __init__(self, *, max_connections: int = 1000, cleanup_interval: float = 60.0):
        """Initialize the connection manager."""
        self._max_connections = max_connections
        self._cleanup_interval = cleanup_interval
        self._lock = asyncio.Lock()
        self._connections: Dict[ConnectionId, WebTransportConnection] = {}
        self._stats = {
            "total_created": 0,
            "total_closed": 0,
            "current_count": 0,
            "max_concurrent": 0,
        }
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    @classmethod
    def create(cls, *, max_connections: int = 1000) -> "ConnectionManager":
        """Factory method to create a new connection manager instance."""
        return cls(max_connections=max_connections)

    async def __aenter__(self) -> "ConnectionManager":
        """Enter async context, starting background tasks."""
        self._start_cleanup_task()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit async context, shutting down the manager."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the manager and all associated tasks and connections."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.close_all_connections()
        logger.info("Connection manager shutdown complete")

    async def close_all_connections(self) -> None:
        """Close all currently managed connections."""
        async with self._lock:
            connections_to_close = list(self._connections.values())
            if not connections_to_close:
                return
            logger.info(f"Closing {len(connections_to_close)} connections")

        close_tasks = [conn.close() for conn in connections_to_close]
        await asyncio.gather(*close_tasks, return_exceptions=True)

        async with self._lock:
            self._connections.clear()
            self._update_stats_unsafe()
        logger.info("All connections closed")

    async def add_connection(self, connection: WebTransportConnection) -> ConnectionId:
        """Add a new connection to the manager."""
        async with self._lock:
            if len(self._connections) >= self._max_connections:
                raise ConnectionError(f"Maximum connections ({self._max_connections}) exceeded")
            connection_id = connection.connection_id
            self._connections[connection_id] = connection
            self._stats["total_created"] += 1
            self._update_stats_unsafe()
            logger.debug(f"Added connection {connection_id} (total: {len(self._connections)})")
            return connection_id

    async def remove_connection(self, connection_id: ConnectionId) -> Optional[WebTransportConnection]:
        """Remove a connection from the manager by its ID."""
        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection:
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                logger.debug(f"Removed connection {connection_id} (total: {len(self._connections)})")
            return connection

    async def get_connection(self, connection_id: ConnectionId) -> Optional[WebTransportConnection]:
        """Retrieve a connection by its ID."""
        async with self._lock:
            return self._connections.get(connection_id)

    async def get_all_connections(self) -> List[WebTransportConnection]:
        """Retrieve a list of all current connections."""
        async with self._lock:
            return list(self._connections.values())

    def get_connection_count(self) -> int:
        """Get the current number of active connections."""
        return len(self._connections)

    async def get_stats(self) -> Dict[str, Any]:
        """Get detailed statistics about the managed connections."""
        async with self._lock:
            states: Dict[str, int] = defaultdict(int)
            for conn in self._connections.values():
                states[conn.state.value] += 1
            return {
                **self._stats,
                "active": len(self._connections),
                "states": dict(states),
                "max_connections": self._max_connections,
            }

    async def cleanup_closed_connections(self) -> int:
        """Find and remove any connections that are marked as closed."""
        async with self._lock:
            all_connections = list(self._connections.items())
        closed_connection_ids = [conn_id for conn_id, conn in all_connections if conn.is_closed]

        if not closed_connection_ids:
            return 0
        for conn_id in closed_connection_ids:
            await self.remove_connection(conn_id)
        logger.debug(f"Cleaned up {len(closed_connection_ids)} closed connections.")
        return len(closed_connection_ids)

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task if it is not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        """Periodically run the cleanup process to remove closed connections."""
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval)
                await self.cleanup_closed_connections()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Connection cleanup task crashed: {e}", exc_info=e)

    def _update_stats_unsafe(self) -> None:
        """Update internal statistics (must be called within a lock)."""
        current_count = len(self._connections)
        self._stats["current_count"] = current_count
        self._stats["max_concurrent"] = max(self._stats["max_concurrent"], current_count)
