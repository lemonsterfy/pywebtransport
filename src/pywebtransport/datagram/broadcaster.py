"""
WebTransport Datagram Broadcaster.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import TYPE_CHECKING, Self, Type

from pywebtransport.exceptions import DatagramError
from pywebtransport.types import Data
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.datagram.transport import WebTransportDatagramDuplexStream


__all__ = ["DatagramBroadcaster"]

logger = get_logger(name="datagram.broadcaster")


class DatagramBroadcaster:
    """A broadcaster to send datagrams to multiple streams concurrently."""

    def __init__(self) -> None:
        """Initialize the datagram broadcaster."""
        self._streams: list[WebTransportDatagramDuplexStream] = []
        self._lock: asyncio.Lock | None = None

    @classmethod
    def create(cls) -> Self:
        """Factory method to create a new datagram broadcaster instance."""
        return cls()

    async def __aenter__(self) -> Self:
        """Enter async context, initializing asyncio resources."""
        self._lock = asyncio.Lock()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, clearing the stream list."""
        if self._lock:
            async with self._lock:
                self._streams.clear()

    async def add_stream(self, *, stream: WebTransportDatagramDuplexStream) -> None:
        """Add a stream to the broadcast list."""
        if self._lock is None:
            raise DatagramError(
                "DatagramBroadcaster has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            if stream not in self._streams:
                self._streams.append(stream)

    async def broadcast(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> int:
        """Broadcast a datagram to all registered streams concurrently."""
        if self._lock is None:
            raise DatagramError(
                "DatagramBroadcaster has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        sent_count = 0
        failed_streams = []

        async with self._lock:
            streams_copy = self._streams.copy()

        active_streams = []
        tasks = []
        for stream in streams_copy:
            if not stream.is_closed:
                tasks.append(stream.send(data=data, priority=priority, ttl=ttl))
                active_streams.append(stream)
            else:
                failed_streams.append(stream)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for stream, result in zip(active_streams, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Failed to broadcast to stream %s: %s",
                        stream,
                        result,
                        exc_info=True,
                    )
                    failed_streams.append(stream)
                else:
                    sent_count += 1

        if failed_streams:
            async with self._lock:
                for stream in failed_streams:
                    if stream in self._streams:
                        self._streams.remove(stream)

        return sent_count

    async def remove_stream(self, *, stream: WebTransportDatagramDuplexStream) -> None:
        """Remove a stream from the broadcast list."""
        if self._lock is None:
            raise DatagramError(
                "DatagramBroadcaster has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            try:
                self._streams.remove(stream)
            except ValueError:
                pass

    async def get_stream_count(self) -> int:
        """Get the current number of active streams safely."""
        if self._lock is None:
            raise DatagramError(
                "DatagramBroadcaster has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            return len(self._streams)
