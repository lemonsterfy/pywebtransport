"""WebTransport Browser Client."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Self

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.exceptions import ClientError
from pywebtransport.session import WebTransportSession
from pywebtransport.utils import get_logger

__all__ = ["WebTransportBrowser"]

logger = get_logger(name="client.browser")


class WebTransportBrowser:
    """A browser-like WebTransport client with a managed lifecycle and history."""

    def __init__(self, *, config: ClientConfig | None = None) -> None:
        """Initialize the browser-like WebTransport client."""
        self._client = WebTransportClient(config=config)
        self._history: list[str] = []
        self._history_index: int = -1
        self._current_session: WebTransportSession | None = None
        self._lock: asyncio.Lock | None = None

    @classmethod
    def create(cls, *, config: ClientConfig | None = None) -> Self:
        """Factory method to create a new browser-like client instance."""
        return cls(config=config)

    @property
    def current_session(self) -> WebTransportSession | None:
        """Get the current active session."""
        return self._current_session

    async def __aenter__(self) -> Self:
        """Enter the async context, initializing resources."""
        self._lock = asyncio.Lock()
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context, ensuring all resources are closed."""
        await self.close()

    async def close(self) -> None:
        """Close the browser, the current session, and all underlying resources."""
        if self._lock is None:
            raise ClientError(
                message=(
                    "WebTransportBrowser has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            logger.info("Closing WebTransportBrowser and active session.")
            if self._current_session and not self._current_session.is_closed:
                await self._current_session.close()

            await self._client.close()
            self._current_session = None
            self._history.clear()
            self._history_index = -1

    async def back(self) -> WebTransportSession | None:
        """Go back to the previous entry in the navigation history."""
        if self._lock is None:
            raise ClientError(
                message=(
                    "WebTransportBrowser has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if self._history_index > 0:
                self._history_index -= 1
                url_to_navigate = self._history[self._history_index]
                return await self._navigate_internal(url=url_to_navigate)
            return None

    async def forward(self) -> WebTransportSession | None:
        """Go forward to the next entry in the navigation history."""
        if self._lock is None:
            raise ClientError(
                message=(
                    "WebTransportBrowser has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                url_to_navigate = self._history[self._history_index]
                return await self._navigate_internal(url=url_to_navigate)
            return None

    async def navigate(self, *, url: str) -> WebTransportSession:
        """Navigate to a URL, creating a new session and clearing forward history."""
        if self._lock is None:
            raise ClientError(
                message=(
                    "WebTransportBrowser has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if self._current_session and self._history and self._history[self._history_index] == url:
                return self._current_session

            if self._history_index < len(self._history) - 1:
                self._history = self._history[: self._history_index + 1]

            if not self._history or self._history[-1] != url:
                self._history.append(url)

            self._history_index = len(self._history) - 1
            return await self._navigate_internal(url=url)

    async def refresh(self) -> WebTransportSession | None:
        """Refresh the current session by reconnecting to the current URL."""
        if self._lock is None:
            raise ClientError(
                message=(
                    "WebTransportBrowser has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if not self._history:
                return None
            current_url = self._history[self._history_index]
            return await self._navigate_internal(url=current_url)

    async def get_history(self) -> list[str]:
        """Get a copy of the navigation history."""
        if self._lock is None:
            raise ClientError(
                message=(
                    "WebTransportBrowser has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            return self._history.copy()

    async def _navigate_internal(self, *, url: str) -> WebTransportSession:
        """Handle the core navigation logic for session teardown and creation."""
        old_session = self._current_session
        self._current_session = None

        if old_session and not old_session.is_closed:
            asyncio.create_task(old_session.close())

        try:
            new_session = await self._client.connect(url=url)
            self._current_session = new_session
            return new_session
        except Exception as e:
            self._current_session = old_session
            logger.error("Failed to navigate to %s: %s", url, e, exc_info=True)
            raise
