"""
WebTransport Browser Client.

This module provides the WebTransportBrowser class, a high-level client
that emulates browser-like navigation with session history.
"""

import asyncio
from types import TracebackType
from typing import List, Optional, Type

from ..config import ClientConfig
from ..session import WebTransportSession
from ..utils import get_logger
from .client import WebTransportClient

__all__ = ["WebTransportBrowser"]

logger = get_logger("client.browser")


class WebTransportBrowser:
    """A browser-like WebTransport client with a managed lifecycle and history."""

    def __init__(self, *, config: Optional[ClientConfig] = None):
        """Initialize the browser-like WebTransport client."""
        self._client = WebTransportClient.create(config=config)
        self._history: List[str] = []
        self._history_index: int = -1
        self._current_session: Optional[WebTransportSession] = None
        self._lock = asyncio.Lock()

    @classmethod
    def create(cls, *, config: Optional[ClientConfig] = None) -> "WebTransportBrowser":
        """Factory method to create a new browser-like client instance."""
        return cls(config=config)

    @property
    def current_session(self) -> Optional[WebTransportSession]:
        """Get the current active session."""
        return self._current_session

    async def __aenter__(self) -> "WebTransportBrowser":
        """Enter the async context, activating the underlying client."""
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the async context, ensuring all resources are closed."""
        await self.close()

    async def close(self) -> None:
        """Close the browser, the current session, and all underlying resources."""
        async with self._lock:
            logger.info("Closing WebTransportBrowser and active session.")
            if self._current_session and not self._current_session.is_closed:
                await self._current_session.close()

            await self._client.close()
            self._current_session = None
            self._history.clear()
            self._history_index = -1

    async def navigate(self, url: str) -> WebTransportSession:
        """Navigate to a URL, creating a new session and clearing forward history."""
        async with self._lock:
            if self._history_index < len(self._history) - 1:
                self._history = self._history[: self._history_index + 1]

            if not self._history or self._history[-1] != url:
                self._history.append(url)

            self._history_index = len(self._history) - 1
            return await self._navigate_internal(url)

    async def back(self) -> Optional[WebTransportSession]:
        """Go back to the previous entry in the navigation history."""
        async with self._lock:
            if self._history_index > 0:
                self._history_index -= 1
                url_to_navigate = self._history[self._history_index]
                return await self._navigate_internal(url_to_navigate)
            return None

    async def forward(self) -> Optional[WebTransportSession]:
        """Go forward to the next entry in the navigation history."""
        async with self._lock:
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                url_to_navigate = self._history[self._history_index]
                return await self._navigate_internal(url_to_navigate)
            return None

    async def refresh(self) -> Optional[WebTransportSession]:
        """Refresh the current session by reconnecting to the current URL."""
        async with self._lock:
            if not self._history:
                return None
            current_url = self._history[self._history_index]
            return await self._navigate_internal(current_url)

    async def get_history(self) -> List[str]:
        """Get a copy of the navigation history."""
        async with self._lock:
            return self._history.copy()

    async def _navigate_internal(self, url: str) -> WebTransportSession:
        """Handle the core navigation logic for session teardown and creation."""
        old_session = self._current_session
        self._current_session = None

        if old_session and not old_session.is_closed:
            asyncio.create_task(old_session.close())

        try:
            new_session = await self._client.connect(url)
            self._current_session = new_session
            return new_session
        except Exception as e:
            self._current_session = old_session
            logger.error(f"Failed to navigate to {url}: {e}", exc_info=True)
            raise
