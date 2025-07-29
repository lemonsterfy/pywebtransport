"""
WebTransport Reconnecting Client.
"""

import asyncio
from types import TracebackType
from typing import Optional, Type

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ClientError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import URL
from pywebtransport.utils import get_logger

__all__ = ["ReconnectingClient"]

logger = get_logger("client.reconnecting")


class ReconnectingClient(EventEmitter):
    """A client that automatically reconnects with exponential backoff."""

    def __init__(
        self,
        url: URL,
        *,
        config: Optional[ClientConfig] = None,
        max_retries: int = 5,
        retry_delay: float = 1.0,
        backoff_factor: float = 2.0,
    ):
        """Initialize the reconnecting client."""
        super().__init__()
        self._url = url
        self._config = config or ClientConfig.create()
        self._max_retries = max_retries if max_retries >= 0 else float("inf")
        self._retry_delay = retry_delay
        self._backoff_factor = backoff_factor
        self._client = WebTransportClient.create(config=self._config)
        self._session: Optional[WebTransportSession] = None
        self._reconnect_task: Optional[asyncio.Task[None]] = None
        self._closed = False

    @classmethod
    def create(
        cls,
        url: URL,
        *,
        config: Optional[ClientConfig] = None,
        max_retries: int = 5,
        retry_delay: float = 1.0,
        backoff_factor: float = 2.0,
    ) -> "ReconnectingClient":
        """Factory method to create a new reconnecting client instance."""
        return cls(
            url,
            config=config,
            max_retries=max_retries,
            retry_delay=retry_delay,
            backoff_factor=backoff_factor,
        )

    @property
    def is_connected(self) -> bool:
        """Check if the client is currently connected with a ready session."""
        return self._session is not None and self._session.is_ready

    async def __aenter__(self) -> "ReconnectingClient":
        """Enter the async context, activating the client and starting the reconnect loop."""
        if self._closed:
            raise ClientError("Client is already closed")

        await self._client.__aenter__()
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        logger.info("ReconnectingClient started.")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the async context, ensuring the client is closed."""
        await self.close()

    async def get_session(self) -> Optional[WebTransportSession]:
        """Get the current session if connected, waiting briefly for connection."""
        for _ in range(50):
            if self.is_connected:
                return self._session
            await asyncio.sleep(0.1)
        return None

    async def close(self) -> None:
        """Close the reconnecting client and all its resources."""
        if self._closed:
            return
        logger.info("Closing reconnecting client")
        self._closed = True

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        await self._client.close()
        logger.info("Reconnecting client closed")

    async def _reconnect_loop(self) -> None:
        """Manage the connection lifecycle with an exponential backoff retry strategy."""
        retry_count = 0
        try:
            while not self._closed:
                try:
                    self._session = await self._client.connect(self._url)
                    logger.info(f"Connected to {self._url}")
                    if retry_count > 0:
                        await self.emit("reconnected", data={"session": self._session})
                    retry_count = 0
                    await self._session.wait_closed()
                    if not self._closed:
                        logger.warning(f"Connection to {self._url} lost, attempting to reconnect...")
                except Exception as e:
                    retry_count += 1
                    if retry_count > self._max_retries:
                        logger.error(f"Max retries ({self._max_retries}) exceeded for {self._url}")
                        await self.emit("failed", data={"reason": "max_retries_exceeded"})
                        break
                    delay = min(self._retry_delay * (self._backoff_factor ** (retry_count - 1)), 30.0)
                    logger.warning(
                        f"Connection attempt {retry_count} failed for {self._url}, retrying in {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("Reconnection loop finished.")
