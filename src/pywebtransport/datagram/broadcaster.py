"""Utility for broadcasting datagrams to multiple sessions."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import TYPE_CHECKING, Self

from pywebtransport.exceptions import SessionError
from pywebtransport.types import Data
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.session.session import WebTransportSession


__all__: list[str] = ["DatagramBroadcaster"]

logger = get_logger(name=__name__)


class DatagramBroadcaster:
    """Broadcast datagrams to multiple sessions concurrently."""

    def __init__(self) -> None:
        """Initialize the datagram broadcaster."""
        self._sessions: list[WebTransportSession] = []
        self._lock: asyncio.Lock | None = None

    async def __aenter__(self) -> Self:
        """Enter async context, initializing asyncio resources."""
        self._lock = asyncio.Lock()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit async context, clearing the session list."""
        if self._lock:
            async with self._lock:
                self._sessions.clear()

    async def shutdown(self) -> None:
        """Shut down the load balancer and clear sessions."""
        logger.info("Shutting down broadcaster")
        if self._lock:
            async with self._lock:
                self._sessions.clear()
        logger.info("Broadcaster shutdown complete")

    async def add_session(self, *, session: WebTransportSession) -> None:
        """Add a session to the broadcast list."""
        if self._lock is None:
            raise SessionError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if session not in self._sessions:
                self._sessions.append(session)

    async def broadcast(self, *, data: Data) -> int:
        """Broadcast a datagram to all registered sessions concurrently."""
        if self._lock is None:
            raise SessionError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        sent_count = 0
        failed_sessions = []

        async with self._lock:
            sessions_copy = self._sessions.copy()

        active_sessions = []
        tasks = []
        for session in sessions_copy:
            if not session.is_closed:
                tasks.append(session.send_datagram(data=data))
                active_sessions.append(session)
            else:
                failed_sessions.append(session)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for session, result in zip(active_sessions, results):
                if isinstance(result, Exception):
                    logger.warning("Failed to broadcast to session %s: %s", session.session_id, result, exc_info=True)
                    failed_sessions.append(session)
                else:
                    sent_count += 1

        if failed_sessions:
            async with self._lock:
                for session in failed_sessions:
                    if session in self._sessions:
                        self._sessions.remove(session)

        return sent_count

    async def remove_session(self, *, session: WebTransportSession) -> None:
        """Remove a session from the broadcast list."""
        if self._lock is None:
            raise SessionError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            try:
                self._sessions.remove(session)
            except ValueError:
                pass

    async def get_session_count(self) -> int:
        """Get the current number of active sessions safely."""
        if self._lock is None:
            raise SessionError(
                message=(
                    "DatagramBroadcaster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            return len(self._sessions)
