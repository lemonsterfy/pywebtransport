"""
WebTransport Datagram Broadcaster.
"""

import asyncio
from typing import TYPE_CHECKING, List, Optional

from ..types import Data
from ..utils import get_logger

if TYPE_CHECKING:
    from .transport import WebTransportDatagramDuplexStream


__all__ = ["DatagramBroadcaster"]

logger = get_logger("datagram.broadcaster")


class DatagramBroadcaster:
    """A broadcaster to send datagrams to multiple streams concurrently."""

    def __init__(self) -> None:
        """Initialize the datagram broadcaster."""
        self._streams: List["WebTransportDatagramDuplexStream"] = []
        self._lock = asyncio.Lock()

    @classmethod
    def create(cls) -> "DatagramBroadcaster":
        """Factory method to create a new datagram broadcaster instance."""
        return cls()

    async def add_stream(self, stream: "WebTransportDatagramDuplexStream") -> None:
        """Add a stream to the broadcast list."""
        async with self._lock:
            if stream not in self._streams:
                self._streams.append(stream)

    async def remove_stream(self, stream: "WebTransportDatagramDuplexStream") -> None:
        """Remove a stream from the broadcast list."""
        async with self._lock:
            try:
                self._streams.remove(stream)
            except ValueError:
                pass

    async def broadcast(self, data: Data, *, priority: int = 0, ttl: Optional[float] = None) -> int:
        """Broadcast a datagram to all registered streams concurrently."""
        sent_count = 0
        failed_streams = []

        async with self._lock:
            streams_copy = self._streams.copy()

        active_streams = []
        tasks = []
        for stream in streams_copy:
            if not stream.is_closed:
                tasks.append(stream.send(data, priority=priority, ttl=ttl))
                active_streams.append(stream)
            else:
                failed_streams.append(stream)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for stream, result in zip(active_streams, results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to broadcast to stream {stream}: {result}")
                    failed_streams.append(stream)
                else:
                    sent_count += 1

        if failed_streams:
            async with self._lock:
                for stream in failed_streams:
                    if stream in self._streams:
                        self._streams.remove(stream)

        return sent_count

    async def get_stream_count(self) -> int:
        """Get the current number of active streams safely."""
        async with self._lock:
            return len(self._streams)
