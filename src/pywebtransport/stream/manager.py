"""
WebTransport stream management and orchestration.
"""

import asyncio
from collections import defaultdict
from types import TracebackType
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Type, Union

from pywebtransport.stream.stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.types import StreamId
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__ = ["StreamManager"]

logger = get_logger("stream.manager")

StreamType = Union[WebTransportStream, WebTransportReceiveStream, WebTransportSendStream]


class StreamManager:
    """Manages all streams within a session, enforcing resource limits."""

    def __init__(
        self,
        session: "WebTransportSession",
        *,
        max_streams: int = 100,
        cleanup_interval: float = 60.0,
    ):
        """Initialize the stream manager."""
        self._session = session
        self._max_streams = max_streams
        self._cleanup_interval = cleanup_interval

        self._streams: Dict[StreamId, StreamType] = {}
        self._lock = asyncio.Lock()
        self._creation_semaphore = asyncio.Semaphore(max_streams)
        self._stats = {
            "total_created": 0,
            "total_closed": 0,
            "current_count": 0,
            "max_concurrent": 0,
        }
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    @classmethod
    def create(
        cls,
        session: "WebTransportSession",
        *,
        max_streams: int = 100,
        cleanup_interval: float = 60.0,
    ) -> "StreamManager":
        """Factory method to create a new stream manager instance."""
        return cls(session, max_streams=max_streams, cleanup_interval=cleanup_interval)

    async def __aenter__(self) -> "StreamManager":
        """Enter the asynchronous context, starting background tasks."""
        self._start_cleanup_task()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the asynchronous context, shutting down the manager."""
        await self.shutdown()

    def __len__(self) -> int:
        """Return the current number of managed streams."""
        return len(self._streams)

    def __contains__(self, stream_id: object) -> bool:
        """Check if a stream ID is being managed."""
        if not isinstance(stream_id, int):
            return False
        return stream_id in self._streams

    async def __aiter__(self) -> AsyncIterator[StreamType]:
        """Return an async iterator over a snapshot of the managed streams."""
        async with self._lock:
            streams_copy = list(self._streams.values())
        for stream in streams_copy:
            yield stream

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

    async def close_all_streams(self) -> None:
        """Close all currently managed streams."""
        async with self._lock:
            streams_to_close = list(self._streams.values())
            if not streams_to_close:
                return
            logger.info(f"Closing {len(streams_to_close)} managed streams.")

        close_tasks = [stream.close() for stream in streams_to_close if not stream.is_closed]
        await asyncio.gather(*close_tasks, return_exceptions=True)

        async with self._lock:
            self._streams.clear()
            self._update_stats_unsafe()

    async def create_bidirectional_stream(self) -> WebTransportStream:
        """Create a new bidirectional stream, respecting concurrency limits."""
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
        await self._creation_semaphore.acquire()
        try:
            stream_id = await self._session._create_stream_on_protocol(is_unidirectional=True)
            stream = WebTransportSendStream(session=self._session, stream_id=stream_id)
            await self.add_stream(stream)
            return stream
        except Exception:
            self._creation_semaphore.release()
            raise

    async def add_stream(self, stream: StreamType) -> None:
        """Add an externally created stream to the manager."""
        async with self._lock:
            if stream.stream_id in self._streams:
                return
            self._streams[stream.stream_id] = stream
            self._stats["total_created"] += 1
            self._update_stats_unsafe()
            logger.debug(f"Added stream {stream.stream_id} (total: {self._stats['current_count']})")

    async def remove_stream(self, stream_id: StreamId) -> Optional[StreamType]:
        """Remove a stream from the manager by its ID."""
        async with self._lock:
            stream = self._streams.pop(stream_id, None)
            if stream:
                self._creation_semaphore.release()
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                logger.debug(f"Removed stream {stream_id} (total: {self._stats['current_count']})")
            return stream

    async def get_stream(self, stream_id: StreamId) -> Optional[StreamType]:
        """Retrieve a stream by its ID in a thread-safe manner."""
        async with self._lock:
            return self._streams.get(stream_id)

    async def get_all_streams(self) -> List[StreamType]:
        """Retrieve a list of all currently managed streams."""
        async with self._lock:
            return list(self._streams.values())

    async def get_stats(self) -> Dict[str, Any]:
        """Get detailed statistics about the managed streams."""
        async with self._lock:
            states: Dict[str, int] = defaultdict(int)
            directions: Dict[str, int] = defaultdict(int)
            for stream in self._streams.values():
                if hasattr(stream, "state"):
                    states[stream.state.value] += 1
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

    async def cleanup_closed_streams(self) -> int:
        """Find and remove any streams that are marked as closed."""
        closed_stream_ids = []
        async with self._lock:
            all_streams = list(self._streams.items())

        for stream_id, stream in all_streams:
            if stream.is_closed:
                closed_stream_ids.append(stream_id)

        for stream_id in closed_stream_ids:
            await self.remove_stream(stream_id)

        if closed_stream_ids:
            logger.debug(f"Cleaned up {len(closed_stream_ids)} closed streams")
        return len(closed_stream_ids)

    def _start_cleanup_task(self) -> None:
        """Start the periodic cleanup task if it is not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            except RuntimeError:
                logger.warning("Could not start cleanup task: no running event loop.")

    async def _periodic_cleanup(self) -> None:
        """Periodically run the cleanup process to remove closed streams."""
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval)
                await self.cleanup_closed_streams()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Stream cleanup task error: {e}", exc_info=e)

    def _update_stats_unsafe(self) -> None:
        """Update internal statistics (must be called within a lock)."""
        count = len(self._streams)
        self._stats["current_count"] = count
        self._stats["max_concurrent"] = max(self._stats["max_concurrent"], count)
