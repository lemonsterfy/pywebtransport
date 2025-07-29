"""Unit tests for the pywebtransport.connection.manager module."""

import asyncio
from typing import Any, AsyncGenerator, List

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, ConnectionState
from pywebtransport.connection import ConnectionManager, WebTransportConnection
from pywebtransport.types import ConnectionId


@pytest.fixture
def mock_logger(mocker: MockerFixture) -> Any:
    return mocker.patch("pywebtransport.connection.manager.logger")


@pytest.fixture
def mock_connection(mocker: MockerFixture) -> Any:
    mock = mocker.create_autospec(WebTransportConnection, instance=True)
    mock.connection_id = ConnectionId("mock-conn-id-fixture")
    mock.state = mocker.MagicMock(spec=ConnectionState)
    mock.state.value = "established"
    mock.is_closed = False
    mock.close = mocker.AsyncMock()
    return mock


@pytest.fixture
async def manager(mocker: MockerFixture) -> AsyncGenerator[ConnectionManager, None]:
    mgr = ConnectionManager(max_connections=10, cleanup_interval=0.1)
    mocker.patch.object(mgr, "_start_cleanup_task", new=mocker.MagicMock())
    async with mgr as m:
        yield m


class TestConnectionManagerInitialization:
    def test_init_default_values(self) -> None:
        manager = ConnectionManager()
        assert manager._max_connections == 1000
        assert manager._cleanup_interval == 60.0
        assert manager.get_connection_count() == 0
        assert manager._cleanup_task is None

    def test_init_custom_values(self) -> None:
        manager = ConnectionManager(max_connections=50, cleanup_interval=10.0)
        assert manager._max_connections == 50
        assert manager._cleanup_interval == 10.0

    def test_create_factory_method(self) -> None:
        manager = ConnectionManager.create(max_connections=20)
        assert isinstance(manager, ConnectionManager)
        assert manager._max_connections == 20


class TestManagerMisc:
    def test_start_cleanup_task(self, mocker: MockerFixture) -> None:
        mock_cleanup_method = mocker.MagicMock()
        mocker.patch.object(ConnectionManager, "_periodic_cleanup", new=mock_cleanup_method)
        mock_create_task = mocker.patch("asyncio.create_task", return_value=mocker.MagicMock())
        manager = ConnectionManager()

        manager._start_cleanup_task()
        mock_cleanup_method.assert_called_once()
        mock_create_task.assert_called_once_with(mock_cleanup_method.return_value)

        mock_task = mock_create_task.return_value
        mock_task.done.return_value = False
        manager._cleanup_task = mock_task

        manager._start_cleanup_task()
        mock_create_task.assert_called_once()

        mock_task.done.return_value = True
        manager._start_cleanup_task()
        assert mock_create_task.call_count == 2
        assert mock_cleanup_method.call_count == 2


@pytest.mark.asyncio
class TestConnectionLifecycle:
    async def test_add_connection_success(self, manager: ConnectionManager, mock_connection: Any) -> None:
        conn_id = await manager.add_connection(mock_connection)
        assert conn_id == mock_connection.connection_id
        assert manager.get_connection_count() == 1
        assert await manager.get_connection(conn_id) is mock_connection

        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1

    async def test_add_connection_exceeds_limit(self, mocker: MockerFixture, mock_connection: Any) -> None:
        manager = ConnectionManager(max_connections=1)
        await manager.add_connection(mock_connection)

        another_mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        another_mock_connection.connection_id = ConnectionId("another-id")

        with pytest.raises(ConnectionError, match=r"Maximum connections \(1\) exceeded"):
            await manager.add_connection(another_mock_connection)

        assert manager.get_connection_count() == 1

    async def test_remove_connection_success(self, manager: ConnectionManager, mock_connection: Any) -> None:
        conn_id = await manager.add_connection(mock_connection)
        assert manager.get_connection_count() == 1

        removed_conn = await manager.remove_connection(conn_id)
        assert removed_conn is mock_connection
        assert manager.get_connection_count() == 0
        assert await manager.get_connection(conn_id) is None

        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["total_closed"] == 1
        assert stats["current_count"] == 0

    async def test_remove_nonexistent_connection(self, manager: ConnectionManager) -> None:
        non_existent_id = ConnectionId("non-existent-id")
        removed_conn = await manager.remove_connection(non_existent_id)
        assert removed_conn is None
        assert manager.get_connection_count() == 0

    async def test_get_connection_success(self, manager: ConnectionManager, mock_connection: Any) -> None:
        conn_id = await manager.add_connection(mock_connection)
        retrieved_conn = await manager.get_connection(conn_id)
        assert retrieved_conn is mock_connection

    async def test_get_nonexistent_connection(self, manager: ConnectionManager) -> None:
        non_existent_id = ConnectionId("non-existent-id")
        retrieved_conn = await manager.get_connection(non_existent_id)
        assert retrieved_conn is None


