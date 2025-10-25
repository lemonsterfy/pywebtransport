"""Robust pool for managing WebTransportConnection objects."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.pool._base import _AsyncObjectPool

if TYPE_CHECKING:
    from pywebtransport.config import ClientConfig

__all__: list[str] = ["ConnectionPool"]


class ConnectionPool(_AsyncObjectPool[WebTransportConnection]):
    """A robust pool for reusing and managing concurrent WebTransport connections."""

    def __init__(
        self,
        *,
        config: ClientConfig,
        host: str,
        port: int,
        path: str = "/",
        max_size: int,
    ) -> None:
        """Initialize the connection pool."""

        async def factory() -> WebTransportConnection:
            return await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)

        super().__init__(max_size=max_size, factory=factory)

    async def _dispose(self, conn: WebTransportConnection) -> None:
        """Close and dispose of a single connection object."""
        if not conn.is_closed:
            await conn.close()
