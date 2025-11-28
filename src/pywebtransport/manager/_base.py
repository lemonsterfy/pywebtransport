"""Reusable base class for managing event-driven resources."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Any, ClassVar, Generic, Protocol, Self, TypeVar, runtime_checkable

from pywebtransport.events import Event, EventEmitter
from pywebtransport.types import EventType
from pywebtransport.utils import get_logger

__all__: list[str] = []

ResourceId = TypeVar("ResourceId")


@runtime_checkable
class ManageableResource(Protocol):
    """Define the protocol for a resource manageable by this class."""

    events: EventEmitter


ResourceType = TypeVar("ResourceType", bound=ManageableResource)


logger = get_logger(name=__name__)


class _BaseResourceManager(ABC, Generic[ResourceId, ResourceType]):
    """Manage the lifecycle of concurrent resources abstractly via events."""

    _log: ClassVar[logging.Logger] = logger
    _resource_closed_event_type: ClassVar[EventType]

    def __init__(self, *, resource_name: str, max_resources: int) -> None:
        """Initialize the base resource manager."""
        self._resource_name = resource_name
        self._max_resources = max_resources
        self._lock: asyncio.Lock | None = None
        self._resources: dict[ResourceId, ResourceType] = {}
        self._stats = {"total_created": 0, "total_closed": 0, "current_count": 0, "max_concurrent": 0}
        self._is_shutting_down = False
        self._background_tasks_to_cancel: list[asyncio.Task[None] | None] = []
        self._event_handlers: dict[ResourceId, tuple[EventEmitter, Callable[[Event], Awaitable[None]]]] = {}

    async def __aenter__(self) -> Self:
        """Enter async context and initialize resources."""
        self._lock = asyncio.Lock()
        self._start_background_tasks()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit async context and shut down the manager."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the manager and all associated tasks and resources."""
        if self._is_shutting_down:
            return

        self._is_shutting_down = True
        self._log.info("Shutting down %s manager", self._resource_name)

        await self._cancel_background_tasks()
        await self._close_all_resources()
        self._log.info("%s manager shutdown complete", self._resource_name)

    async def add_resource(self, *, resource: ResourceType) -> None:
        """Add a new resource and subscribe to its closure event."""
        if self._lock is None:
            raise RuntimeError(f"{self.__class__.__name__} is not activated. Use 'async with'.")
        if self._is_shutting_down:
            self._log.warning("Attempted to add resource to shutting down %s manager.", self._resource_name)
            await self._close_resource(resource=resource)
            raise RuntimeError(f"{self.__class__.__name__} is shutting down.")

        resource_id = self._get_resource_id(resource)
        emitter = resource.events

        async with self._lock:
            if resource_id in self._resources:
                self._log.debug("Resource %s already managed.", resource_id)
                return
            if len(self._resources) >= self._max_resources > 0:
                self._log.error(
                    "Maximum %s limit (%d) reached. Cannot add %s.",
                    self._resource_name,
                    self._max_resources,
                    resource_id,
                )
                await self._close_resource(resource=resource)
                raise RuntimeError(f"Maximum {self._resource_name} limit reached")

            self._resources[resource_id] = resource
            self._stats["total_created"] += 1
            self._update_stats_unsafe()

            async def closed_handler_wrapper(event: Event) -> None:
                event_resource_id: ResourceId | None = None
                if isinstance(event.data, dict):
                    event_resource_id = event.data.get(f"{self._resource_name}_id")

                if event_resource_id == resource_id:
                    await self._handle_resource_closed(resource_id=resource_id)
                else:
                    self._log.warning(
                        "Received close event without expected resource ID in data for %s (Expected %s, Data: %s)",
                        self._resource_name,
                        resource_id,
                        event.data,
                    )

            emitter.once(event_type=self._resource_closed_event_type, handler=closed_handler_wrapper)

            self._log.debug("Added %s %s (total: %d)", self._resource_name, resource_id, self._stats["current_count"])

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
            stats["current_count"] = len(self._resources)
            stats["active"] = len(self._resources)
            stats[f"max_{self._resource_name}s"] = self._max_resources
            return stats

    async def _cancel_background_tasks(self) -> None:
        """Cancel all running background tasks."""
        tasks_to_cancel = self._background_tasks_to_cancel

        active_tasks = [task for task in tasks_to_cancel if task and not task.done()]
        if not active_tasks:
            return

        for task in active_tasks:
            task.cancel()
        await asyncio.gather(*active_tasks, return_exceptions=True)

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
                    tg.create_task(coro=self._close_resource(resource=resource))
        except* Exception as eg:
            self._log.error(
                "Errors occurred while closing managed %ss: %s", self._resource_name, eg.exceptions, exc_info=eg
            )

        async with self._lock:
            if self._stats["current_count"] != 0:
                self._stats["total_closed"] += len(resources_to_close)
            self._update_stats_unsafe()
        self._log.info("All managed %ss processed for closure.", self._resource_name)

    @abstractmethod
    async def _close_resource(self, resource: ResourceType) -> None:
        """Close a single resource (must be implemented by subclasses)."""
        raise NotImplementedError

    @abstractmethod
    def _get_resource_id(self, resource: ResourceType) -> ResourceId:
        """Get the unique ID from a resource object (must be implemented by subclasses)."""
        raise NotImplementedError

    async def _handle_resource_closed(self, *, resource_id: ResourceId) -> None:
        """Handle the closure event for a managed resource."""
        if self._lock is None:
            return

        removed_resource: ResourceType | None = None
        async with self._lock:
            removed_resource = self._resources.pop(resource_id, None)
            if removed_resource:
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                self._log.debug(
                    "Removed closed %s %s (total: %d)", self._resource_name, resource_id, self._stats["current_count"]
                )

        if removed_resource:
            self._on_resource_removed(resource_id=resource_id)

    def _on_background_task_done(self, task: asyncio.Task[None]) -> None:
        """Handle the completion of a background task added by subclasses."""
        if self._is_shutting_down:
            return

        if task.cancelled():
            return

        if exc := task.exception():
            self._log.error(
                "%s background task finished unexpectedly: %s.", self._resource_name.capitalize(), exc, exc_info=exc
            )
            asyncio.create_task(coro=self.shutdown())

    def _on_resource_removed(self, *, resource_id: ResourceId) -> None:
        """Hook for subclasses after a resource is removed."""
        pass

    def _start_background_tasks(self) -> None:
        """Start all periodic background tasks (hook for subclasses)."""
        pass

    def _update_stats_unsafe(self) -> None:
        """Update internal statistics (must be called within a lock)."""
        current_count = len(self._resources)
        self._stats["current_count"] = current_count
        self._stats["max_concurrent"] = max(self._stats["max_concurrent"], current_count)

    def __len__(self) -> int:
        """Return the current number of managed resources."""
        return len(self._resources)
