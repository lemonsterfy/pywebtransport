"""Unit tests for the pywebtransport.manager.connection module."""

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport.events import EventEmitter
from pywebtransport.manager.connection import ConnectionManager
from pywebtransport.types import ConnectionState


@pytest.mark.asyncio
class TestConnectionManager:

    @pytest.fixture
    def manager(self) -> ConnectionManager:
        return ConnectionManager(max_connections=10)

    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture) -> MagicMock:
        conn = mocker.Mock()
        conn.connection_id = "conn-1"
        conn.state = ConnectionState.CONNECTED
        conn.is_closed = False
        conn.is_closing = False
        conn.events = EventEmitter()
        conn.close = mocker.AsyncMock()
        return cast(MagicMock, conn)

    async def test_add_connection(self, manager: ConnectionManager, mock_connection: MagicMock) -> None:
        async with manager:
            conn_id = await manager.add_connection(connection=mock_connection)

            assert conn_id == "conn-1"
            assert len(manager) == 1
            assert await manager.get_resource(resource_id="conn-1") is mock_connection

    async def test_cleanup_worker_closes_connections(
        self, manager: ConnectionManager, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        manager._cleanup_queue = asyncio.Queue()
        manager._cleanup_queue.put_nowait(mock_connection)

        try:
            await manager._cleanup_worker()
        except asyncio.CancelledError:
            pass

        mock_connection.close.assert_awaited_once()
        mock_sleep.assert_awaited_with(0)

    async def test_cleanup_worker_critical_error(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        manager._cleanup_queue = asyncio.Queue()
        mocker.patch.object(
            manager._cleanup_queue,
            "get",
            side_effect=[RuntimeError("Fatal"), asyncio.CancelledError],
        )
        spy_logger = mocker.patch.object(ConnectionManager, "_log")
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

        try:
            await manager._cleanup_worker()
        except asyncio.CancelledError:
            pass

        spy_logger.error.assert_called_with("Cleanup worker crashed unexpectedly: %s", mocker.ANY, exc_info=True)
        mock_sleep.assert_awaited_with(0.1)

    async def test_cleanup_worker_early_exit(self, manager: ConnectionManager) -> None:
        manager._cleanup_queue = None
        await manager._cleanup_worker()

    async def test_cleanup_worker_handles_errors(
        self, manager: ConnectionManager, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_connection.close.side_effect = ValueError("Close failed")
        _ = mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        spy_logger = mocker.patch.object(ConnectionManager, "_log")

        manager._cleanup_queue = asyncio.Queue()
        manager._cleanup_queue.put_nowait(mock_connection)

        try:
            await manager._cleanup_worker()
        except asyncio.CancelledError:
            pass

        mock_connection.close.assert_awaited_once()
        spy_logger.error.assert_called()

    async def test_cleanup_worker_ignores_closed_connections(
        self, manager: ConnectionManager, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_connection.is_closed = True
        _ = mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)

        manager._cleanup_queue = asyncio.Queue()
        manager._cleanup_queue.put_nowait(mock_connection)

        try:
            await manager._cleanup_worker()
        except asyncio.CancelledError:
            pass

        mock_connection.close.assert_not_awaited()

    async def test_get_resource_id(self, manager: ConnectionManager, mock_connection: MagicMock) -> None:
        assert manager._get_resource_id(mock_connection) == "conn-1"

    async def test_get_stats_includes_states(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        c1 = mocker.Mock(connection_id="c1", events=EventEmitter())
        c1.state = ConnectionState.CONNECTED
        c2 = mocker.Mock(connection_id="c2", events=EventEmitter())
        c2.state = ConnectionState.CONNECTING

        async with manager:
            await manager.add_connection(connection=c1)
            await manager.add_connection(connection=c2)

            stats = await manager.get_stats()

            assert stats["current_count"] == 2
            assert stats["states"]["connected"] == 1
            assert stats["states"]["connecting"] == 1

    async def test_get_stats_no_lock(self, manager: ConnectionManager) -> None:
        stats = await manager.get_stats()

        assert stats == {}

    async def test_handle_resource_closed(self, manager: ConnectionManager, mock_connection: MagicMock) -> None:
        async with manager:
            await manager.add_connection(connection=mock_connection)

            await manager._handle_resource_closed(resource_id="conn-1")

            assert len(manager) == 0
            assert manager._cleanup_queue is not None
            assert manager._cleanup_queue.qsize() == 1
            assert manager._cleanup_queue.get_nowait() is mock_connection

    async def test_handle_resource_closed_allowed_during_shutdown(
        self, manager: ConnectionManager, mock_connection: MagicMock
    ) -> None:
        manager._lock = asyncio.Lock()
        manager._cleanup_queue = asyncio.Queue()
        manager._resources["conn-1"] = mock_connection
        manager._is_shutting_down = True

        await manager._handle_resource_closed(resource_id="conn-1")

        assert "conn-1" not in manager._resources
        assert manager._cleanup_queue.qsize() == 1

    async def test_handle_resource_closed_guards_no_lock(self, manager: ConnectionManager) -> None:
        assert manager._lock is None
        await manager._handle_resource_closed(resource_id="c1")

    async def test_handle_resource_closed_unmanaged(
        self, manager: ConnectionManager, mock_connection: MagicMock
    ) -> None:
        async with manager:
            await manager._handle_resource_closed(resource_id="conn-1")

            assert manager._cleanup_queue is not None
            assert manager._cleanup_queue.qsize() == 0

    async def test_on_resource_removed_hook(self, manager: ConnectionManager, mock_connection: MagicMock) -> None:
        async with manager:
            await manager.add_connection(connection=mock_connection)
            await manager.remove_connection(connection_id="conn-1")

        manager._on_resource_removed(resource_id="test")

    async def test_remove_connection(self, manager: ConnectionManager, mock_connection: MagicMock) -> None:
        async with manager:
            await manager.add_connection(connection=mock_connection)

            removed = await manager.remove_connection(connection_id="conn-1")

            assert removed is mock_connection
            assert len(manager) == 0
            assert manager._cleanup_queue is not None
            assert manager._cleanup_queue.qsize() == 1
            assert manager._cleanup_queue.get_nowait() is mock_connection

    async def test_remove_connection_missing(self, manager: ConnectionManager) -> None:
        async with manager:
            removed = await manager.remove_connection(connection_id="missing")

            assert removed is None
            assert manager._cleanup_queue is not None
            assert manager._cleanup_queue.qsize() == 0

    async def test_remove_connection_no_lock(self, manager: ConnectionManager) -> None:
        assert await manager.remove_connection(connection_id="c1") is None

    async def test_remove_connection_no_queue(self, manager: ConnectionManager, mock_connection: MagicMock) -> None:
        async with manager:
            await manager.add_connection(connection=mock_connection)
            manager._cleanup_queue = None

            removed = await manager.remove_connection(connection_id="conn-1")

            assert removed is mock_connection
            assert len(manager) == 0

    async def test_start_background_tasks_creates_worker(self, manager: ConnectionManager) -> None:
        manager._lock = asyncio.Lock()

        manager._start_background_tasks()

        assert manager._cleanup_queue is not None
        assert manager._cleanup_worker_task is not None
        assert not manager._cleanup_worker_task.done()
        assert manager._cleanup_worker_task in manager._background_tasks_to_cancel

        manager._cleanup_worker_task.cancel()
        try:
            await manager._cleanup_worker_task
        except asyncio.CancelledError:
            pass

    async def test_start_background_tasks_worker_already_running(
        self, manager: ConnectionManager, mocker: MockerFixture
    ) -> None:
        manager._lock = asyncio.Lock()

        existing_task = mocker.Mock(spec=asyncio.Task)
        existing_task.done.return_value = False
        manager._cleanup_worker_task = existing_task

        spy_create_task = mocker.patch("asyncio.create_task")

        manager._start_background_tasks()

        spy_create_task.assert_not_called()
        assert manager._cleanup_worker_task is existing_task

    async def test_start_background_tasks_worker_duplicate_in_cancel_list(
        self, manager: ConnectionManager, mocker: MockerFixture
    ) -> None:
        manager._lock = asyncio.Lock()

        mock_task = mocker.Mock(spec=asyncio.Task)

        def safe_create_task(coro: Any) -> MagicMock:
            coro.close()
            return cast(MagicMock, mock_task)

        mocker.patch("asyncio.create_task", side_effect=safe_create_task)
        mocker.patch.object(manager, "_cleanup_worker")

        manager._background_tasks_to_cancel.append(mock_task)

        manager._start_background_tasks()

        assert len(manager._background_tasks_to_cancel) == 1
        assert manager._background_tasks_to_cancel[0] is mock_task

    async def test_start_background_tasks_worker_restart_done(
        self, manager: ConnectionManager, mocker: MockerFixture
    ) -> None:
        manager._lock = asyncio.Lock()

        done_task = mocker.Mock(spec=asyncio.Task)
        done_task.done.return_value = True
        manager._cleanup_worker_task = done_task

        mock_new_task = mocker.Mock(spec=asyncio.Task)

        def safe_create_task(coro: Any) -> MagicMock:
            coro.close()
            return cast(MagicMock, mock_new_task)

        spy_create_task = mocker.patch("asyncio.create_task", side_effect=safe_create_task)
        mocker.patch.object(manager, "_cleanup_worker")

        manager._start_background_tasks()

        spy_create_task.assert_called_once()
        assert manager._cleanup_worker_task is mock_new_task
        assert manager._cleanup_worker_task in manager._background_tasks_to_cancel
