"""
WebTransport session manager implementation.
"""

from __future__ import annotations

import asyncio
import weakref
from collections import defaultdict
from types import TracebackType
from typing import Any, Self, Type

from pywebtransport.constants import WebTransportConstants
from pywebtransport.exceptions import SessionError
from pywebtransport.session.session import WebTransportSession
from pywebtransport.types import EventType, SessionId, SessionState
from pywebtransport.utils import get_logger

__all__ = ["SessionManager"]

logger = get_logger("session.manager")


class SessionManager:
    """Manages multiple WebTransport sessions with concurrency safety."""

    def __init__(
        self,
        *,
        max_sessions: int = WebTransportConstants.DEFAULT_MAX_SESSIONS,
        session_cleanup_interval: float = WebTransportConstants.DEFAULT_SESSION_CLEANUP_INTERVAL,
    ):
        """Initialize the session manager."""
        self._max_sessions = max_sessions
        self._cleanup_interval = session_cleanup_interval
        self._lock: asyncio.Lock | None = None
        self._sessions: dict[SessionId, WebTransportSession] = {}
        self._stats = {
            "total_created": 0,
            "total_closed": 0,
            "current_count": 0,
            "max_concurrent": 0,
        }
        self._cleanup_task: asyncio.Task[None] | None = None

    @classmethod
    def create(
        cls,
        *,
        max_sessions: int = WebTransportConstants.DEFAULT_MAX_SESSIONS,
        session_cleanup_interval: float = WebTransportConstants.DEFAULT_SESSION_CLEANUP_INTERVAL,
    ) -> Self:
        """Factory method to create a new session manager instance."""
        return cls(max_sessions=max_sessions, session_cleanup_interval=session_cleanup_interval)

    async def __aenter__(self) -> Self:
        """Enter async context, initializing resources and starting background tasks."""
        self._lock = asyncio.Lock()
        self._start_cleanup_task()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, shutting down the manager."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the session manager and close all active sessions."""
        logger.info("Shutting down session manager")
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        await self.close_all_sessions()
        logger.info("Session manager shutdown complete")

    async def add_session(self, session: WebTransportSession) -> SessionId:
        """Add a new session to the manager."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            if len(self._sessions) >= self._max_sessions:
                raise SessionError(f"Maximum sessions ({self._max_sessions}) exceeded")
            session_id = session.session_id
            self._sessions[session_id] = session

            manager_ref = weakref.ref(self)

            async def on_close(event: Any) -> None:
                manager = manager_ref()
                if manager:
                    await manager.remove_session(event.data["session_id"])

            session.once(EventType.SESSION_CLOSED, on_close)

            self._stats["total_created"] += 1
            self._update_stats_unsafe()
            logger.debug(f"Added session {session_id} (total: {len(self._sessions)})")
            return session_id

    async def remove_session(self, session_id: SessionId) -> WebTransportSession | None:
        """Remove a session from the manager by its ID."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                logger.debug(f"Removed session {session_id} (total: {len(self._sessions)})")
            return session

    async def get_session(self, session_id: SessionId) -> WebTransportSession | None:
        """Retrieve a session by its ID."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            return self._sessions.get(session_id)

    async def close_all_sessions(self) -> None:
        """Close and remove all currently managed sessions."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        async with self._lock:
            sessions_to_close = list(self._sessions.values())
            if not sessions_to_close:
                return
            logger.info(f"Closing and removing {len(sessions_to_close)} managed sessions.")

        close_tasks = [session.close() for session in sessions_to_close if not session.is_closed]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        session_ids = [session.session_id for session in sessions_to_close]
        remove_tasks = [self.remove_session(session_id) for session_id in session_ids]
        await asyncio.gather(*remove_tasks, return_exceptions=True)

    async def get_all_sessions(self) -> list[WebTransportSession]:
        """Retrieve a list of all current sessions."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            return list(self._sessions.values())

    async def get_sessions_by_state(self, state: SessionState) -> list[WebTransportSession]:
        """Retrieve sessions that are in a specific state."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            return [session for session in self._sessions.values() if session.state == state]

    async def cleanup_closed_sessions(self) -> int:
        """Find and remove any sessions that are marked as closed."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            all_sessions = list(self._sessions.items())
        closed_session_ids = []
        for session_id, session in all_sessions:
            if session.is_closed:
                closed_session_ids.append(session_id)

        if not closed_session_ids:
            return 0

        logger.debug(f"Found {len(closed_session_ids)} closed sessions to clean up.")
        for session_id in closed_session_ids:
            await self.remove_session(session_id)
        return len(closed_session_ids)

    def get_session_count(self) -> int:
        """Get the current number of active sessions (non-locking)."""
        return len(self._sessions)

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed statistics about the managed sessions."""
        if self._lock is None:
            raise SessionError(
                "SessionManager has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            states: dict[str, int] = defaultdict(int)
            for session in self._sessions.values():
                states[session.state.value] += 1
            return {
                **self._stats,
                "active_sessions": len(self._sessions),
                "states": dict(states),
                "max_sessions": self._max_sessions,
            }

    def _start_cleanup_task(self) -> None:
        """Start the background task for periodic cleanup if not running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def _periodic_cleanup(self) -> None:
        """Periodically run the cleanup process to remove closed sessions."""
        try:
            while True:
                try:
                    await self.cleanup_closed_sessions()
                except Exception as e:
                    logger.error(f"Session cleanup cycle failed: {e}", exc_info=e)

                await asyncio.sleep(self._cleanup_interval)
        except asyncio.CancelledError:
            pass

    def _update_stats_unsafe(self) -> None:
        """Update internal statistics (must be called within a lock)."""
        current_count = len(self._sessions)
        self._stats["current_count"] = current_count
        self._stats["max_concurrent"] = max(self._stats["max_concurrent"], current_count)