@pytest.mark.asyncio
class TestBulkOperationsAndQueries:
    async def test_get_all_connections(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        assert await manager.get_all_connections() == []

        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.connection_id = ConnectionId("conn1-id")
        conn2 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn2.connection_id = ConnectionId("conn2-id")

        await manager.add_connection(conn1)
        await manager.add_connection(conn2)

        all_conns = await manager.get_all_connections()
        assert len(all_conns) == 2
        assert conn1 in all_conns
        assert conn2 in all_conns

    async def test_get_connection_count(self, manager: ConnectionManager, mock_connection: Any) -> None:
        assert manager.get_connection_count() == 0
        await manager.add_connection(mock_connection)
        assert manager.get_connection_count() == 1
        await manager.remove_connection(mock_connection.connection_id)
        assert manager.get_connection_count() == 0

    async def test_get_stats(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        initial_stats = await manager.get_stats()
        assert initial_stats["active"] == 0
        assert initial_stats["states"] == {}

        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.connection_id = ConnectionId("conn1-id")
        conn1.state = mocker.MagicMock(spec=ConnectionState)
        conn1.state.value = "established"

        conn2 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn2.connection_id = ConnectionId("conn2-id")
        conn2.state = mocker.MagicMock(spec=ConnectionState)
        conn2.state.value = "connecting"

        await manager.add_connection(conn1)
        await manager.add_connection(conn2)

        stats_after_add = await manager.get_stats()
        assert stats_after_add["active"] == 2
        assert stats_after_add["states"] == {"established": 1, "connecting": 1}

    async def test_close_all_connections(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        original_gather = asyncio.gather

        async def await_all(*tasks: Any, return_exceptions: bool) -> List[Any]:
            return await original_gather(*tasks, return_exceptions=return_exceptions)

        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)
        mock_gather.side_effect = await_all

        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.connection_id = ConnectionId("conn1-id")
        conn1.close = mocker.AsyncMock()
        conn2 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn2.connection_id = ConnectionId("conn2-id")
        conn2.close = mocker.AsyncMock()

        await manager.add_connection(conn1)
        await manager.add_connection(conn2)

        await manager.close_all_connections()

        conn1.close.assert_awaited_once()
        conn2.close.assert_awaited_once()
        mock_gather.assert_awaited_once()
        assert manager.get_connection_count() == 0

    async def test_close_all_connections_empty(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)
        await manager.close_all_connections()
        mock_gather.assert_not_awaited()


@pytest.mark.asyncio
class TestManagerLifecycleAndCleanup:
    async def test_context_manager_lifecycle(self, mocker: MockerFixture) -> None:
        mock_start_cleanup = mocker.patch.object(ConnectionManager, "_start_cleanup_task", new=mocker.MagicMock())
        mock_shutdown = mocker.patch.object(ConnectionManager, "shutdown", new_callable=mocker.AsyncMock)

        async with ConnectionManager():
            mock_start_cleanup.assert_called_once()

        mock_shutdown.assert_awaited_once()

    async def test_shutdown(self, mocker: MockerFixture) -> None:
        manager = ConnectionManager()
        mock_close_all = mocker.patch.object(manager, "close_all_connections", new_callable=mocker.AsyncMock)

        real_task = asyncio.create_task(asyncio.sleep(3600))
        cancel_spy = mocker.spy(real_task, "cancel")
        manager._cleanup_task = real_task

        await manager.shutdown()

        cancel_spy.assert_called_once()
        mock_close_all.assert_awaited_once()

        try:
            await real_task
        except asyncio.CancelledError:
            pass

    async def test_cleanup_closed_connections(self, manager: ConnectionManager, mocker: MockerFixture) -> None:
        conn_open = mocker.create_autospec(WebTransportConnection, instance=True)
        conn_open.connection_id = ConnectionId("open-conn")
        conn_open.is_closed = False

        conn_closed = mocker.create_autospec(WebTransportConnection, instance=True)
        conn_closed.connection_id = ConnectionId("closed-conn")
        conn_closed.is_closed = True

        await manager.add_connection(conn_open)
        await manager.add_connection(conn_closed)
        assert manager.get_connection_count() == 2

        cleaned_count = await manager.cleanup_closed_connections()
        assert cleaned_count == 1
        assert manager.get_connection_count() == 1
        assert await manager.get_connection(conn_open.connection_id) is conn_open
        assert await manager.get_connection(conn_closed.connection_id) is None

    async def test_cleanup_with_no_closed_connections(self, manager: ConnectionManager, mock_connection: Any) -> None:
        await manager.add_connection(mock_connection)
        cleaned_count = await manager.cleanup_closed_connections()
        assert cleaned_count == 0
        assert manager.get_connection_count() == 1

    async def test_periodic_cleanup_task_logic(self, mocker: MockerFixture) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        manager = ConnectionManager(cleanup_interval=123.45)
        mock_cleanup = mocker.patch.object(manager, "cleanup_closed_connections", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = [None, None, asyncio.CancelledError]

        await manager._periodic_cleanup()

        assert mock_sleep.call_count == 3
        mock_sleep.assert_has_awaits([mocker.call(123.45), mocker.call(123.45)])
        assert mock_cleanup.await_count == 2

    async def test_periodic_cleanup_task_exception_handling(self, mocker: MockerFixture, mock_logger: Any) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        manager = ConnectionManager()
        mock_cleanup = mocker.patch.object(manager, "cleanup_closed_connections", new_callable=mocker.AsyncMock)
        test_exception = RuntimeError("Cleanup failed")
        mock_cleanup.side_effect = test_exception
        mock_sleep.side_effect = [None, asyncio.CancelledError]

        await manager._periodic_cleanup()

        mock_cleanup.assert_awaited_once()
        mock_logger.error.assert_called_once_with(
            f"Connection cleanup task crashed: {test_exception}", exc_info=test_exception
        )
