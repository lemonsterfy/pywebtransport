"""Unit tests for the pywebtransport.session.manager module."""

import asyncio
from typing import List

import pytest
from pytest_mock import MockerFixture

from pywebtransport import SessionError, SessionState, WebTransportSession
from pywebtransport.session import SessionManager

FAST_CLEANUP_INTERVAL = 1000.0


@pytest.fixture
def mock_session(mocker: MockerFixture) -> WebTransportSession:
    session = mocker.create_autospec(WebTransportSession, instance=True)
    session.session_id = "session-1"
    session.state = SessionState.CONNECTED
    session.is_closed = False
    session.close = mocker.AsyncMock()
    return session


@pytest.fixture
def manager() -> SessionManager:
    return SessionManager(cleanup_interval=FAST_CLEANUP_INTERVAL)


class TestSessionManager:
    def test_initialization(self, manager: SessionManager):
        assert manager.get_session_count() == 0
        assert manager._max_sessions == 1000
        stats = manager._stats
        assert stats["total_created"] == 0
        assert stats["total_closed"] == 0
        assert stats["current_count"] == 0
        assert stats["max_concurrent"] == 0

    def test_create_factory(self):
        mgr = SessionManager.create(max_sessions=50, cleanup_interval=10.0)
        assert isinstance(mgr, SessionManager)
        assert mgr._max_sessions == 50
        assert mgr._cleanup_interval == 10.0

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mocker: MockerFixture):
        mock_start = mocker.patch.object(SessionManager, "_start_cleanup_task")
        mock_shutdown = mocker.patch.object(SessionManager, "shutdown", new_callable=mocker.AsyncMock)

        async with SessionManager():
            mock_start.assert_called_once()

        mock_shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_session_success(self, manager: SessionManager, mock_session: WebTransportSession):
        session_id = await manager.add_session(mock_session)
        assert session_id == "session-1"
        assert manager.get_session_count() == 1

        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1
        assert await manager.get_session("session-1") is mock_session

    @pytest.mark.asyncio
    async def test_get_session(self, manager: SessionManager, mock_session: WebTransportSession):
        await manager.add_session(mock_session)
        retrieved = await manager.get_session("session-1")
        assert retrieved is mock_session

        not_found = await manager.get_session("non-existent-id")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_remove_session(self, manager: SessionManager, mock_session: WebTransportSession):
        await manager.add_session(mock_session)
        assert manager.get_session_count() == 1

        removed_session = await manager.remove_session("session-1")
        assert removed_session is mock_session
        assert manager.get_session_count() == 0

        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["total_closed"] == 1
        assert stats["current_count"] == 0

    @pytest.mark.asyncio
    async def test_get_all_and_by_state(self, manager: SessionManager, mocker: MockerFixture):
        sessions: List[WebTransportSession] = []
        for i, state in enumerate([SessionState.CONNECTED, SessionState.CLOSED, SessionState.CONNECTED]):
            session = mocker.create_autospec(WebTransportSession, instance=True)
            session.session_id = f"session-{i}"
            session.state = state
            sessions.append(session)
            await manager.add_session(session)

        all_sessions = await manager.get_all_sessions()
        assert len(all_sessions) == 3
        assert set(all_sessions) == set(sessions)

        connected_sessions = await manager.get_sessions_by_state(SessionState.CONNECTED)
        assert len(connected_sessions) == 2
        assert connected_sessions[0].state == SessionState.CONNECTED
        assert connected_sessions[1].state == SessionState.CONNECTED

        closed_sessions = await manager.get_sessions_by_state(SessionState.CLOSED)
        assert len(closed_sessions) == 1
        assert closed_sessions[0].state == SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_get_stats(self, manager: SessionManager, mock_session: WebTransportSession):
        await manager.add_session(mock_session)
        stats = await manager.get_stats()

        assert stats["active_sessions"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1
        assert stats["total_created"] == 1
        assert stats["total_closed"] == 0
        assert stats["states"] == {"connected": 1}
        assert stats["max_sessions"] == 1000

    @pytest.mark.asyncio
    async def test_add_session_limit_exceeded(self, mock_session: WebTransportSession, mocker: MockerFixture):
        manager = SessionManager(max_sessions=1)
        await manager.add_session(mock_session)

        another_session = mocker.create_autospec(WebTransportSession, instance=True, session_id="session-2")
        with pytest.raises(SessionError, match=r"Maximum sessions \(1\) exceeded"):
            await manager.add_session(another_session)

    @pytest.mark.asyncio
    async def test_remove_non_existent_session(self, manager: SessionManager):
        removed = await manager.remove_session("non-existent-id")
        assert removed is None
        stats = await manager.get_stats()
        assert stats["total_closed"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_closed_sessions(self, manager: SessionManager, mocker: MockerFixture):
        open_session = mocker.create_autospec(WebTransportSession, instance=True, session_id="open-1")
        open_session.is_closed = False
        closed_session = mocker.create_autospec(WebTransportSession, instance=True, session_id="closed-1")
        closed_session.is_closed = True

        await manager.add_session(open_session)
        await manager.add_session(closed_session)
        assert manager.get_session_count() == 2

        cleaned_count = await manager.cleanup_closed_sessions()
        assert cleaned_count == 1
        assert manager.get_session_count() == 1
        assert await manager.get_session("open-1") is not None
        assert await manager.get_session("closed-1") is None
        stats = await manager.get_stats()
        assert stats["total_closed"] == 1

    @pytest.mark.asyncio
    async def test_periodic_cleanup_task(self, mocker: MockerFixture):
        manager = SessionManager(cleanup_interval=0.001)
        mock_cleanup = mocker.patch.object(manager, "cleanup_closed_sessions", new_callable=mocker.AsyncMock)

        async with manager:
            await asyncio.sleep(0.01)

        mock_cleanup.assert_awaited()

    @pytest.mark.asyncio
    async def test_periodic_cleanup_handles_exception(self, mocker: MockerFixture):
        manager = SessionManager(cleanup_interval=0.001)
        mock_logger = mocker.patch("pywebtransport.session.manager.logger")
        mock_cleanup = mocker.patch.object(manager, "cleanup_closed_sessions", new_callable=mocker.AsyncMock)
        mock_cleanup.side_effect = ValueError("Cleanup failed")

        async with manager:
            await asyncio.sleep(0.01)

        mock_logger.error.assert_called_once_with("Session cleanup error: Cleanup failed")
        mock_cleanup.assert_awaited()

    @pytest.mark.asyncio
    async def test_shutdown(self, manager: SessionManager, mock_session: WebTransportSession, mocker: MockerFixture):
        manager._start_cleanup_task()
        assert manager._cleanup_task is not None
        assert isinstance(manager._cleanup_task, asyncio.Task)
        assert not manager._cleanup_task.done()
        the_task = manager._cleanup_task
        await manager.add_session(mock_session)
        await manager.shutdown()
        assert the_task.done()
        assert the_task.cancelled()
        mock_session.close.assert_awaited_once()
        assert manager.get_session_count() == 0
