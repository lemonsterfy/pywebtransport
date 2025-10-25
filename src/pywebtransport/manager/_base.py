"""Generic, reusable base class for managing resources."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from types import TracebackType
from typing import Any, ClassVar, Generic, Self, TypeVar

from pywebtransport.utils import get_logger

__all__: list[str] = []

ResourceId = TypeVar("ResourceId")
ResourceType = TypeVar("ResourceType")

logger = get_logger(name=__name__)


class _BaseResourceManager(ABC, Generic[ResourceId, ResourceType]):
    """Manage the lifecycle of concurrent resources abstractly."""

    _log: ClassVar[logging.Logger] = logger

    def __init__(
        self,
        *,
        resource_name: str,
        max_resources: int,
        cleanup_interval: float,
    ) -> None:
        """Initialize the base resource manager."""
        self._resource_name = resource_name
        self._max_resources = max_resources
        self._cleanup_interval = cleanup_interval
        self._lock: asyncio.Lock | None = None
        self._resources: dict[ResourceId, ResourceType] = {}
        self._stats = {
            "total_created": 0,
            "total_closed": 0,
            "current_count": 0,
            "max_concurrent": 0,
        }
        self._cleanup_task: asyncio.Task[None] | None = None
        self._is_shutting_down = False

    async def __aenter__(self) -> Self:
        """Enter async context, initializing resources and starting background tasks."""
        self._lock = asyncio.Lock()
        self._start_background_tasks()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, shutting down the manager."""
        await self.shutdown()

    async def cleanup_closed_resources(self) -> int:
        """Find and remove any resources that are marked as closed."""
        if self._lock is None:
            return 0

        closed_resource_ids = []
        async with self._lock:
            for resource_id, resource in list(self._resources.items()):
                if self._is_resource_closed(resource):
                    closed_resource_ids.append(resource_id)
                    del self._resources[resource_id]

            if closed_resource_ids:
                self._stats["total_closed"] += len(closed_resource_ids)
                self._update_stats_unsafe()
                self._log.debug("Cleaned up %d closed %ss.", len(closed_resource_ids), self._resource_name)

        return len(closed_resource_ids)

    async def get_all_resources(self) -> list[ResourceType]:
        """Retrieve a list of all current resources."""
        if self._lock is None:
            return []

        async with self._lock:
            return list(self._resources.values())

    async def get_resource(self, *, resource_id: ResourceId) -> ResourceType | None:
        """Retrieve a resource by its ID."""
        if self._lock is None:
            return None

        async with self._lock:
            return self._resources.get(resource_id)

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed statistics about the managed resources."""
        if self._lock is None:
            return {}

        async with self._lock:
            stats = self._stats.copy()
            stats["active"] = len(self._resources)
            stats[f"max_{self._resource_name}s"] = self._max_resources
            return stats

    async def shutdown(self) -> None:
        """Shut down the manager and all associated tasks and resources."""
        if self._is_shutting_down:
            return

        self._is_shutting_down = True
        self._log.info("Shutting down %s manager", self._resource_name)

        await self._cancel_background_tasks()
        await self._close_all_resources()
        self._log.info("%s manager shutdown complete", self._resource_name)

    async def _cancel_background_tasks(self) -> None:
        """Cancel all running background tasks."""
        tasks_to_cancel = [self._cleanup_task]
        tasks_to_cancel.extend(getattr(self, "_background_tasks_to_cancel", []))

        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in tasks_to_cancel if t], return_exceptions=True)

    async def _close_all_resources(self) -> None:
        """Close all currently managed resources."""
        if self._lock is None:
            return

        resources_to_close: list[ResourceType] = []
        async with self._lock:
            if not self._resources:
                return
            resources_to_close = list(self._resources.values())
            self._log.info("Closing %d managed %ss", len(resources_to_close), self._resource_name)
            self._resources.clear()

        try:
            async with asyncio.TaskGroup() as tg:
                for resource in resources_to_close:
                    tg.create_task(self._close_resource(resource))
        except* Exception as eg:
            self._log.error(
                "Errors occurred while closing managed %ss: %s",
                self._resource_name,
                eg.exceptions,
                exc_info=eg,
            )

        async with self._lock:
            self._stats["total_closed"] += len(resources_to_close)
            self._update_stats_unsafe()
        self._log.info("All %ss closed", self._resource_name)

    @abstractmethod
    async def _close_resource(self, resource: ResourceType) -> None:
        """Close a single resource (must be implemented by subclasses)."""
        raise NotImplementedError

    @abstractmethod
    def _get_resource_id(self, resource: ResourceType) -> ResourceId:
        """Get the unique ID from a resource object (must be implemented by subclasses)."""
        raise NotImplementedError

    @abstractmethod
    def _is_resource_closed(self, resource: ResourceType) -> bool:
        """Check if a resource is closed (must be implemented by subclasses)."""
        raise NotImplementedError

    def _on_background_task_done(self, task: asyncio.Task[None]) -> None:
        """Handle the completion of a background task."""
        if self._is_shutting_down:
            return

        if task.cancelled():
            return

        if exc := task.exception():
            self._log.error(
                "%s background task finished unexpectedly: %s.", self._resource_name.capitalize(), exc, exc_info=exc
            )
            asyncio.create_task(self.shutdown())

    async def _periodic_cleanup(self) -> None:
        """Periodically run the cleanup process to remove closed resources."""
        try:
            while True:
                try:
                    await self.cleanup_closed_resources()
                except Exception as e:
                    self._log.error("%s cleanup cycle failed: %s", self._resource_name.capitalize(), e, exc_info=e)

                await asyncio.sleep(self._cleanup_interval)
        except (Exception, asyncio.CancelledError):
            pass

    def _start_background_tasks(self) -> None:
        """Start all periodic background tasks."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            self._cleanup_task.add_done_callback(self._on_background_task_done)

    def _update_stats_unsafe(self) -> None:
        """Update internal statistics (must be called within a lock)."""
        current_count = len(self._resources)
        self._stats["current_count"] = current_count
        self._stats["max_concurrent"] = max(self._stats["max_concurrent"], current_count)

    def __len__(self) -> int:
        """Return the current number of managed resources."""
        return len(self._resources)
