"""Unit tests for the pywebtransport.session.manager module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest import mock
from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import EventType, SessionError, SessionState, WebTransportSession
from pywebtransport.session import SessionManager

FAST_CLEANUP_INTERVAL = 1000.0


class TestSessionManager:
    @pytest.fixture
    async def manager(self) -> AsyncGenerator[SessionManager, None]:
        async with SessionManager(session_cleanup_interval=FAST_CLEANUP_INTERVAL) as mgr:
            yield mgr

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> WebTransportSession:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.session_id = "session-1"
        session.state = SessionState.CONNECTED
        type(session).is_closed = mocker.PropertyMock(return_value=False)
        session.close = mocker.AsyncMock()
        session.once = mocker.MagicMock()
        return session

    def test_initialization(self) -> None:
        mgr = SessionManager()

        assert mgr.get_session_count() == 0
        assert mgr._max_sessions > 0
        stats = mgr._stats
        assert stats["total_created"] == 0
        assert stats["total_closed"] == 0
        assert stats["current_count"] == 0
        assert stats["max_concurrent"] == 0

    def test_create_factory(self) -> None:
        mgr = SessionManager.create(max_sessions=50, session_cleanup_interval=10.0)

        assert isinstance(mgr, SessionManager)
        assert mgr._max_sessions == 50
        assert mgr._cleanup_interval == 10.0

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mocker: MockerFixture) -> None:
        mock_start = mocker.patch.object(SessionManager, "_start_cleanup_task")
        mock_shutdown = mocker.patch.object(SessionManager, "shutdown", new_callable=mocker.AsyncMock)

        async with SessionManager() as mgr:
            mock_start.assert_called_once()
            assert mgr._lock is not None

        mock_shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown(self, manager: SessionManager, mock_session: WebTransportSession) -> None:
        assert manager._cleanup_task is not None
        assert not manager._cleanup_task.done()
        the_task = manager._cleanup_task
        await manager.add_session(session=mock_session)

        await manager.shutdown()

        assert the_task.done()
        cast(mock.AsyncMock, mock_session.close).assert_awaited_once()
        assert manager.get_session_count() == 0

    @pytest.mark.asyncio
    async def test_shutdown_no_cleanup_task(self, manager: SessionManager) -> None:
        assert manager._cleanup_task is not None
        manager._cleanup_task.cancel()
        await asyncio.sleep(0)
        manager._cleanup_task = None

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_add_session_success(self, manager: SessionManager, mock_session: WebTransportSession) -> None:
        session_id = await manager.add_session(session=mock_session)

        assert session_id == "session-1"
        assert manager.get_session_count() == 1
        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1
        assert await manager.get_session(session_id="session-1") is mock_session
        cast(mock.MagicMock, mock_session.once).assert_called_once_with(
            event_type=EventType.SESSION_CLOSED, handler=mock.ANY
        )

    @pytest.mark.asyncio
    async def test_add_session_limit_exceeded(self, mock_session: WebTransportSession, mocker: MockerFixture) -> None:
        async with SessionManager(max_sessions=1) as manager:
            await manager.add_session(session=mock_session)
            another_session = mocker.create_autospec(WebTransportSession, instance=True, session_id="session-2")
            another_session.once = mocker.MagicMock()

            with pytest.raises(SessionError, match=r"Maximum sessions \(1\) exceeded"):
                await manager.add_session(session=another_session)

    @pytest.mark.asyncio
    async def test_get_session(self, manager: SessionManager, mock_session: WebTransportSession) -> None:
        await manager.add_session(session=mock_session)

        retrieved = await manager.get_session(session_id="session-1")
        not_found = await manager.get_session(session_id="non-existent-id")

        assert retrieved is mock_session
        assert not_found is None

    @pytest.mark.asyncio
    async def test_remove_session(self, manager: SessionManager, mock_session: WebTransportSession) -> None:
        await manager.add_session(session=mock_session)
        assert manager.get_session_count() == 1

        removed_session = await manager.remove_session(session_id="session-1")

        assert removed_session is mock_session
        assert manager.get_session_count() == 0
        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["total_closed"] == 1
        assert stats["current_count"] == 0

    @pytest.mark.asyncio
    async def test_remove_non_existent_session(self, manager: SessionManager) -> None:
        removed = await manager.remove_session(session_id="non-existent-id")

        assert removed is None
        stats = await manager.get_stats()
        assert stats["total_closed"] == 0

    @pytest.mark.asyncio
    async def test_automatic_removal_on_session_close(
        self, manager: SessionManager, mock_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        close_handler = None

        def capture_handler(event_type: EventType, handler: Any) -> None:
            nonlocal close_handler
            if event_type == EventType.SESSION_CLOSED:
                close_handler = handler

        cast(mock.MagicMock, mock_session.once).side_effect = capture_handler
        await manager.add_session(session=mock_session)
        assert manager.get_session_count() == 1
        assert close_handler is not None
        close_event = mocker.MagicMock()
        close_event.data = {"session_id": mock_session.session_id}

        await close_handler(close_event)

        assert manager.get_session_count() == 0
        stats = await manager.get_stats()
        assert stats["total_closed"] == 1

    @pytest.mark.asyncio
    async def test_on_close_handler_with_dead_weakref(
        self, manager: SessionManager, mock_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        close_handler = None

        def capture_handler(event_type: EventType, handler: Any) -> None:
            nonlocal close_handler
            if event_type == EventType.SESSION_CLOSED:
                close_handler = handler

        cast(mock.MagicMock, mock_session.once).side_effect = capture_handler
        await manager.add_session(session=mock_session)
        assert close_handler is not None
        mocker.patch("weakref.ref", return_value=lambda: None)
        close_event = mocker.MagicMock()
        close_event.data = {"session_id": mock_session.session_id}

        await close_handler(close_event)

    @pytest.mark.asyncio
    async def test_get_all_and_by_state(self, manager: SessionManager, mocker: MockerFixture) -> None:
        sessions: list[WebTransportSession] = []
        for i, state in enumerate([SessionState.CONNECTED, SessionState.CLOSED, SessionState.CONNECTED]):
            session = mocker.create_autospec(WebTransportSession, instance=True)
            session.session_id = f"session-{i}"
            session.state = state
            session.once = mocker.MagicMock()
            sessions.append(session)
            await manager.add_session(session=session)

        all_sessions = await manager.get_all_sessions()
        connected_sessions = await manager.get_sessions_by_state(state=SessionState.CONNECTED)
        closed_sessions = await manager.get_sessions_by_state(state=SessionState.CLOSED)

        assert len(all_sessions) == 3
        assert set(all_sessions) == set(sessions)
        assert len(connected_sessions) == 2
        assert connected_sessions[0].state == SessionState.CONNECTED
        assert connected_sessions[1].state == SessionState.CONNECTED
        assert len(closed_sessions) == 1
        assert closed_sessions[0].state == SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_get_stats(self, manager: SessionManager, mock_session: WebTransportSession) -> None:
        await manager.add_session(session=mock_session)

        stats = await manager.get_stats()

        assert stats["active_sessions"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1
        assert stats["total_created"] == 1
        assert stats["total_closed"] == 0
        assert stats["states"] == {"connected": 1}
        assert stats["max_sessions"] > 0

    @pytest.mark.asyncio
    async def test_close_all_sessions_empty(self, manager: SessionManager) -> None:
        await manager.close_all_sessions()

        stats = await manager.get_stats()
        assert stats["total_closed"] == 0

    @pytest.mark.asyncio
    async def test_close_all_sessions_raises_exception_group(
        self, manager: SessionManager, mock_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        cast(AsyncMock, mock_session.close).side_effect = ValueError("Close failed")
        await manager.add_session(session=mock_session)

        with pytest.raises(ExceptionGroup) as excinfo:
            await manager.close_all_sessions()

        assert len(excinfo.value.exceptions) == 1
        assert isinstance(excinfo.value.exceptions[0], ValueError)

    @pytest.mark.asyncio
    async def test_cleanup_closed_sessions(self, manager: SessionManager, mocker: MockerFixture) -> None:
        open_session = mocker.create_autospec(WebTransportSession, instance=True, session_id="open-1")
        type(open_session).is_closed = mocker.PropertyMock(return_value=False)
        open_session.once = mocker.MagicMock()
        closed_session = mocker.create_autospec(WebTransportSession, instance=True, session_id="closed-1")
        type(closed_session).is_closed = mocker.PropertyMock(return_value=True)
        closed_session.once = mocker.MagicMock()
        await manager.add_session(session=open_session)
        await manager.add_session(session=closed_session)
        assert manager.get_session_count() == 2

        cleaned_count = await manager.cleanup_closed_sessions()

        assert cleaned_count == 1
        assert manager.get_session_count() == 1
        assert await manager.get_session(session_id="open-1") is not None
        assert await manager.get_session(session_id="closed-1") is None
        stats = await manager.get_stats()
        assert stats["total_closed"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_closed_sessions_no_sessions_to_clean(self, manager: SessionManager) -> None:
        cleaned_count = await manager.cleanup_closed_sessions()

        assert cleaned_count == 0

    @pytest.mark.asyncio
    async def test_periodic_cleanup_task(self, mocker: MockerFixture) -> None:
        mock_cleanup = mocker.patch.object(SessionManager, "cleanup_closed_sessions", new_callable=mocker.AsyncMock)

        async with SessionManager(session_cleanup_interval=1000):
            await asyncio.sleep(0)

        mock_cleanup.assert_awaited()

    @pytest.mark.asyncio
    async def test_start_cleanup_task_is_idempotent(self, manager: SessionManager) -> None:
        first_task = manager._cleanup_task
        assert first_task is not None

        manager._start_cleanup_task()
        second_task = manager._cleanup_task

        assert first_task is second_task

    @pytest.mark.asyncio
    async def test_periodic_cleanup_handles_exception(self, mocker: MockerFixture) -> None:
        mock_logger = mocker.patch("pywebtransport.session.manager.logger")
        error = ValueError("Cleanup failed")
        mock_cleanup = mocker.patch.object(SessionManager, "cleanup_closed_sessions", new_callable=mocker.AsyncMock)
        mock_cleanup.side_effect = error

        async with SessionManager(session_cleanup_interval=0.001):
            await asyncio.sleep(0.01)

        mock_logger.error.assert_called_with("Session cleanup cycle failed: %s", error, exc_info=error)
        mock_cleanup.assert_awaited()


class TestSessionManagerUninitialized:
    @pytest.fixture
    def uninitialized_manager(self) -> SessionManager:
        return SessionManager()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("add_session", {"session": mock.Mock()}),
            ("close_all_sessions", {}),
            ("get_session", {"session_id": "id-1"}),
            ("remove_session", {"session_id": "id-1"}),
            ("cleanup_closed_sessions", {}),
            ("get_all_sessions", {}),
            ("get_sessions_by_state", {"state": SessionState.CONNECTED}),
            ("get_stats", {}),
        ],
    )
    async def test_methods_raise_before_activated(
        self, uninitialized_manager: SessionManager, method_name: str, kwargs: dict
    ) -> None:
        with pytest.raises(SessionError, match="SessionManager has not been activated"):
            await getattr(uninitialized_manager, method_name)(**kwargs)
