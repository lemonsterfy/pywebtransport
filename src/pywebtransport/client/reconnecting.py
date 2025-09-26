"""WebTransport Reconnecting Client."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Self

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ClientError, ConnectionError, TimeoutError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import EventType, URL
from pywebtransport.utils import get_logger

__all__ = ["ReconnectingClient"]

logger = get_logger(name="client.reconnecting")


class ReconnectingClient(EventEmitter):
    """A client that automatically reconnects based on the provided configuration."""

    def __init__(
        self,
        *,
        url: URL,
        config: ClientConfig,
    ) -> None:
        """Initialize the reconnecting client."""
        super().__init__()
        self._url = url
        self._config = config
        self._client: WebTransportClient | None = None
        self._session: WebTransportSession | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closed = False
        self._is_initialized = False

    @classmethod
    def create(
        cls,
        *,
        url: URL,
        config: ClientConfig,
    ) -> Self:
        """Factory method to create a new reconnecting client instance."""
        return cls(url=url, config=config)

    @property
    def is_connected(self) -> bool:
        """Check if the client is currently connected with a ready session."""
        return self._session is not None and self._session.is_ready

    async def __aenter__(self) -> Self:
        """Enter the async context, activating the client and starting the reconnect loop."""
        if self._closed:
            raise ClientError(message="Client is already closed")
        if self._is_initialized:
            return self

        self._client = WebTransportClient(config=self._config)
        await self._client.__aenter__()
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

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.close()

        logger.info("Reconnecting client closed")

    async def get_session(self, *, wait_timeout: float = 5.0) -> WebTransportSession | None:
        """Get the current session if connected, waiting briefly for connection."""
        wait_interval = 0.1
        for _ in range(int(wait_timeout / wait_interval)):
            if self.is_connected and self._session:
                return self._session
            await asyncio.sleep(wait_interval)
        return None

    async def _reconnect_loop(self) -> None:
        """Manage the connection lifecycle with an exponential backoff retry strategy."""
        if not self._client:
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
                    await self.emit(
                        event_type=EventType.CONNECTION_ESTABLISHED,
                        data={"session": self._session, "attempt": retry_count + 1},
                    )
                    retry_count = 0
                    await self._session.wait_closed()
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
            logger.info("Reconnection loop finished.")
