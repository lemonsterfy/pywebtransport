"""Robust pool for managing WebTransportSession objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pywebtransport.pool._base import _AsyncObjectPool
from pywebtransport.session.session import WebTransportSession

if TYPE_CHECKING:
    from pywebtransport.client.client import WebTransportClient
    from pywebtransport.types import URL


__all__: list[str] = ["SessionPool"]


class SessionPool(_AsyncObjectPool[WebTransportSession]):
    """A robust pool for reusing and managing concurrent sessions for a client and URL."""

    def __init__(
        self,
        *,
        client: WebTransportClient,
        url: URL,
        max_size: int,
    ) -> None:
        """Initialize the session pool."""

        async def factory() -> WebTransportSession:
            return await client.connect(url=url)

        super().__init__(max_size=max_size, factory=factory)

    async def _dispose(self, session: WebTransportSession) -> None:
        """Close and dispose of a single session object."""
        if not session.is_closed:
            await session.close()
