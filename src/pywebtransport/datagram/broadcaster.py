"""WebTransport Datagram Broadcaster."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import TYPE_CHECKING, Self

from pywebtransport.exceptions import DatagramError
from pywebtransport.types import Data
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.datagram.transport import WebTransportDatagramTransport


__all__ = ["DatagramBroadcaster"]

logger = get_logger(name="datagram.broadcaster")


class DatagramBroadcaster:
    """A broadcaster to send datagrams to multiple transports concurrently."""

    def __init__(self) -> None:
        """Initialize the datagram broadcaster."""
        self._transports: list[WebTransportDatagramTransport] = []
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
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, clearing the transport list."""
        if self._lock:
            async with self._lock:
                self._transports.clear()

    async def add_transport(self, *, transport: WebTransportDatagramTransport) -> None:
        """Add a transport to the broadcast list."""
        if self._lock is None:
            raise DatagramError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            if transport not in self._transports:
                self._transports.append(transport)

    async def broadcast(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> int:
        """Broadcast a datagram to all registered transports concurrently."""
        if self._lock is None:
            raise DatagramError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        sent_count = 0
        failed_transports = []

        async with self._lock:
            transports_copy = self._transports.copy()

        active_transports = []
        tasks = []
        for transport in transports_copy:
            if not transport.is_closed:
                tasks.append(transport.send(data=data, priority=priority, ttl=ttl))
                active_transports.append(transport)
            else:
                failed_transports.append(transport)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for transport, result in zip(active_transports, results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Failed to broadcast to transport %s: %s",
                        transport,
                        result,
                        exc_info=True,
                    )
                    failed_transports.append(transport)
                else:
                    sent_count += 1

        if failed_transports:
            async with self._lock:
                for transport in failed_transports:
                    if transport in self._transports:
                        self._transports.remove(transport)

        return sent_count

    async def remove_transport(self, *, transport: WebTransportDatagramTransport) -> None:
        """Remove a transport from the broadcast list."""
        if self._lock is None:
            raise DatagramError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            try:
                self._transports.remove(transport)
            except ValueError:
                pass

    async def get_transport_count(self) -> int:
        """Get the current number of active transports safely."""
        if self._lock is None:
            raise DatagramError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            return len(self._transports)
