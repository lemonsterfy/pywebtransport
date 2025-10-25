"""Manager for handling numerous concurrent connection lifecycles."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.constants import (
    DEFAULT_CONNECTION_CLEANUP_INTERVAL,
    DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL,
    DEFAULT_CONNECTION_IDLE_TIMEOUT,
    DEFAULT_SERVER_MAX_CONNECTIONS,
)
from pywebtransport.exceptions import ConnectionError
from pywebtransport.manager._base import _BaseResourceManager
from pywebtransport.types import ConnectionId, EventType
from pywebtransport.utils import get_logger, get_timestamp

__all__: list[str] = ["ConnectionManager"]

logger = get_logger(name=__name__)


class ConnectionManager(_BaseResourceManager[ConnectionId, WebTransportConnection]):
    """Manage multiple WebTransport connections with concurrency safety."""

    _log = logger

    def __init__(
        self,
        *,
        max_connections: int = DEFAULT_SERVER_MAX_CONNECTIONS,
        connection_cleanup_interval: float = DEFAULT_CONNECTION_CLEANUP_INTERVAL,
        connection_idle_check_interval: float = DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL,
        connection_idle_timeout: float = DEFAULT_CONNECTION_IDLE_TIMEOUT,
    ) -> None:
        """Initialize the connection manager."""
        super().__init__(
            resource_name="connection",
            max_resources=max_connections,
            cleanup_interval=connection_cleanup_interval,
        )
        self._idle_check_interval = connection_idle_check_interval
        self._idle_timeout = connection_idle_timeout
        self._idle_check_task: asyncio.Task[None] | None = None
        self._background_tasks_to_cancel: list[asyncio.Task[None] | None] = []

    async def add_connection(self, *, connection: WebTransportConnection) -> ConnectionId:
        """Add a new connection to the manager."""
        if self._lock is None:
            raise ConnectionError(
                message=(
                    "ConnectionManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if len(self._resources) >= self._max_resources:
                raise ConnectionError(message=f"Maximum connections ({self._max_resources}) exceeded")

            connection_id = self._get_resource_id(connection)
            self._resources[connection_id] = connection

            async def on_close(event: Any) -> None:
                await self.remove_connection(connection_id=event.data["connection_id"])

            connection.once(event_type=EventType.CONNECTION_CLOSED, handler=on_close)
            connection.once(event_type=EventType.CONNECTION_LOST, handler=self._handle_connection_lost)

            self._stats["total_created"] += 1
            self._update_stats_unsafe()
            self._log.debug("Added connection %s (total: %d)", connection_id, len(self._resources))
            return connection_id

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed statistics about the managed connections."""
        if self._lock is None:
            return {}

        stats = await super().get_stats()
        async with self._lock:
            states: dict[str, int] = defaultdict(int)
            for conn in self._resources.values():
                states[conn.state] += 1
            stats["states"] = dict(states)
        return stats

    async def remove_connection(self, *, connection_id: ConnectionId) -> WebTransportConnection | None:
        """Remove a connection from the manager by its ID."""
        if self._lock is None:
            return None

        async with self._lock:
            connection = self._resources.pop(connection_id, None)
            if connection:
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                self._log.debug("Removed connection %s (total: %d)", connection_id, len(self._resources))
            return connection

    async def _close_idle_resources(self, idle_resources: list[WebTransportConnection]) -> None:
        """Close idle connection resources."""
        if self._lock is None:
            return

        async with self._lock:
            for resource in idle_resources:
                if resource.connection_id in self._resources:
                    self._resources.pop(resource.connection_id, None)
                    self._stats["total_closed"] += 1
            self._update_stats_unsafe()

        try:
            async with asyncio.TaskGroup() as tg:
                for resource in idle_resources:
                    tg.create_task(resource.close(reason="Idle timeout"))
        except* Exception as eg:
            self._log.error(
                "Errors occurred while closing idle connections: %s",
                eg.exceptions,
                exc_info=eg,
            )

    async def _close_resource(self, resource: WebTransportConnection) -> None:
        """Close a single connection resource."""
        if not resource.is_closed:
            await resource.close()

    def _get_resource_id(self, resource: WebTransportConnection) -> ConnectionId:
        """Get the unique ID from a connection object."""
        return resource.connection_id

    async def _handle_connection_lost(self, event: Any) -> None:
        """Handle the unexpected loss of a connection."""
        connection_id = event.data["connection_id"]
        self._log.warning("Handling lost connection: %s", connection_id)
        connection = await self.remove_connection(connection_id=connection_id)
        if connection and not connection.is_closed:
            try:
                await connection.close(reason="Connection was lost.")
            except Exception as e:
                self._log.error("Error while closing lost connection %s: %s", connection_id, e, exc_info=e)

    def _is_resource_closed(self, resource: WebTransportConnection) -> bool:
        """Check if a connection resource is closed."""
        return resource.is_closed

    def _on_idle_check_done(self, task: asyncio.Task[None]) -> None:
        """Handle the completion of the idle check task."""
        if self._is_shutting_down:
            return

        if not task.cancelled():
            if exc := task.exception():
                self._log.error("Connection idle check task finished unexpectedly: %s.", exc, exc_info=exc)

        if not self._is_shutting_down:
            asyncio.create_task(self.shutdown())

    async def _periodic_idle_check(self) -> None:
        """Periodically check for and close idle connections."""
        if self._lock is None:
            self._log.warning("Idle check task running on uninitialized ConnectionManager; stopping.")
            return

        try:
            while True:
                try:
                    idle_connections_to_close = []
                    now = get_timestamp()

                    async with self._lock:
                        all_connections = list(self._resources.values())

                    for conn in all_connections:
                        if conn.is_closing or conn.is_closed:
                            continue

                        if self._idle_timeout > 0 and conn.last_activity_time > 0:
                            idle_duration = now - conn.last_activity_time
                            if idle_duration >= self._idle_timeout:
                                idle_connections_to_close.append(conn)

                    if idle_connections_to_close:
                        self._log.info("Closing %d idle connections.", len(idle_connections_to_close))
                        await self._close_idle_resources(idle_connections_to_close)

                except Exception as e:
                    self._log.error("Idle connection check cycle failed: %s", e, exc_info=e)

                await asyncio.sleep(self._idle_check_interval)
        except (Exception, asyncio.CancelledError):
            pass

    def _start_background_tasks(self) -> None:
        """Start all periodic background tasks."""
        super()._start_background_tasks()
        if self._idle_check_task is None or self._idle_check_task.done():
            self._idle_check_task = asyncio.create_task(self._periodic_idle_check())
            self._idle_check_task.add_done_callback(self._on_idle_check_done)
            self._background_tasks_to_cancel.append(self._idle_check_task)
