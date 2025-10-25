"""Manager for handling numerous concurrent session lifecycles."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pywebtransport.constants import DEFAULT_MAX_SESSIONS, DEFAULT_SESSION_CLEANUP_INTERVAL
from pywebtransport.exceptions import SessionError
from pywebtransport.manager._base import _BaseResourceManager
from pywebtransport.session.session import WebTransportSession
from pywebtransport.types import EventType, SessionId, SessionState
from pywebtransport.utils import get_logger

__all__: list[str] = ["SessionManager"]

logger = get_logger(name=__name__)


class SessionManager(_BaseResourceManager[SessionId, WebTransportSession]):
    """Manage multiple WebTransport sessions with concurrency safety."""

    _log = logger

    def __init__(
        self,
        *,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        session_cleanup_interval: float = DEFAULT_SESSION_CLEANUP_INTERVAL,
    ) -> None:
        """Initialize the session manager."""
        super().__init__(
            resource_name="session",
            max_resources=max_sessions,
            cleanup_interval=session_cleanup_interval,
        )

    async def add_session(self, *, session: WebTransportSession) -> SessionId:
        """Add a new session to the manager."""
        if self._lock is None:
            raise SessionError(
                message=(
                    "SessionManager has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if len(self._resources) >= self._max_resources:
                raise SessionError(message=f"Maximum sessions ({self._max_resources}) exceeded")

            session_id = self._get_resource_id(session)
            self._resources[session_id] = session

            async def on_close(event: Any) -> None:
                if isinstance(event.data, dict):
                    await self.remove_session(session_id=event.data["session_id"])

            session.once(event_type=EventType.SESSION_CLOSED, handler=on_close)

            self._stats["total_created"] += 1
            self._update_stats_unsafe()
            self._log.debug("Added session %s (total: %d)", session_id, len(self._resources))
            return session_id

    async def get_sessions_by_state(self, *, state: SessionState) -> list[WebTransportSession]:
        """Retrieve sessions that are in a specific state."""
        if self._lock is None:
            return []

        async with self._lock:
            return [session for session in self._resources.values() if session.state == state]

    async def get_stats(self) -> dict[str, Any]:
        """Get detailed statistics about the managed sessions."""
        if self._lock is None:
            return {}

        stats = await super().get_stats()
        async with self._lock:
            states: dict[str, int] = defaultdict(int)
            for session in self._resources.values():
                states[session.state] += 1
            stats["states"] = dict(states)
        return stats

    async def remove_session(self, *, session_id: SessionId) -> WebTransportSession | None:
        """Remove a session from the manager by its ID."""
        if self._lock is None:
            return None

        async with self._lock:
            session = self._resources.pop(session_id, None)
            if session:
                self._stats["total_closed"] += 1
                self._update_stats_unsafe()
                self._log.debug("Removed session %s (total: %d)", session_id, len(self._resources))
            return session

    async def _close_resource(self, resource: WebTransportSession) -> None:
        """Close a single session resource."""
        if not resource.is_closed:
            await resource.close(close_connection=False)

    def _get_resource_id(self, resource: WebTransportSession) -> SessionId:
        """Get the unique ID from a session object."""
        return resource.session_id

    def _is_resource_closed(self, resource: WebTransportSession) -> bool:
        """Check if a session resource is closed."""
        return resource.is_closed
