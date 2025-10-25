"""Client wrapper for automatic reconnection logic."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Self

from pywebtransport.client.client import WebTransportClient
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ClientError, ConnectionError, TimeoutError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import URL, EventType
from pywebtransport.utils import get_logger

__all__: list[str] = ["ReconnectingClient"]

logger = get_logger(name=__name__)


class ReconnectingClient(EventEmitter):
    """A client that automatically reconnects based on the provided configuration."""

    def __init__(
        self,
        *,
        url: URL,
        client: WebTransportClient,
    ) -> None:
        """Initialize the reconnecting client."""
        super().__init__()
        self._url = url
        self._client = client
        self._config = client.config
        self._session: WebTransportSession | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closed = False
        self._is_initialized = False
        self._connected_event: asyncio.Event | None = None

    @property
    def is_connected(self) -> bool:
        """Check if the client is currently connected with a ready session."""
        return (
            self._session is not None
            and self._session.is_ready
            and self._connected_event is not None
            and self._connected_event.is_set()
        )

    async def __aenter__(self) -> Self:
        """Enter the async context, activating the client and starting the reconnect loop."""
        if self._closed:
            raise ClientError(message="Client is already closed")
        if self._is_initialized:
            return self

        self._connected_event = asyncio.Event()
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        self._is_initialized = True
        logger.info("ReconnectingClient started for URL: %s", self._url)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context, ensuring the client is closed."""
        await self.close()

    async def close(self) -> None:
        """Close the reconnecting client and all its resources."""
        if self._closed:
            return

        logger.info("Closing reconnecting client")
        self._closed = True
        if self._connected_event:
            self._connected_event.clear()

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._session and not self._session.is_closed:
            await self._session.close()

        logger.info("Reconnecting client closed")

    async def get_session(self, *, wait_timeout: float = 5.0) -> WebTransportSession | None:
        """Get the current session, waiting for a connection if necessary."""
        if self._closed or self._connected_event is None:
            return None
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=wait_timeout)
            return self._session
        except asyncio.TimeoutError:
            return None

    async def _reconnect_loop(self) -> None:
        """Manage the connection lifecycle with an exponential backoff retry strategy."""
        if self._connected_event is None:
            logger.error("Reconnection loop started before client was properly initialized.")
            return

        retry_count = 0
        max_retries = self._config.max_retries if self._config.max_retries >= 0 else float("inf")
        initial_delay = self._config.retry_delay
        backoff_factor = self._config.retry_backoff
        max_delay = self._config.max_retry_delay

        try:
            while not self._closed:
                try:
                    self._session = await self._client.connect(url=self._url)
                    logger.info("Successfully connected to %s", self._url)
                    self._connected_event.set()
                    await self.emit(
                        event_type=EventType.CONNECTION_ESTABLISHED,
                        data={"session": self._session, "attempt": retry_count + 1},
                    )
                    retry_count = 0
                    await self._session.wait_closed()

                    self._session = None
                    self._connected_event.clear()

                    if not self._closed:
                        logger.warning("Connection to %s lost, attempting to reconnect...", self._url)
                        await self.emit(event_type=EventType.CONNECTION_LOST, data={"url": self._url})

                except (ConnectionError, TimeoutError, ClientError) as e:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error("Max retries (%d) exceeded for %s", max_retries, self._url)
                        await self.emit(
                            event_type=EventType.CONNECTION_FAILED,
                            data={"reason": "max_retries_exceeded", "last_error": str(e)},
                        )
                        break

                    delay = min(initial_delay * (backoff_factor ** (retry_count - 1)), max_delay)
                    logger.warning(
                        "Connection attempt %d failed for %s, retrying in %.1fs: %s",
                        retry_count,
                        self._url,
                        delay,
                        e,
                        exc_info=True,
                    )
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass
        finally:
            if self._connected_event:
                self._connected_event.clear()
            logger.info("Reconnection loop finished.")
