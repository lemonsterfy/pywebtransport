"""Unit tests for the pywebtransport.manager.session module."""

from typing import cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport.constants import ErrorCodes
from pywebtransport.events import EventEmitter
from pywebtransport.manager.session import SessionManager
from pywebtransport.session.session import WebTransportSession
from pywebtransport.types import SessionState


@pytest.mark.asyncio
class TestSessionManager:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        session.session_id = "sess-1"
        session.state = SessionState.CONNECTED
        session.is_closed = False
        session.events = EventEmitter()
        session.close = mocker.AsyncMock()
        return cast(MagicMock, session)

    @pytest.fixture
    def manager(self) -> SessionManager:
        return SessionManager(max_sessions=10)

    async def test_add_session(self, manager: SessionManager, mock_session: MagicMock) -> None:
        async with manager:
            session_id = await manager.add_session(session=mock_session)

            assert session_id == "sess-1"
            assert len(manager) == 1
            assert await manager.get_resource(resource_id="sess-1") is mock_session

    async def test_close_resource_already_closed(self, manager: SessionManager, mock_session: MagicMock) -> None:
        mock_session.is_closed = True

        await manager._close_resource(mock_session)

        mock_session.close.assert_not_awaited()

    async def test_close_resource_open(self, manager: SessionManager, mock_session: MagicMock) -> None:
        mock_session.is_closed = False

        await manager._close_resource(mock_session)

        mock_session.close.assert_awaited_once_with(
            error_code=ErrorCodes.NO_ERROR, close_connection=False, reason="Session manager shutdown"
        )

    async def test_get_resource_id(self, manager: SessionManager, mock_session: MagicMock) -> None:
        assert manager._get_resource_id(mock_session) == "sess-1"

    async def test_get_sessions_by_state(self, manager: SessionManager, mocker: MockerFixture) -> None:
        s1 = mocker.Mock(spec=WebTransportSession, session_id="s1", events=EventEmitter())
        s1.state = SessionState.CONNECTED
        s2 = mocker.Mock(spec=WebTransportSession, session_id="s2", events=EventEmitter())
        s2.state = SessionState.CLOSING
        s3 = mocker.Mock(spec=WebTransportSession, session_id="s3", events=EventEmitter())
        s3.state = SessionState.CONNECTED

        async with manager:
            await manager.add_session(session=s1)
            await manager.add_session(session=s2)
            await manager.add_session(session=s3)

            connected = await manager.get_sessions_by_state(state=SessionState.CONNECTED)
            assert len(connected) == 2
            assert s1 in connected
            assert s3 in connected

            closing = await manager.get_sessions_by_state(state=SessionState.CLOSING)
            assert len(closing) == 1
            assert s2 in closing

    async def test_get_sessions_by_state_no_lock(self, manager: SessionManager) -> None:
        assert await manager.get_sessions_by_state(state=SessionState.CONNECTED) == []

    async def test_get_stats_includes_states(self, manager: SessionManager, mocker: MockerFixture) -> None:
        s1 = mocker.Mock(spec=WebTransportSession, session_id="s1", events=EventEmitter())
        s1.state = SessionState.CONNECTED
        s2 = mocker.Mock(spec=WebTransportSession, session_id="s2", events=EventEmitter())
        s2.state = SessionState.DRAINING

        async with manager:
            await manager.add_session(session=s1)
            await manager.add_session(session=s2)

            stats = await manager.get_stats()

            assert stats["current_count"] == 2
            assert stats["states"]["connected"] == 1
            assert stats["states"]["draining"] == 1

    async def test_get_stats_no_lock(self, manager: SessionManager) -> None:
        stats = await manager.get_stats()

        assert stats == {}

    async def test_init(self, manager: SessionManager) -> None:
        assert len(manager) == 0

    async def test_on_resource_removed_hook(self, manager: SessionManager) -> None:
        manager._on_resource_removed(resource_id="sess-1")

    async def test_remove_session(self, manager: SessionManager, mock_session: MagicMock) -> None:
        async with manager:
            await manager.add_session(session=mock_session)
            assert len(manager) == 1

            removed = await manager.remove_session(session_id="sess-1")

            assert removed is mock_session
            assert len(manager) == 0
            stats = await manager.get_stats()
            assert stats["total_closed"] == 1

    async def test_remove_session_missing(self, manager: SessionManager) -> None:
        async with manager:
            removed = await manager.remove_session(session_id="missing")

            assert removed is None

    async def test_remove_session_no_lock(self, manager: SessionManager) -> None:
        assert await manager.remove_session(session_id="s1") is None
