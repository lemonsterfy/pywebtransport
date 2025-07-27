"""Unit tests for the pywebtransport.connection.pool module."""

import asyncio
import time
from typing import Any, AsyncGenerator

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig
from pywebtransport.connection import ConnectionPool, WebTransportConnection


@pytest.fixture
def mock_client_config(mocker: MockerFixture) -> Any:
    return mocker.MagicMock(spec=ClientConfig)


@pytest.fixture
def mock_connection(mocker: MockerFixture) -> Any:
    connection = mocker.create_autospec(WebTransportConnection, instance=True)
    connection.is_connected = True
    connection.remote_address = ("127.0.0.1", 4433)
    connection.close = mocker.AsyncMock()
    connection.connect = mocker.AsyncMock()
    return connection


@pytest.fixture
async def pool() -> AsyncGenerator[ConnectionPool, None]:
    connection_pool = ConnectionPool()
    try:
        yield connection_pool
    finally:
        await connection_pool.close_all()


class TestConnectionPool:
    def test_initialization_defaults(self) -> None:
        pool = ConnectionPool()
        assert pool._max_size == 10
        assert pool._max_idle_time == 300.0
        assert pool._cleanup_interval == 60.0
        assert pool._pool == {}
        assert pool._cleanup_task is None

    @pytest.mark.parametrize(
        "max_size, max_idle_time, cleanup_interval",
        [(20, 150.5, 30.0), (1, 1.0, 1.0)],
    )
    def test_initialization_custom(self, max_size: int, max_idle_time: float, cleanup_interval: float) -> None:
        pool = ConnectionPool(
            max_size=max_size,
            max_idle_time=max_idle_time,
            cleanup_interval=cleanup_interval,
        )
        assert pool._max_size == max_size
        assert pool._max_idle_time == max_idle_time
        assert pool._cleanup_interval == cleanup_interval

    async def test_async_context_manager(self, mocker: MockerFixture) -> None:
        start_mock = mocker.patch.object(ConnectionPool, "_start_cleanup_task")
        close_all_mock = mocker.patch.object(ConnectionPool, "close_all", new_callable=mocker.AsyncMock)

        async with ConnectionPool() as pool:
            start_mock.assert_called_once()
            assert isinstance(pool, ConnectionPool)

        close_all_mock.assert_awaited_once()

    async def test_get_connection_new(
        self, pool: ConnectionPool, mock_client_config: Any, mocker: MockerFixture
    ) -> None:
        mock_conn_class = mocker.patch("pywebtransport.connection.pool.WebTransportConnection")
        mock_instance = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_instance.connect = mocker.AsyncMock()
        mock_conn_class.return_value = mock_instance

        connection = await pool.get_connection(config=mock_client_config, host="example.com", port=443, path="/test")

        mock_conn_class.assert_called_once_with(mock_client_config)
        mock_instance.connect.assert_awaited_once_with(host="example.com", port=443, path="/test")
        assert connection is mock_instance

    async def test_get_connection_reuse(
        self, pool: ConnectionPool, mock_client_config: Any, mock_connection: Any
    ) -> None:
        await pool.return_connection(mock_connection)
        assert pool.get_stats()["total_pooled_connections"] == 1

        reused_connection = await pool.get_connection(
            config=mock_client_config,
            host=mock_connection.remote_address[0],
            port=mock_connection.remote_address[1],
        )

        assert reused_connection is mock_connection
        assert pool.get_stats()["total_pooled_connections"] == 0

    async def test_get_connection_stale(
        self, pool: ConnectionPool, mock_client_config: Any, mock_connection: Any, mocker: MockerFixture
    ) -> None:
        mock_connection.is_connected = False
        pool._pool["127.0.0.1:4433"] = [(mock_connection, time.time())]
        mock_conn_class = mocker.patch("pywebtransport.connection.pool.WebTransportConnection")
        new_mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        new_mock_connection.connect = mocker.AsyncMock()
        mock_conn_class.return_value = new_mock_connection

        connection = await pool.get_connection(config=mock_client_config, host="127.0.0.1", port=4433)

        mock_connection.close.assert_awaited()
        assert connection is new_mock_connection
        new_mock_connection.connect.assert_awaited_once()

    async def test_return_connection_success(self, pool: ConnectionPool, mock_connection: Any) -> None:
        await pool.return_connection(mock_connection)
        stats = pool.get_stats()
        assert stats["total_pooled_connections"] == 1
        pool_key = f"{mock_connection.remote_address[0]}:{mock_connection.remote_address[1]}"
        assert len(pool._pool[pool_key]) == 1

    async def test_return_connection_pool_full(self, mock_connection: Any, mocker: MockerFixture) -> None:
        pool = ConnectionPool(max_size=1)
        await pool.return_connection(mock_connection)
        another_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        another_connection.is_connected = True
        another_connection.remote_address = ("127.0.0.1", 4433)
        another_connection.close = mocker.AsyncMock()

        await pool.return_connection(another_connection)

        assert pool.get_stats()["total_pooled_connections"] == 1
        another_connection.close.assert_awaited_once()
        await pool.close_all()

    async def test_return_connection_disconnected(self, pool: ConnectionPool, mock_connection: Any) -> None:
        mock_connection.is_connected = False
        await pool.return_connection(mock_connection)
        mock_connection.close.assert_awaited_once()
        assert pool.get_stats()["total_pooled_connections"] == 0

    async def test_return_connection_no_remote_addr(self, pool: ConnectionPool, mock_connection: Any) -> None:
        mock_connection.remote_address = None
        await pool.return_connection(mock_connection)
        mock_connection.close.assert_awaited_once()
        assert pool.get_stats()["total_pooled_connections"] == 0

    async def test_get_stats(self, pool: ConnectionPool, mocker: MockerFixture) -> None:
        def create_mock_conn() -> Any:
            conn = mocker.MagicMock(spec=WebTransportConnection)
            conn.close = mocker.AsyncMock()
            return conn

        pool._pool = {
            "key1": [(create_mock_conn(), 0), (create_mock_conn(), 0)],
            "key2": [(create_mock_conn(), 0)],
        }
        stats = pool.get_stats()
        assert stats["total_pooled_connections"] == 3
        assert stats["active_pools"] == 2

    async def test_close_all(self, mocker: MockerFixture) -> None:
        pool = ConnectionPool()

        async def dummy_coro() -> None:
            await asyncio.sleep(3600)

        cleanup_task = asyncio.create_task(dummy_coro())
        pool._cleanup_task = cleanup_task
        conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
        conn1.close = mocker.AsyncMock()
        pool._pool = {"key1": [(conn1, time.time())]}

        await pool.close_all()

        assert cleanup_task.cancelled()
        conn1.close.assert_awaited_once()
        assert not pool._pool

    async def test_cleanup_idle_connections(self, mocker: MockerFixture, mock_connection: Any) -> None:
        pool = ConnectionPool(max_idle_time=10.0, cleanup_interval=0.01)
        mock_time = mocker.patch("time.time")
        cycle_done = asyncio.Event()
        original_sleep = asyncio.sleep

        async def controlled_sleep(delay: float) -> None:
            await original_sleep(delay)
            cycle_done.set()

        mocker.patch("asyncio.sleep", side_effect=controlled_sleep)

        async with pool:
            mock_time.return_value = 1000.0
            await pool.return_connection(mock_connection)
            new_connection = mocker.create_autospec(WebTransportConnection, instance=True)
            new_connection.is_connected = True
            new_connection.remote_address = ("127.0.0.1", 4433)
            new_connection.close = mocker.AsyncMock()
            mock_time.return_value = 1010.0
            await pool.return_connection(new_connection)
            assert pool.get_stats()["total_pooled_connections"] == 2
            mock_time.return_value = 1011.0
            await asyncio.wait_for(cycle_done.wait(), timeout=1)
            mock_connection.close.assert_awaited_once()
            new_connection.close.assert_not_awaited()
            assert pool.get_stats()["total_pooled_connections"] == 1

        new_connection.close.assert_awaited_once()

    async def test_cleanup_task_deletes_empty_pool_key(self, mocker: MockerFixture, mock_connection: Any) -> None:
        pool = ConnectionPool(max_idle_time=5.0, cleanup_interval=0.01)
        mock_time = mocker.patch("time.time")
        cycle_done = asyncio.Event()
        original_sleep = asyncio.sleep

        async def controlled_sleep(delay: float) -> None:
            await original_sleep(delay)
            cycle_done.set()

        mocker.patch("asyncio.sleep", side_effect=controlled_sleep)

        async with pool:
            mock_time.return_value = 1000.0
            await pool.return_connection(mock_connection)
            pool_key = f"{mock_connection.remote_address[0]}:{mock_connection.remote_address[1]}"
            assert pool_key in pool._pool
            mock_time.return_value = 1006.0
            await asyncio.wait_for(cycle_done.wait(), timeout=1)
            assert pool_key not in pool._pool
            assert pool.get_stats()["total_pooled_connections"] == 0

    def test_start_cleanup_task_no_running_loop(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("no running loop"))
        logger_mock = mocker.patch("pywebtransport.connection.pool.logger")
        mocker.patch.object(ConnectionPool, "_cleanup_idle_connections", new_callable=mocker.MagicMock)
        pool = ConnectionPool()
        pool._start_cleanup_task()

        assert pool._cleanup_task is None
        logger_mock.warning.assert_called_once()
