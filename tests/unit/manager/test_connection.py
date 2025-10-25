"""Unit tests for the pywebtransport.manager.connection module."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError
from pywebtransport.connection import WebTransportConnection
from pywebtransport.manager import ConnectionManager
from pywebtransport.types import ConnectionState, EventType


@pytest.fixture
def manager() -> ConnectionManager:
    """Fixture for creating a ConnectionManager instance with short intervals for testing."""
    return ConnectionManager(
        max_connections=10,
        connection_cleanup_interval=0.01,
        connection_idle_check_interval=0.01,
        connection_idle_timeout=0.1,
    )


@pytest.fixture
def mock_connection(mocker: MockerFixture) -> MagicMock:
    """Fixture for creating a mock WebTransportConnection."""
    connection = mocker.create_autospec(WebTransportConnection, instance=True)
    connection.connection_id = f"conn_{mocker.sentinel.id}"
    connection.is_closed = False
    connection.is_closing = False
    connection.state = ConnectionState.CONNECTED
    connection.last_activity_time = 0.0
    connection.close = AsyncMock()

    events: dict[EventType, Callable[..., Awaitable[None]]] = {}
    connection.events = events

    def once(event_type: EventType, handler: Callable[..., Awaitable[None]]) -> None:
        connection.events[event_type] = handler

    def on(event_type: EventType, handler: Callable[..., Awaitable[None]]) -> None:
        connection.events[event_type] = handler

    async def trigger(event_type: EventType, data: dict[str, str]) -> None:
        if event_type in connection.events:
            event = MagicMock()
            event.data = data
            await connection.events[event_type](event)

    connection.once = MagicMock(side_effect=once)
    connection.on = MagicMock(side_effect=on)
    connection.trigger = AsyncMock(side_effect=trigger)

    return connection


@pytest_asyncio.fixture
async def running_manager(
    manager: ConnectionManager,
) -> AsyncGenerator[ConnectionManager, None]:
    """Fixture to provide a running ConnectionManager within a context."""
    async with manager as mgr:
        yield mgr


class TestConnectionManager:
    """Test suite for the ConnectionManager class."""

    @pytest.mark.asyncio
    async def test_add_connection(
        self,
        running_manager: ConnectionManager,
        mock_connection: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test adding a valid connection to the manager."""
        conn_id = await running_manager.add_connection(connection=mock_connection)
        assert conn_id == mock_connection.connection_id
        assert len(running_manager) == 1
        mock_connection.once.assert_any_call(event_type=EventType.CONNECTION_CLOSED, handler=mocker.ANY)
        mock_connection.once.assert_any_call(event_type=EventType.CONNECTION_LOST, handler=mocker.ANY)

    @pytest.mark.asyncio
    async def test_add_connection_limit_exceeded(
        self, running_manager: ConnectionManager, mock_connection: MagicMock
    ) -> None:
        """Test that adding a connection fails when the maximum limit is reached."""
        running_manager._max_resources = 0
        with pytest.raises(ConnectionError, match="Maximum connections"):
            await running_manager.add_connection(connection=mock_connection)

    @pytest.mark.asyncio
    async def test_close_idle_resources_exception_group(
        self,
        running_manager: ConnectionManager,
        mock_connection: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test that errors from closing multiple idle connections are grouped and logged."""
        mock_connection.close.side_effect = ValueError("close error")
        log_spy = mocker.spy(running_manager._log, "error")
        await running_manager._close_idle_resources([mock_connection])
        log_spy.assert_called_once()
        assert "Errors occurred while closing idle connections" in log_spy.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_stats_with_states(self, running_manager: ConnectionManager, mock_connection: MagicMock) -> None:
        """Test that get_stats correctly reports connection states."""
        await running_manager.add_connection(connection=mock_connection)
        stats = await running_manager.get_stats()
        assert stats["states"] == {ConnectionState.CONNECTED: 1}

    @pytest.mark.asyncio
    async def test_handle_connection_lost(self, running_manager: ConnectionManager, mock_connection: MagicMock) -> None:
        """Test handling a lost connection, ensuring it's removed and closed."""
        await running_manager.add_connection(connection=mock_connection)
        assert len(running_manager) == 1

        await mock_connection.trigger(EventType.CONNECTION_LOST, {"connection_id": mock_connection.connection_id})
        assert len(running_manager) == 0
        mock_connection.close.assert_awaited_once_with(reason="Connection was lost.")

    @pytest.mark.asyncio
    async def test_handle_connection_lost_already_closed(
        self, running_manager: ConnectionManager, mock_connection: MagicMock
    ) -> None:
        """Test that a lost connection that is already closed does not trigger another close."""
        mock_connection.is_closed = True
        await running_manager.add_connection(connection=mock_connection)
        await mock_connection.trigger(EventType.CONNECTION_LOST, {"connection_id": mock_connection.connection_id})
        mock_connection.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_connection_lost_close_error(
        self,
        running_manager: ConnectionManager,
        mock_connection: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test that an error during the closing of a lost connection is logged."""
        mock_connection.close.side_effect = ValueError("test error")
        log_spy = mocker.spy(running_manager._log, "error")
        await running_manager.add_connection(connection=mock_connection)
        await mock_connection.trigger(EventType.CONNECTION_LOST, {"connection_id": mock_connection.connection_id})
        log_spy.assert_called_once()

    def test_initialization(self, manager: ConnectionManager) -> None:
        """Test that the manager initializes with the correct properties."""
        assert manager._max_resources == 10
        assert manager._cleanup_interval == 0.01
        assert manager._idle_check_interval == 0.01
        assert manager._idle_timeout == 0.1

    @pytest.mark.asyncio
    async def test_manager_inactive_exceptions(self, manager: ConnectionManager, mock_connection: MagicMock) -> None:
        """Test that key methods raise errors or return safely when the manager is not active."""
        with pytest.raises(ConnectionError, match="has not been activated"):
            await manager.add_connection(connection=mock_connection)

        assert await manager.remove_connection(connection_id="dummy") is None
        assert await manager.get_stats() == {}
        await manager._close_idle_resources([])
        await manager._periodic_idle_check()

    @pytest.mark.asyncio
    async def test_on_connection_closed_handler(
        self, running_manager: ConnectionManager, mock_connection: MagicMock
    ) -> None:
        """Test that the manager auto-removes a connection when its 'closed' event is triggered."""
        await running_manager.add_connection(connection=mock_connection)
        assert len(running_manager) == 1

        await mock_connection.trigger(EventType.CONNECTION_CLOSED, {"connection_id": mock_connection.connection_id})
        assert len(running_manager) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "is_shutting_down, is_cancelled, exception, shutdown_called, log_error_called",
        [
            (True, False, None, False, False),
            (False, True, None, True, False),
            (False, False, ValueError("test"), True, True),
            (False, False, None, True, False),
        ],
    )
    async def test_on_idle_check_done_callback(
        self,
        running_manager: ConnectionManager,
        mocker: MockerFixture,
        is_shutting_down: bool,
        is_cancelled: bool,
        exception: Exception | None,
        shutdown_called: bool,
        log_error_called: bool,
    ) -> None:
        """Test the done-callback for the idle check task under various scenarios."""
        running_manager._is_shutting_down = is_shutting_down
        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.cancelled.return_value = is_cancelled
        mock_task.exception.return_value = exception

        shutdown_spy = mocker.patch.object(running_manager, "shutdown", new_callable=AsyncMock)
        log_spy = mocker.spy(running_manager._log, "error")

        running_manager._on_idle_check_done(mock_task)
        await asyncio.sleep(0)

        assert shutdown_spy.call_count == (1 if shutdown_called else 0)
        assert log_spy.call_count == (1 if log_error_called else 0)

    @pytest.mark.asyncio
    async def test_periodic_idle_check_cycle_fails(
        self, running_manager: ConnectionManager, mocker: MockerFixture
    ) -> None:
        """Test that the idle check loop logs an error and continues if a cycle fails."""
        mocker.patch(
            "pywebtransport.manager.connection.get_timestamp",
            side_effect=ValueError("ts error"),
        )
        log_spy = mocker.spy(running_manager._log, "error")

        mocker.patch("asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError)

        await running_manager._periodic_idle_check()
        log_spy.assert_called_with("Idle connection check cycle failed: %s", mocker.ANY, exc_info=mocker.ANY)
        assert isinstance(log_spy.call_args.args[1], ValueError)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "last_activity_time, idle_timeout, is_closing, should_close",
        [
            (900.0, 0.1, False, True),
            (999.9, 0.1, False, True),
            (1000.0, 0.1, False, False),
            (900.0, 0, False, False),
            (900.0, 0.1, True, False),
            (0, 0.1, False, False),
        ],
    )
    async def test_periodic_idle_check_scenarios(
        self,
        running_manager: ConnectionManager,
        mock_connection: MagicMock,
        mocker: MockerFixture,
        last_activity_time: float,
        idle_timeout: float,
        is_closing: bool,
        should_close: bool,
    ) -> None:
        """Test the periodic idle check logic under various conditions."""
        running_manager._idle_timeout = idle_timeout
        mock_connection.last_activity_time = last_activity_time
        mock_connection.is_closing = is_closing
        mocker.patch("pywebtransport.manager.connection.get_timestamp", return_value=1000.0)
        await running_manager.add_connection(connection=mock_connection)

        mocker.patch("asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError)
        await running_manager._periodic_idle_check()

        if should_close:
            mock_connection.close.assert_awaited_once_with(reason="Idle timeout")
            assert len(running_manager) == 0
        else:
            mock_connection.close.assert_not_awaited()
            assert len(running_manager) == 1

    @pytest.mark.asyncio
    async def test_remove_connection(self, running_manager: ConnectionManager, mock_connection: MagicMock) -> None:
        """Test removing a connection successfully."""
        conn_id = await running_manager.add_connection(connection=mock_connection)
        assert len(running_manager) == 1

        removed_conn = await running_manager.remove_connection(connection_id=conn_id)
        assert removed_conn is mock_connection
        assert len(running_manager) == 0
        stats = await running_manager.get_stats()
        assert stats["total_closed"] == 1

    @pytest.mark.asyncio
    async def test_remove_connection_not_found(self, running_manager: ConnectionManager) -> None:
        """Test that removing a non-existent connection returns None."""
        removed_conn = await running_manager.remove_connection(connection_id="unknown")
        assert removed_conn is None

    @pytest.mark.asyncio
    async def test_shutdown_cancels_tasks(self, mocker: MockerFixture) -> None:
        """Test that shutting down the manager cancels background tasks."""
        manager = ConnectionManager()
        async with manager as mgr:
            cleanup_cancel_spy = mocker.spy(mgr._cleanup_task, "cancel")
            idle_cancel_spy = mocker.spy(mgr._idle_check_task, "cancel")

        cleanup_cancel_spy.assert_called_once()
        idle_cancel_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_open_and_ignores_closed_connections(
        self, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        """Test that shutdown closes open connections and ignores already closed ones."""
        manager = ConnectionManager()
        closed_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        closed_connection.is_closed = True
        closed_connection.close = AsyncMock()

        async with manager:
            await manager.add_connection(connection=mock_connection)
            await manager.add_connection(connection=closed_connection)

        mock_connection.close.assert_awaited_once()
        closed_connection.close.assert_not_awaited()
