"""Unit tests for the pywebtransport.manager.session module."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import SessionError, WebTransportSession
from pywebtransport.manager import SessionManager
from pywebtransport.types import EventType, SessionId, SessionState


@pytest.fixture
def manager() -> SessionManager:
    """Fixture for creating a SessionManager instance."""
    return SessionManager(max_sessions=10, session_cleanup_interval=0.01)


@pytest.fixture
def mock_session(mocker: MockerFixture) -> MagicMock:
    """Fixture for creating a mock WebTransportSession."""
    session = mocker.create_autospec(WebTransportSession, instance=True)
    session.session_id = f"session_{mocker.sentinel.id}"
    session.is_closed = False
    session.state = SessionState.CONNECTED
    session.close = AsyncMock()

    events: dict[EventType, Callable[..., Awaitable[None]]] = {}

    def once(event_type: EventType, handler: Callable[..., Awaitable[None]]) -> None:
        events[event_type] = handler

    async def trigger(event_type: EventType, data: Any) -> None:
        if event_type in events:
            event = MagicMock()
            event.data = data
            await events[event_type](event)

    session.once = MagicMock(side_effect=once)
    session.trigger = AsyncMock(side_effect=trigger)

    return session


@pytest_asyncio.fixture
async def running_manager(
    manager: SessionManager,
) -> AsyncGenerator[SessionManager, None]:
    """Fixture to provide a running SessionManager within a context."""
    async with manager as mgr:
        yield mgr


class TestSessionManager:
    """Test suite for the SessionManager class."""

    def create_mock_session(self, mocker: MockerFixture, session_id: SessionId, state: SessionState) -> MagicMock:
        """Helper to create a mock session with specific properties."""
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.session_id = session_id
        session.state = state
        session.is_closed = state == SessionState.CLOSED
        session.close = AsyncMock()
        session.once = MagicMock()
        return session

    @pytest.mark.asyncio
    async def test_add_session(
        self,
        running_manager: SessionManager,
        mock_session: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test adding a valid session to the manager."""
        session_id = await running_manager.add_session(session=mock_session)
        assert session_id == mock_session.session_id
        assert len(running_manager) == 1
        mock_session.once.assert_called_once_with(event_type=EventType.SESSION_CLOSED, handler=mocker.ANY)

    @pytest.mark.asyncio
    async def test_add_session_limit_exceeded(self, running_manager: SessionManager, mock_session: MagicMock) -> None:
        """Test that adding a session fails when the maximum limit is reached."""
        running_manager._max_resources = 0
        with pytest.raises(SessionError, match="Maximum sessions"):
            await running_manager.add_session(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_sessions_by_state(self, running_manager: SessionManager, mocker: MockerFixture) -> None:
        """Test retrieving sessions based on their state."""
        session1 = self.create_mock_session(mocker, "s1", SessionState.CONNECTED)
        session2 = self.create_mock_session(mocker, "s2", SessionState.CLOSED)
        session3 = self.create_mock_session(mocker, "s3", SessionState.CONNECTED)

        await running_manager.add_session(session=session1)
        await running_manager.add_session(session=session2)
        await running_manager.add_session(session=session3)

        connected_sessions = await running_manager.get_sessions_by_state(state=SessionState.CONNECTED)
        assert len(connected_sessions) == 2
        assert session1 in connected_sessions
        assert session3 in connected_sessions

        closed_sessions = await running_manager.get_sessions_by_state(state=SessionState.CLOSED)
        assert len(closed_sessions) == 1
        assert session2 in closed_sessions

    @pytest.mark.asyncio
    async def test_get_stats_with_states(self, running_manager: SessionManager, mocker: MockerFixture) -> None:
        """Test that get_stats correctly reports session states."""
        await running_manager.add_session(session=self.create_mock_session(mocker, "s1", SessionState.CONNECTED))
        await running_manager.add_session(session=self.create_mock_session(mocker, "s2", SessionState.CONNECTED))
        await running_manager.add_session(session=self.create_mock_session(mocker, "s3", SessionState.CLOSED))

        stats = await running_manager.get_stats()
        assert stats["states"] == {SessionState.CONNECTED: 2, SessionState.CLOSED: 1}

    def test_initialization(self, manager: SessionManager) -> None:
        """Test that the manager initializes with the correct properties."""
        assert manager._max_resources == 10
        assert manager._cleanup_interval == 0.01

    @pytest.mark.asyncio
    async def test_manager_inactive_methods(self, manager: SessionManager, mock_session: MagicMock) -> None:
        """Test that key methods raise errors or return safely when the manager is not active."""
        with pytest.raises(SessionError, match="has not been activated"):
            await manager.add_session(session=mock_session)

        assert await manager.remove_session(session_id="dummy_id") is None
        assert await manager.get_sessions_by_state(state=SessionState.CONNECTED) == []
        assert await manager.get_stats() == {}

    @pytest.mark.asyncio
    async def test_on_session_closed_handler(self, running_manager: SessionManager, mock_session: MagicMock) -> None:
        """Test that the manager auto-removes a session when its 'closed' event is triggered."""
        await running_manager.add_session(session=mock_session)
        assert len(running_manager) == 1

        await mock_session.trigger(EventType.SESSION_CLOSED, {"session_id": mock_session.session_id})
        await asyncio.sleep(0)  # Allow the handler to execute
        assert len(running_manager) == 0

    @pytest.mark.asyncio
    async def test_on_session_closed_handler_bad_event_data(
        self, running_manager: SessionManager, mock_session: MagicMock
    ) -> None:
        """Test that the closed handler ignores events with malformed data."""
        await running_manager.add_session(session=mock_session)
        assert len(running_manager) == 1

        await mock_session.trigger(EventType.SESSION_CLOSED, "not a dict")
        await asyncio.sleep(0)
        assert len(running_manager) == 1

    @pytest.mark.asyncio
    async def test_remove_session(self, running_manager: SessionManager, mock_session: MagicMock) -> None:
        """Test removing a session successfully."""
        session_id = await running_manager.add_session(session=mock_session)
        assert len(running_manager) == 1

        removed_session = await running_manager.remove_session(session_id=session_id)
        assert removed_session is mock_session
        assert len(running_manager) == 0
        stats = await running_manager.get_stats()
        assert stats["total_closed"] == 1

    @pytest.mark.asyncio
    async def test_remove_session_not_found(self, running_manager: SessionManager) -> None:
        """Test that removing a non-existent session returns None."""
        removed_session = await running_manager.remove_session(session_id="unknown")
        assert removed_session is None

    @pytest.mark.asyncio
    async def test_shutdown_closes_open_sessions(self, mock_session: MagicMock, mocker: MockerFixture) -> None:
        """Test that shutdown closes open sessions and ignores already closed ones."""
        manager = SessionManager()
        closed_session = self.create_mock_session(mocker, "closed_session", SessionState.CLOSED)
        closed_session.is_closed = True

        async with manager:
            await manager.add_session(session=mock_session)
            await manager.add_session(session=closed_session)

        mock_session.close.assert_awaited_once_with(close_connection=False)
        closed_session.close.assert_not_awaited()
