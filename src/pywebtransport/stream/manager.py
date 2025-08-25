"""
WebTransport stream management and orchestration.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from types import TracebackType
from typing import TYPE_CHECKING, Any, AsyncIterator, Self, Type

from pywebtransport.constants import WebTransportConstants
from pywebtransport.exceptions import StreamError
from pywebtransport.stream.stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.types import StreamId
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__ = ["StreamManager"]

logger = get_logger("stream.manager")

StreamType = WebTransportStream | WebTransportReceiveStream | WebTransportSendStream


class StreamManager:
    """Manages all streams within a session, enforcing resource limits."""

    def __init__(
        self,
        session: WebTransportSession,
        *,
        max_streams: int = WebTransportConstants.DEFAULT_MAX_STREAMS,
        stream_cleanup_interval: float = WebTransportConstants.DEFAULT_STREAM_CLEANUP_INTERVAL,
    ):
        """Initialize the stream manager."""
        self._session = session
        self._max_streams = max_streams
        self._cleanup_interval = stream_cleanup_interval
        self._streams: dict[StreamId, StreamType] = {}
        self._lock: asyncio.Lock | None = None
        self._creation_semaphore: asyncio.Semaphore | None = None
        self._stats = {"total_created": 0, "total_closed": 0, "current_count": 0, "max_concurrent": 0}
        self._cleanup_task: asyncio.Task[None] | None = None

    @classmethod
    def create(
        cls,
        session: WebTransportSession,
        *,
        max_streams: int = WebTransportConstants.DEFAULT_MAX_STREAMS,
        stream_cleanup_interval: float = WebTransportConstants.DEFAULT_STREAM_CLEANUP_INTERVAL,
    ) -> Self:
        """Factory method to create a new stream manager instance."""
        return cls(session, max_streams=max_streams, stream_cleanup_interval=stream_cleanup_interval)

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context, initializing resources and starting background tasks."""
        self._lock = asyncio.Lock()
        self._creation_semaphore = asyncio.Semaphore(self._max_streams)
        self._start_cleanup_task()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the asynchronous context, shutting down the manager."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the manager and all associated tasks and streams."""
        logger.info("Shutting down stream manager")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.close_all_streams()
        logger.info("Stream manager shutdown complete")

    async def add_stream(self, stream: StreamType) -> None:
        """Add an externally created stream to the manager."""
        if self._lock is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            if stream.stream_id in self._streams:
                return
            self._streams[stream.stream_id] = stream
            self._stats["total_created"] += 1
            self._update_stats_unsafe()
            logger.debug(f"Added stream {stream.stream_id} (total: {self._stats['current_count']})")

    async def close_all_streams(self) -> None:
        """Close and remove all currently managed streams."""
        if self._lock is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        streams_to_close: list[StreamType] = []
        num_to_close = 0
        async with self._lock:
            if not self._streams:
                return

            streams_to_close = list(self._streams.values())
            num_to_close = len(streams_to_close)
            logger.info(f"Initiating shutdown for {num_to_close} managed streams.")

            self._stats["total_closed"] += num_to_close
            self._streams.clear()
            self._update_stats_unsafe()

        try:
            async with asyncio.TaskGroup() as tg:
                for stream in streams_to_close:
                    if not stream.is_closed:
                        tg.create_task(stream.close())
        except* Exception as eg:
            logger.error(f"Errors occurred while closing managed streams: {eg.exceptions}")
            raise
        finally:
            if self._creation_semaphore:
                for _ in range(num_to_close):
                    self._creation_semaphore.release()

    async def create_bidirectional_stream(self) -> WebTransportStream:
        """Create a new bidirectional stream, respecting concurrency limits."""
        if self._creation_semaphore is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        if self._creation_semaphore.locked():
            raise StreamError(f"Cannot create new stream: stream limit ({self._max_streams}) reached.")

        await self._creation_semaphore.acquire()
        try:
            stream_id = await self._session._create_stream_on_protocol(is_unidirectional=False)
            stream = WebTransportStream(session=self._session, stream_id=stream_id)
            await self.add_stream(stream)
            return stream
        except Exception:
            self._creation_semaphore.release()
            raise

    async def create_unidirectional_stream(self) -> WebTransportSendStream:
        """Create a new unidirectional stream, respecting concurrency limits."""
        if self._creation_semaphore is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        if self._creation_semaphore.locked():
            raise StreamError(f"Cannot create new stream: stream limit ({self._max_streams}) reached.")

        await self._creation_semaphore.acquire()
        try:
            stream_id = await self._session._create_stream_on_protocol(is_unidirectional=True)
            stream = WebTransportSendStream(session=self._session, stream_id=stream_id)
            await self.add_stream(stream)
            return stream
        except Exception:
            self._creation_semaphore.release()
            raise

    async def remove_stream(self, stream_id: StreamId) -> StreamType | None:
        """Remove a stream from the manager by its ID."""
        if self._lock is None or self._creation_semaphore is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            stream = self._streams.pop(stream_id, None)
            if stream:
                self._creation_semaphore.release()
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                logger.debug(f"Removed stream {stream_id} (total: {self._stats['current_count']})")
            return stream

    async def cleanup_closed_streams(self) -> int:
        """Find and remove any streams that are marked as closed."""
        if self._lock is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        closed_stream_ids = []
        async with self._lock:
            for stream_id, stream in list(self._streams.items()):
                if stream.is_closed:
                    closed_stream_ids.append(stream_id)
                    del self._streams[stream_id]

            if closed_stream_ids:
                if self._creation_semaphore:
                    for _ in closed_stream_ids:
                        self._creation_semaphore.release()
                self._stats["total_closed"] += len(closed_stream_ids)
                self._update_stats_unsafe()
                logger.debug(f"Cleaned up {len(closed_stream_ids)} closed streams")
        return len(closed_stream_ids)

    async def get_all_streams(self) -> list[StreamType]:
        """Retrieve a list of all currently managed streams."""
        if self._lock is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            return list(self._streams.values())

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed statistics about the managed streams."""
        if self._lock is None or self._creation_semaphore is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            states: dict[str, int] = defaultdict(int)
            directions: dict[str, int] = defaultdict(int)
            for stream in self._streams.values():
                if hasattr(stream, "state"):
                    states[stream.state] += 1
                if hasattr(stream, "direction"):
                    directions[getattr(stream, "direction", "unknown")] += 1

            return {
                **self._stats,
                "active_streams": len(self._streams),
                "semaphore_locked": self._creation_semaphore.locked(),
                "semaphore_value": getattr(self._creation_semaphore, "_value", "N/A"),
                "states": dict(states),
                "directions": dict(directions),
                "max_streams": self._max_streams,
            }

    async def get_stream(self, stream_id: StreamId) -> StreamType | None:
        """Retrieve a stream by its ID in a thread-safe manner."""
        if self._lock is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            return self._streams.get(stream_id)

    async def _periodic_cleanup(self) -> None:
        """Periodically run the cleanup process to remove closed streams."""
        try:
            while True:
                try:
                    await self.cleanup_closed_streams()
                except Exception as e:
                    logger.error(f"Stream cleanup cycle failed: {e}", exc_info=e)

                await asyncio.sleep(self._cleanup_interval)
        except asyncio.CancelledError:
            pass

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task if it is not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            except RuntimeError:
                logger.warning("Could not start cleanup task: no running event loop.")

    def _update_stats_unsafe(self) -> None:
        """Update internal statistics (must be called within a lock)."""
        count = len(self._streams)
        self._stats["current_count"] = count
        self._stats["max_concurrent"] = max(self._stats["max_concurrent"], count)

    async def __aiter__(self) -> AsyncIterator[StreamType]:
        """Return an async iterator over a snapshot of the managed streams."""
        if self._lock is None:
            raise StreamError(
                "StreamManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            streams_copy = list(self._streams.values())
        for stream in streams_copy:
            yield stream

    def __contains__(self, stream_id: object) -> bool:
        """Check if a stream ID is being managed."""
        if not isinstance(stream_id, int):
            return False
        return stream_id in self._streams

    def __len__(self) -> int:
        """Return the current number of managed streams."""
        return len(self._streams)
