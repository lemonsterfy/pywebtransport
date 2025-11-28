"""Robust pool for managing WebTransportStream objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pywebtransport.pool._base import _AsyncObjectPool
from pywebtransport.stream.stream import WebTransportStream

if TYPE_CHECKING:
    from pywebtransport.session.session import WebTransportSession


__all__: list[str] = ["StreamPool"]


class StreamPool(_AsyncObjectPool[WebTransportStream]):
    """A robust pool for reusing and managing concurrent bidirectional streams."""

    def __init__(self, *, session: WebTransportSession, max_size: int) -> None:
        """Initialize the stream pool."""

        async def factory() -> WebTransportStream:
            return await session.create_bidirectional_stream()

        super().__init__(max_size=max_size, factory=factory)

    async def _dispose(self, stream: WebTransportStream) -> None:
        """Close and dispose of a single stream object."""
        if not stream.is_closed:
            await stream.close()
