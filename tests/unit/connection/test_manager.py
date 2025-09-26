"""Unit tests for the pywebtransport.connection.manager module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import Mock

import pytest
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, ConnectionState, Event, EventType
from pywebtransport.connection import ConnectionManager, WebTransportConnection
from pywebtransport.types import ConnectionId


@asyncio_fixture
async def manager() -> AsyncGenerator[ConnectionManager, None]:
    async with ConnectionManager(max_connections=10, connection_cleanup_interval=1000.0) as mgr:
        yield mgr


@pytest.fixture
def mock_connection(mocker: MockerFixture) -> WebTransportConnection:
    mock = mocker.create_autospec(WebTransportConnection, instance=True)
    mock.connection_id = ConnectionId("mock-conn-id-fixture")
    mock.state = ConnectionState.CONNECTED
    type(mock).is_closed = mocker.PropertyMock(return_value=False)
    type(mock).is_closing = mocker.PropertyMock(return_value=False)
    mock.close = mocker.AsyncMock()
    mock.once = mocker.Mock()
    return mock


@pytest.fixture
def mock_logger(mocker: MockerFixture) -> Any:
    return mocker.patch("pywebtransport.connection.manager.logger")


class TestConnectionManagerInitialization:
    def test_init_default_values(self) -> None:
        manager = ConnectionManager()

        assert manager._max_connections > 0
        assert manager._cleanup_interval > 0
        assert manager._idle_check_interval > 0
        assert manager._idle_timeout > 0
        assert manager.get_connection_count() == 0
        assert manager._cleanup_task is None
        assert manager._idle_check_task is None

    def test_init_custom_values(self) -> None:
        manager = ConnectionManager(
            max_connections=50,
            connection_cleanup_interval=10.0,
            connection_idle_check_interval=5.0,
            connection_idle_timeout=30.0,
        )

        assert manager._max_connections == 50
        assert manager._cleanup_interval == 10.0
        assert manager._idle_check_interval == 5.0
        assert manager._idle_timeout == 30.0

    def test_create_factory_method(self) -> None:
        manager = ConnectionManager.create(max_connections=20)

        assert isinstance(manager, ConnectionManager)
        assert manager._max_connections == 20

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("add_connection", {"connection": Mock()}),
            ("remove_connection", {"connection_id": "conn-id"}),
            ("get_connection", {"connection_id": "conn-id"}),
            ("get_all_connections", {}),
            ("get_stats", {}),
            ("close_all_connections", {}),
            ("cleanup_closed_connections", {}),
        ],
    )
    async def test_methods_fail_if_not_activated(self, method_name: str, kwargs: dict[str, Any]) -> None:
        manager = ConnectionManager()
        method = getattr(manager, method_name)

        with pytest.raises(ConnectionError, match="ConnectionManager has not been activated"):
            if asyncio.iscoroutinefunction(method):
                await method(**kwargs)
            else:
                method(**kwargs)


@pytest.mark.asyncio
class TestConnectionLifecycle:
    async def test_add_connection_success(
        self,
        manager: ConnectionManager,
        mock_connection: WebTransportConnection,
        mocker: MockerFixture,
    ) -> None:
        conn_id = await manager.add_connection(connection=mock_connection)

        assert conn_id == mock_connection.connection_id
        assert manager.get_connection_count() == 1
        assert await manager.get_connection(connection_id=conn_id) is mock_connection
        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1
        cast(Mock, mock_connection.once).assert_called_once_with(
            event_type=EventType.CONNECTION_CLOSED, handler=mocker.ANY
        )

    async def test_add_connection_exceeds_limit(
        self, mocker: MockerFixture, mock_connection: WebTransportConnection
    ) -> None:
        async with ConnectionManager(max_connections=1) as manager:
            await manager.add_connection(connection=mock_connection)
            another_mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
            another_mock_connection.connection_id = ConnectionId("another-id")

            with pytest.raises(ConnectionError, match=r"Maximum connections \(1\) exceeded"):
                await manager.add_connection(connection=another_mock_connection)

            assert manager.get_connection_count() == 1

    async def test_remove_connection_success(
        self, manager: ConnectionManager, mock_connection: WebTransportConnection
    ) -> None:
        conn_id = await manager.add_connection(connection=mock_connection)
        assert manager.get_connection_count() == 1

        removed_conn = await manager.remove_connection(connection_id=conn_id)

        assert removed_conn is mock_connection
        assert manager.get_connection_count() == 0
        assert await manager.get_connection(connection_id=conn_id) is None
        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["total_closed"] == 1
        assert stats["current_count"] == 0

    async def test_remove_nonexistent_connection(self, manager: ConnectionManager) -> None:
        non_existent_id = ConnectionId("non-existent-id")

        removed_conn = await manager.remove_connection(connection_id=non_existent_id)

        assert removed_conn is None
        assert manager.get_connection_count() == 0

    async def test_get_connection_success(
        self, manager: ConnectionManager, mock_connection: WebTransportConnection
    ) -> None:
        conn_id = await manager.add_connection(connection=mock_connection)

        retrieved_conn = await manager.get_connection(connection_id=conn_id)

        assert retrieved_conn is mock_connection

    async def test_get_nonexistent_connection(self, manager: ConnectionManager) -> None:
        non_existent_id = ConnectionId("non-existent-id")

        retrieved_conn = await manager.get_connection(connection_id=non_existent_id)

        assert retrieved_conn is None

    async def test_on_close_callback_invalid_event_data(
        self, manager: ConnectionManager, mock_connection: WebTransportConnection
    ) -> None:
        await manager.add_connection(connection=mock_connection)
        on_close_callback = cast(Mock, mock_connection.once).call_args.kwargs["handler"]

        await on_close_callback(Event(type=EventType.CONNECTION_CLOSED, data="invalid_data"))

        assert manager.get_connection_count() == 1


@pytest.mark.asyncio
class TestBulkOperationsAndQueries:
    async def test_get_all_connections(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        assert await manager.get_all_connections() == []
        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.connection_id = ConnectionId("conn1-id")
        conn1.once = mocker.Mock()
        conn2 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn2.connection_id = ConnectionId("conn2-id")
        conn2.once = mocker.Mock()
        await manager.add_connection(connection=conn1)
        await manager.add_connection(connection=conn2)

        all_conns = await manager.get_all_connections()

        assert len(all_conns) == 2
        assert conn1 in all_conns
        assert conn2 in all_conns

    async def test_get_connection_count(
        self, manager: ConnectionManager, mock_connection: WebTransportConnection
    ) -> None:
        assert manager.get_connection_count() == 0

        await manager.add_connection(connection=mock_connection)
        assert manager.get_connection_count() == 1

        await manager.remove_connection(connection_id=mock_connection.connection_id)
        assert manager.get_connection_count() == 0

    async def test_get_stats(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        initial_stats = await manager.get_stats()
        assert initial_stats["active"] == 0
        assert initial_stats["states"] == {}

        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.connection_id = ConnectionId("conn1-id")
        conn1.state = ConnectionState.CONNECTED
        conn1.once = mocker.Mock()
        conn2 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn2.connection_id = ConnectionId("conn2-id")
        conn2.state = ConnectionState.CONNECTING
        conn2.once = mocker.Mock()
        await manager.add_connection(connection=conn1)
        await manager.add_connection(connection=conn2)
        stats_after_add = await manager.get_stats()

        assert stats_after_add["active"] == 2
        assert stats_after_add["states"] == {"connected": 1, "connecting": 1}

    async def test_close_all_connections(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.connection_id = ConnectionId("conn1-id")
        conn1.close = mocker.AsyncMock()
        conn1.once = mocker.Mock()
        conn2 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn2.connection_id = ConnectionId("conn2-id")
        conn2.close = mocker.AsyncMock()
        conn2.once = mocker.Mock()
        await manager.add_connection(connection=conn1)
        await manager.add_connection(connection=conn2)

        await manager.close_all_connections()

        conn1.close.assert_awaited_once()
        conn2.close.assert_awaited_once()
        assert manager.get_connection_count() == 0

    async def test_close_all_connections_empty(self, manager: ConnectionManager) -> None:
        await manager.close_all_connections()

        assert manager.get_connection_count() == 0

    async def test_close_all_connections_with_errors(
        self, manager: ConnectionManager, mocker: MockerFixture, mock_logger: Any
    ) -> None:
        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.connection_id = ConnectionId("conn1-id")
        conn1.close = mocker.AsyncMock(side_effect=RuntimeError("Close failed"))
        conn1.once = mocker.Mock()
        await manager.add_connection(connection=conn1)

        await manager.close_all_connections()

        mock_logger.error.assert_called_once()
        assert "Errors occurred while closing connections" in mock_logger.error.call_args.args[0]


@pytest.mark.asyncio
class TestManagerLifecycleAndCleanup:
    async def test_context_manager_lifecycle(self, mocker: MockerFixture) -> None:
        mock_start_tasks = mocker.patch.object(ConnectionManager, "_start_background_tasks")
        mock_shutdown = mocker.patch.object(ConnectionManager, "shutdown", new_callable=mocker.AsyncMock)

        async with ConnectionManager():
            mock_start_tasks.assert_called_once()

        mock_shutdown.assert_awaited_once()

    async def test_shutdown(self, mocker: MockerFixture) -> None:
        async with ConnectionManager() as manager:
            mocker.patch.object(manager, "close_all_connections", new_callable=mocker.AsyncMock)
            assert manager._cleanup_task is not None and not manager._cleanup_task.done()
            assert manager._idle_check_task is not None and not manager._idle_check_task.done()
            cleanup_task_cancel_spy = mocker.spy(manager._cleanup_task, "cancel")
            idle_task_cancel_spy = mocker.spy(manager._idle_check_task, "cancel")

            await manager.shutdown()

            cleanup_task_cancel_spy.assert_called_once()
            idle_task_cancel_spy.assert_called_once()

    async def test_shutdown_is_idempotent(self, mocker: MockerFixture) -> None:
        async with ConnectionManager() as manager:
            mock_close_all = mocker.patch.object(manager, "close_all_connections", new_callable=mocker.AsyncMock)
            await manager.shutdown()
            await manager.shutdown()
            mock_close_all.assert_awaited_once()

    @pytest.mark.parametrize("task_name", ["_periodic_cleanup", "_periodic_idle_check"])
    async def test_background_task_failure_triggers_shutdown(self, mocker: MockerFixture, task_name: str) -> None:
        mocker.patch.object(ConnectionManager, "_start_background_tasks")
        async with ConnectionManager() as manager:
            mock_shutdown = mocker.patch.object(manager, "shutdown", new_callable=mocker.AsyncMock)

            async def failing_coro() -> None:
                raise RuntimeError("Task failed")

            failing_task = asyncio.create_task(failing_coro())

            if task_name == "_periodic_cleanup":
                callback = manager._on_cleanup_done
            else:
                callback = manager._on_idle_check_done
            failing_task.add_done_callback(callback)

            await asyncio.sleep(0.01)

            mock_shutdown.assert_awaited_once()

    async def test_shutdown_no_tasks(self, manager: ConnectionManager) -> None:
        manager._cleanup_task = None
        manager._idle_check_task = None

        await manager.shutdown()

    async def test_start_background_tasks_idempotency(self, manager: ConnectionManager) -> None:
        task1 = manager._cleanup_task

        manager._start_background_tasks()
        task2 = manager._cleanup_task

        assert task1 is task2

    async def test_cleanup_closed_connections(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        conn_open = mocker.create_autospec(WebTransportConnection, instance=True)
        conn_open.connection_id = ConnectionId("open-conn")
        type(conn_open).is_closed = mocker.PropertyMock(return_value=False)
        conn_open.once = mocker.Mock()
        conn_closed = mocker.create_autospec(WebTransportConnection, instance=True)
        conn_closed.connection_id = ConnectionId("closed-conn")
        type(conn_closed).is_closed = mocker.PropertyMock(return_value=True)
        conn_closed.once = mocker.Mock()
        await manager.add_connection(connection=conn_open)
        await manager.add_connection(connection=conn_closed)
        assert manager.get_connection_count() == 2

        cleaned_count = await manager.cleanup_closed_connections()

        assert cleaned_count == 1
        assert manager.get_connection_count() == 1
        assert await manager.get_connection(connection_id=conn_open.connection_id) is conn_open
        assert await manager.get_connection(connection_id=conn_closed.connection_id) is None

    async def test_cleanup_with_no_closed_connections(
        self, manager: ConnectionManager, mock_connection: WebTransportConnection
    ) -> None:
        await manager.add_connection(connection=mock_connection)

        cleaned_count = await manager.cleanup_closed_connections()

        assert cleaned_count == 0
        assert manager.get_connection_count() == 1

    async def test_periodic_cleanup_task_logic(self, mocker: MockerFixture) -> None:
        mock_cleanup = mocker.patch.object(
            ConnectionManager, "cleanup_closed_connections", new_callable=mocker.AsyncMock
        )
        async with ConnectionManager(connection_cleanup_interval=0.01):
            await asyncio.sleep(0.05)
        mock_cleanup.assert_awaited()
        assert mock_cleanup.await_count > 0

    async def test_periodic_cleanup_task_exception_handling(self, mocker: MockerFixture, mock_logger: Any) -> None:
        test_exception = RuntimeError("Cleanup failed")
        mock_cleanup = mocker.patch.object(ConnectionManager, "cleanup_closed_connections", side_effect=test_exception)
        async with ConnectionManager(connection_cleanup_interval=0.01):
            await asyncio.sleep(0.05)
        mock_cleanup.assert_awaited()
        mock_logger.error.assert_called_with(
            "Connection cleanup cycle failed: %s",
            test_exception,
            exc_info=test_exception,
        )


@pytest.mark.asyncio
class TestIdleConnectionManagement:
    async def test_idle_connection_is_closed(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.connection.manager.get_timestamp", side_effect=[1000.0, 2000.0])
        async with ConnectionManager(connection_idle_timeout=500.0, connection_idle_check_interval=0.01) as manager:
            conn_idle = mocker.create_autospec(WebTransportConnection, instance=True)
            conn_idle.connection_id = ConnectionId("idle-conn")
            type(conn_idle).is_closed = mocker.PropertyMock(return_value=False)
            type(conn_idle).is_closing = mocker.PropertyMock(return_value=False)
            conn_idle.last_activity_time = 1000.0
            conn_idle.close = mocker.AsyncMock()
            conn_idle.once = mocker.Mock()

            await manager.add_connection(connection=conn_idle)
            await asyncio.sleep(0.05)

            conn_idle.close.assert_awaited_once_with(reason="Idle timeout")

    async def test_active_connection_is_not_closed(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.connection.manager.get_timestamp", side_effect=[1000.0, 1200.0])
        async with ConnectionManager(connection_idle_timeout=500.0, connection_idle_check_interval=0.01) as manager:
            conn_active = mocker.create_autospec(WebTransportConnection, instance=True)
            conn_active.connection_id = ConnectionId("active-conn")
            type(conn_active).is_closed = mocker.PropertyMock(return_value=False)
            type(conn_active).is_closing = mocker.PropertyMock(return_value=False)
            conn_active.last_activity_time = 1000.0
            conn_active.close = mocker.AsyncMock()
            conn_active.once = mocker.Mock()

            await manager.add_connection(connection=conn_active)
            await asyncio.sleep(0.05)

            conn_active.close.assert_not_awaited()

    async def test_idle_check_skips_closing_connections(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.connection.manager.get_timestamp", return_value=2000.0)
        async with ConnectionManager(connection_idle_timeout=500.0, connection_idle_check_interval=0.01) as manager:
            conn_closing = mocker.create_autospec(WebTransportConnection, instance=True)
            conn_closing.connection_id = ConnectionId("closing-conn")
            type(conn_closing).is_closed = mocker.PropertyMock(return_value=False)
            type(conn_closing).is_closing = mocker.PropertyMock(return_value=True)
            conn_closing.last_activity_time = 1000.0
            conn_closing.close = mocker.AsyncMock()
            conn_closing.once = mocker.Mock()

            await manager.add_connection(connection=conn_closing)
            await asyncio.sleep(0.05)

            conn_closing.close.assert_not_awaited()

    async def test_idle_check_error_handling(self, mocker: MockerFixture, mock_logger: Any) -> None:
        test_exception = ValueError("Idle check failed")
        mocker.patch("pywebtransport.connection.manager.get_timestamp", side_effect=test_exception)
        async with ConnectionManager(connection_idle_check_interval=0.01) as _:
            await asyncio.sleep(0.05)
        mock_logger.error.assert_called_with(
            "Idle connection check cycle failed: %s",
            test_exception,
            exc_info=test_exception,
        )

    async def test_idle_check_close_error_handling(self, mocker: MockerFixture, mock_logger: Any) -> None:
        mocker.patch("pywebtransport.connection.manager.get_timestamp", return_value=2000.0)
        async with ConnectionManager(connection_idle_timeout=500.0, connection_idle_check_interval=0.01) as manager:
            conn_idle = mocker.create_autospec(WebTransportConnection, instance=True)
            conn_idle.connection_id = ConnectionId("idle-conn")
            type(conn_idle).is_closed = mocker.PropertyMock(return_value=False)
            type(conn_idle).is_closing = mocker.PropertyMock(return_value=False)
            conn_idle.last_activity_time = 1000.0
            conn_idle.close = mocker.AsyncMock(side_effect=RuntimeError("Close failed"))
            conn_idle.once = mocker.Mock()
            await manager.add_connection(connection=conn_idle)
            await asyncio.sleep(0.05)

            mock_logger.error.assert_called()
            assert "Errors occurred while closing idle connections" in mock_logger.error.call_args.args[0]
