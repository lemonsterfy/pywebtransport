"""Unit tests for the pywebtransport.connection.pool module."""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError
from pywebtransport.connection import ConnectionPool, WebTransportConnection


class TestConnectionPool:
    @pytest.fixture
    def mock_connection_factory(self, mocker: MockerFixture) -> Callable[[], Any]:
        def _factory() -> Any:
            connection = mocker.create_autospec(WebTransportConnection, instance=True)
            connection.is_connected = True
            connection.remote_address = ("127.0.0.1", 4433)
            connection.close = mocker.AsyncMock()
            return connection

        return _factory

    @pytest.fixture
    def mock_connection(self, mock_connection_factory: Callable[[], Any]) -> Any:
        return mock_connection_factory()

    @pytest.mark.parametrize("invalid_size", [0, -1])
    def test_init_with_invalid_max_size(self, invalid_size: int) -> None:
        with pytest.raises(ValueError, match="max_size must be a positive integer"):
            ConnectionPool(max_size=invalid_size)

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mocker: MockerFixture) -> None:
        start_mock = mocker.patch.object(ConnectionPool, "_start_cleanup_task")
        close_all_mock = mocker.patch.object(ConnectionPool, "close_all", new_callable=mocker.AsyncMock)

        async with ConnectionPool():
            start_mock.assert_called_once()

        close_all_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_handles_failures(self, mocker: MockerFixture) -> None:
        async with ConnectionPool() as pool:
            conn1 = mocker.create_autospec(WebTransportConnection, instance=True)
            conn1.close = mocker.AsyncMock(side_effect=IOError("Close failed"))
            pool._pool["key1"] = [(conn1, time.time())]

            await pool.close_all()

            assert not pool._pool
            conn1.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_without_cleanup_task(self) -> None:
        async with ConnectionPool() as pool:
            pool._cleanup_task = None

    @pytest.mark.asyncio
    async def test_get_connection_reuses_from_pool(self, mock_connection: Any) -> None:
        async with ConnectionPool() as pool:
            pool._pool["127.0.0.1:4433"].append((mock_connection, time.time()))
            pool._total_connections["127.0.0.1:4433"] = 1

            reused_conn = await pool.get_connection(config=ClientConfig(), host="127.0.0.1", port=4433)

            assert reused_conn is mock_connection
            assert not pool._pool["127.0.0.1:4433"]

    @pytest.mark.asyncio
    async def test_get_connection_discards_stale_connection(
        self, mocker: MockerFixture, mock_connection_factory: Callable[[], Any]
    ) -> None:
        async with ConnectionPool() as pool:
            pool_key = "127.0.0.1:4433"
            stale_conn = mock_connection_factory()
            stale_conn.is_connected = False
            pool._pool[pool_key].append((stale_conn, time.time()))
            pool._total_connections[pool_key] = 1
            mocker.patch("pywebtransport.connection.pool.WebTransportConnection.connect")

            await pool.get_connection(config=ClientConfig(), host="127.0.0.1", port=4433)

            assert pool._total_connections[pool_key] == 1
            assert not pool._pool[pool_key]

    @pytest.mark.asyncio
    async def test_get_connection_creation_failure_updates_count(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "pywebtransport.connection.pool.WebTransportConnection.connect",
            side_effect=ConnectionError("Failed to connect"),
        )
        async with ConnectionPool() as pool:
            pool_key = "localhost:1234"

            with pytest.raises(ConnectionError):
                await pool.get_connection(config=ClientConfig(), host="localhost", port=1234)

            assert pool._total_connections[pool_key] == 0

    @pytest.mark.asyncio
    async def test_return_connection_full_pool_closes_it(self, mock_connection_factory: Callable[[], Any]) -> None:
        async with ConnectionPool(max_size=1) as pool:
            conn1 = mock_connection_factory()
            await pool.return_connection(conn1)
            assert len(pool._pool["127.0.0.1:4433"]) == 1
            conn2 = mock_connection_factory()

            await pool.return_connection(conn2)

            assert len(pool._pool["127.0.0.1:4433"]) == 1
            conn2.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_stale_connection_does_not_pool(self, mock_connection: Any) -> None:
        async with ConnectionPool() as pool:
            mock_connection.is_connected = False
            pool._total_connections["127.0.0.1:4433"] = 1

            await pool.return_connection(mock_connection)

            assert not pool._pool
            assert pool._total_connections["127.0.0.1:4433"] == 0
            cast(AsyncMock, mock_connection.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_connection_with_no_remote_address(self, mock_connection: Any) -> None:
        async with ConnectionPool() as pool:
            mock_connection.remote_address = None

            await pool.return_connection(mock_connection)

            assert not pool._pool
            cast(AsyncMock, mock_connection.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_connection_concurrent_respects_max_size(self, mocker: MockerFixture) -> None:
        created_connections: list[Any] = []

        def connection_factory(*args: Any, **kwargs: Any) -> Any:
            new_conn = mocker.create_autospec(WebTransportConnection, instance=True)
            new_conn.connect = mocker.AsyncMock()
            new_conn.close = mocker.AsyncMock()
            new_conn.is_connected = True
            new_conn.remote_address = ("localhost", 1234)
            created_connections.append(new_conn)
            return new_conn

        mocker.patch(
            "pywebtransport.connection.pool.WebTransportConnection",
            side_effect=connection_factory,
        )

        async with ConnectionPool(max_size=2) as pool:

            async def getter() -> WebTransportConnection:
                return await pool.get_connection(config=ClientConfig(), host="localhost", port=1234)

            tasks = [asyncio.create_task(getter()) for _ in range(3)]
            await asyncio.sleep(0.01)

            assert len(created_connections) == 2
            assert not tasks[2].done()

            conn1 = await tasks[0]
            await tasks[1]
            await pool.return_connection(conn1)
            conn3 = await asyncio.wait_for(tasks[2], timeout=1.0)

            assert conn3 is conn1
            assert len(created_connections) == 2

    @pytest.mark.asyncio
    async def test_internal_methods_are_safe_before_activation(self) -> None:
        pool = ConnectionPool()

        await pool._cleanup_idle_connections()

    def test_start_cleanup_task_is_idempotent(self, mocker: MockerFixture) -> None:
        pool = ConnectionPool()
        create_task_mock = mocker.patch("asyncio.create_task")
        mocker.patch.object(pool, "_cleanup_idle_connections", new=MagicMock())

        pool._start_cleanup_task()
        cast(MagicMock, pool._cleanup_task).done.return_value = False
        pool._start_cleanup_task()

        create_task_mock.assert_called_once()

    def test_start_cleanup_task_handles_no_event_loop(self, mocker: MockerFixture) -> None:
        pool = ConnectionPool()
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("no loop"))
        mocker.patch.object(pool, "_cleanup_idle_connections")

        pool._start_cleanup_task()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["prunes_stale", "keeps_fresh", "handles_empty_list"])
    async def test_cleanup_task_scenarios(
        self, mocker: MockerFixture, mock_connection_factory: Callable[[], Any], scenario: str
    ) -> None:
        class StopTest(Exception):
            pass

        pool = ConnectionPool(max_idle_time=5.0)
        pool._conditions = defaultdict(asyncio.Condition)
        mocker.patch("asyncio.sleep", side_effect=[None, StopTest()])
        time_mock = mocker.patch("pywebtransport.connection.pool.time.time")
        pool_key = "127.0.0.1:4433"
        stale_conn, fresh_conn = mock_connection_factory(), mock_connection_factory()
        if scenario == "prunes_stale":
            pool._pool[pool_key] = [(stale_conn, 990.0), (fresh_conn, 1000.0)]
            pool._total_connections[pool_key] = 2
            time_mock.return_value = 1000.0
        elif scenario == "keeps_fresh":
            pool._pool[pool_key] = [(fresh_conn, 1000.0)]
            pool._total_connections[pool_key] = 1
            time_mock.return_value = 1001.0
        elif scenario == "handles_empty_list":
            pool._pool[pool_key] = []
            pool._total_connections[pool_key] = 0
            time_mock.return_value = 1000.0

        await pool._cleanup_idle_connections()

        if scenario == "prunes_stale":
            assert len(pool._pool[pool_key]) == 1
            assert pool._pool[pool_key][0][0] is fresh_conn
            assert pool._total_connections[pool_key] == 1
        elif scenario == "keeps_fresh":
            assert len(pool._pool[pool_key]) == 1
            assert pool._total_connections[pool_key] == 1
        elif scenario == "handles_empty_list":
            assert not pool._pool.get(pool_key)
            assert pool._total_connections[pool_key] == 0

    @pytest.mark.asyncio
    async def test_cleanup_task_crashes_safely(self, mocker: MockerFixture, caplog: Any) -> None:
        async with ConnectionPool() as pool:
            mocker.patch("asyncio.sleep", new_callable=AsyncMock)
            mocker.patch(
                "pywebtransport.connection.pool.time.time",
                side_effect=[ValueError("Time is broken"), time.time()],
            )

            await pool._cleanup_idle_connections()

            assert "Pool cleanup task error" in caplog.text

    def test_get_stats(self, mocker: MockerFixture) -> None:
        pool = ConnectionPool()
        pool._conditions = defaultdict(asyncio.Condition)
        pool._pool = {"key1": [mocker.Mock(), mocker.Mock()], "key2": [mocker.Mock()]}
        pool._total_connections = defaultdict(int, {"key1": 2, "key2": 1, "key3_creating": 1})

        stats = pool.get_stats()

        assert stats["total_pooled_connections"] == 3
        assert stats["total_active_connections"] == 4
        assert stats["active_pools"] == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["close_all", "get_connection", "return_connection", "get_stats"])
    async def test_methods_raise_if_not_activated(self, method_name: str, mock_connection: Any) -> None:
        pool = ConnectionPool()
        method = getattr(pool, method_name)
        args: dict[str, Any] = {}
        if method_name == "get_connection":
            args = {"config": ClientConfig(), "host": "localhost", "port": 1234}
        elif method_name == "return_connection":
            args = {"connection": mock_connection}

        with pytest.raises(ConnectionError, match="ConnectionPool has not been activated"):
            if asyncio.iscoroutinefunction(method):
                await method(**args)
            else:
                method(**args)
