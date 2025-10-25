"""Manager for session-level stream lifecycles and concurrency."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Self, TypeAlias

from pywebtransport.constants import DEFAULT_MAX_STREAMS, DEFAULT_STREAM_CLEANUP_INTERVAL
from pywebtransport.exceptions import StreamError
from pywebtransport.manager._base import _BaseResourceManager
from pywebtransport.stream.stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.types import StreamId
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__: list[str] = ["StreamManager", "StreamType"]

StreamType: TypeAlias = WebTransportStream | WebTransportReceiveStream | WebTransportSendStream

logger = get_logger(name=__name__)


class StreamManager(_BaseResourceManager[StreamId, StreamType]):
    """Manage all streams within a session, enforcing resource limits."""

    _log = logger

    def __init__(
        self,
        *,
        stream_factory: Callable[[bool], Awaitable[StreamId]],
        session_factory: Callable[[], WebTransportSession],
        max_streams: int = DEFAULT_MAX_STREAMS,
        stream_cleanup_interval: float = DEFAULT_STREAM_CLEANUP_INTERVAL,
    ) -> None:
        """Initialize the stream manager."""
        super().__init__(
            resource_name="stream",
            max_resources=max_streams,
            cleanup_interval=stream_cleanup_interval,
        )
        self._stream_factory = stream_factory
        self._session_factory = session_factory
        self._creation_semaphore: asyncio.Semaphore | None = None
        self._created_stream_ids: set[StreamId] = set()

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context, initializing resources and starting background tasks."""
        await super().__aenter__()
        self._creation_semaphore = asyncio.Semaphore(value=self._max_resources)
        return self

    async def shutdown(self) -> None:
        """Shut down the stream manager gracefully."""
        await super().shutdown()

    async def add_stream(self, *, stream: StreamType) -> None:
        """Add an externally created stream to the manager."""
        if self._lock is None:
            raise StreamError(
                message=(
                    "StreamManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if stream.stream_id in self._resources:
                return

            self._resources[stream.stream_id] = stream
            self._stats["total_created"] += 1
            self._update_stats_unsafe()
            self._log.debug("Added stream %d (total: %d)", stream.stream_id, self._stats["current_count"])

    async def create_bidirectional_stream(self) -> WebTransportStream:
        """Create a new bidirectional stream, respecting concurrency limits."""
        if self._creation_semaphore is None:
            raise StreamError(
                message=(
                    "StreamManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        if self._creation_semaphore.locked():
            raise StreamError(message=f"Cannot create new stream: stream limit ({self._max_resources}) reached.")

        await self._creation_semaphore.acquire()
        try:
            stream_id = await self._stream_factory(False)
            stream = WebTransportStream(session=self._session_factory(), stream_id=stream_id)
            await self.add_stream(stream=stream)
            self._created_stream_ids.add(stream_id)
            return stream
        except Exception:
            self._creation_semaphore.release()
            raise

    async def create_unidirectional_stream(self) -> WebTransportSendStream:
        """Create a new unidirectional stream, respecting concurrency limits."""
        if self._creation_semaphore is None:
            raise StreamError(
                message=(
                    "StreamManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        if self._creation_semaphore.locked():
            raise StreamError(message=f"Cannot create new stream: stream limit ({self._max_resources}) reached.")

        await self._creation_semaphore.acquire()
        try:
            stream_id = await self._stream_factory(True)
            stream = WebTransportSendStream(session=self._session_factory(), stream_id=stream_id)
            await self.add_stream(stream=stream)
            self._created_stream_ids.add(stream_id)
            return stream
        except Exception:
            self._creation_semaphore.release()
            raise

    async def remove_stream(self, *, stream_id: StreamId) -> StreamType | None:
        """Remove a stream from the manager by its ID."""
        if self._lock is None or self._creation_semaphore is None:
            return None

        async with self._lock:
            stream = self._resources.pop(stream_id, None)
            if stream:
                if stream_id in self._created_stream_ids:
                    self._creation_semaphore.release()
                    self._created_stream_ids.remove(stream_id)
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                self._log.debug("Removed stream %d (total: %d)", stream_id, self._stats["current_count"])
            return stream

    async def cleanup_closed_streams(self) -> int:
        """Find and remove any streams that are marked as closed."""
        if self._is_shutting_down or self._lock is None or self._creation_semaphore is None:
            return 0

        closed_stream_ids = []
        async with self._lock:
            for stream_id, stream in list(self._resources.items()):
                if self._is_resource_closed(stream):
                    closed_stream_ids.append(stream_id)
                    del self._resources[stream_id]

            if closed_stream_ids:
                for stream_id in closed_stream_ids:
                    if stream_id in self._created_stream_ids:
                        self._creation_semaphore.release()
                        self._created_stream_ids.remove(stream_id)
                self._stats["total_closed"] += len(closed_stream_ids)
                self._update_stats_unsafe()
                self._log.debug("Cleaned up %d closed streams", len(closed_stream_ids))

        return len(closed_stream_ids)

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed statistics about the managed streams."""
        if self._lock is None or self._creation_semaphore is None:
            return {}

        stats = await super().get_stats()
        async with self._lock:
            states: dict[str, int] = defaultdict(int)
            directions: dict[str, int] = defaultdict(int)
            for stream in self._resources.values():
                if hasattr(stream, "state"):
                    states[stream.state] += 1
                if hasattr(stream, "direction"):
                    directions[getattr(stream, "direction", "unknown")] += 1

            stats["semaphore_locked"] = self._creation_semaphore.locked()
            stats["semaphore_value"] = getattr(self._creation_semaphore, "_value", "N/A")
            stats["states"] = dict(states)
            stats["directions"] = dict(directions)
        return stats

    async def _close_resource(self, resource: StreamType) -> None:
        """Close a single stream resource."""
        if not resource.is_closed:
            await resource.close()

    def _get_resource_id(self, resource: StreamType) -> StreamId:
        """Get the unique ID from a stream object."""
        return resource.stream_id

    def _is_resource_closed(self, resource: StreamType) -> bool:
        """Check if a stream resource is closed."""
        return resource.is_closed

    async def __aiter__(self) -> AsyncIterator[StreamType]:
        """Return an async iterator over a snapshot of the managed streams."""
        if self._lock is None:
            raise StreamError(
                message=(
                    "StreamManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            resources_copy = list(self._resources.values())

        for resource in resources_copy:
            yield resource

    def __contains__(self, item: object) -> bool:
        """Check if a stream ID is being managed."""
        if not isinstance(item, int):
            return False
        return item in self._resources
