"""Manager for handling numerous concurrent connection lifecycles."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, ClassVar

from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.manager._base import _BaseResourceManager
from pywebtransport.types import ConnectionId, EventType
from pywebtransport.utils import get_logger

__all__: list[str] = ["ConnectionManager"]

logger = get_logger(name=__name__)


class ConnectionManager(_BaseResourceManager[ConnectionId, WebTransportConnection]):
    """Manage multiple WebTransport connections using event-driven cleanup."""

    _log = logger
    _resource_closed_event_type: ClassVar[EventType] = EventType.CONNECTION_CLOSED

    def __init__(self, *, max_connections: int) -> None:
        """Initialize the connection manager."""
        super().__init__(resource_name="connection", max_resources=max_connections)
        self._cleanup_queue: asyncio.Queue[WebTransportConnection] | None = None
        self._cleanup_worker_task: asyncio.Task[None] | None = None

    async def add_connection(self, *, connection: WebTransportConnection) -> ConnectionId:
        """Add a new connection and subscribe to its closure event."""
        await super().add_resource(resource=connection)
        return connection.connection_id

    async def remove_connection(self, *, connection_id: ConnectionId) -> WebTransportConnection | None:
        """Manually remove a connection from management."""
        if self._lock is None:
            return None

        removed_connection: WebTransportConnection | None = None
        async with self._lock:
            removed_connection = self._resources.pop(connection_id, None)
            if removed_connection:
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                self._log.debug(
                    "Manually removed connection %s (total: %d)", connection_id, self._stats["current_count"]
                )

        if removed_connection:
            if self._cleanup_queue:
                self._cleanup_queue.put_nowait(item=removed_connection)
            self._on_resource_removed(resource_id=connection_id)
        return removed_connection

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed statistics about the managed connections."""
        stats = await super().get_stats()
        if self._lock:
            async with self._lock:
                states: defaultdict[str, int] = defaultdict(int)
                for conn in self._resources.values():
                    states[conn.state.value] += 1
                stats["states"] = dict(states)
        return stats

    async def _cleanup_worker(self) -> None:
        """Process the cleanup queue sequentially with yielding."""
        if self._cleanup_queue is None:
            return

        while True:
            try:
                connection = await self._cleanup_queue.get()
                try:
                    if not connection.is_closed:
                        await connection.close()
                except Exception as e:
                    self._log.error("Error closing connection in cleanup worker: %s", e, exc_info=True)
                finally:
                    self._cleanup_queue.task_done()

                await asyncio.sleep(0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log.error("Cleanup worker crashed unexpectedly: %s", e, exc_info=True)
                await asyncio.sleep(0.1)

    async def _close_resource(self, resource: WebTransportConnection) -> None:
        """Close a single connection resource."""
        if not resource.is_closed:
            await resource.close()

    def _get_resource_id(self, resource: WebTransportConnection) -> ConnectionId:
        """Get the unique ID from a connection object."""
        return resource.connection_id

    async def _handle_resource_closed(self, *, resource_id: ConnectionId) -> None:
        """Handle the closure event for a managed resource."""
        if self._lock is None or self._cleanup_queue is None:
            return

        async with self._lock:
            conn = self._resources.pop(resource_id, None)
            if conn:
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                self._cleanup_queue.put_nowait(item=conn)
                self._log.debug("Passive cleanup: Connection %s removed and queued.", resource_id)

        self._on_resource_removed(resource_id=resource_id)

    def _on_resource_removed(self, *, resource_id: ConnectionId) -> None:
        """Hook called after a connection is removed."""
        pass

    def _start_background_tasks(self) -> None:
        """Start background tasks including the cleanup worker."""
        super()._start_background_tasks()

        if self._cleanup_queue is None:
            self._cleanup_queue = asyncio.Queue()

        if self._cleanup_worker_task is None or self._cleanup_worker_task.done():
            self._cleanup_worker_task = asyncio.create_task(coro=self._cleanup_worker())
            self._cleanup_worker_task.add_done_callback(self._on_background_task_done)
            if self._cleanup_worker_task not in self._background_tasks_to_cancel:
                self._background_tasks_to_cancel.append(self._cleanup_worker_task)
