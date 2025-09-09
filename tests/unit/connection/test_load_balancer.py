"""Unit tests for the pywebtransport.connection.load_balancer module."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError
from pywebtransport.connection import ConnectionLoadBalancer, WebTransportConnection


@pytest.fixture
async def lb(targets: list[tuple[str, int]]) -> AsyncGenerator[ConnectionLoadBalancer, None]:
    async with ConnectionLoadBalancer(targets=targets) as load_balancer:
        yield load_balancer


@pytest.fixture
def mock_client_config(mocker: MockerFixture) -> Any:
    return mocker.MagicMock(spec=ClientConfig)


@pytest.fixture
def mock_connection(mocker: MockerFixture) -> Any:
    connection = mocker.create_autospec(WebTransportConnection, instance=True)
    connection.is_connected = True
    connection.remote_address = ("server1.com", 443)
    connection.close = mocker.AsyncMock()
    return connection


@pytest.fixture
def targets() -> list[tuple[str, int]]:
    return [("server1.com", 443), ("server2.com", 4433), ("server3.com", 8443)]


class TestConnectionLoadBalancer:
    def test_initialization(self, targets: list[tuple[str, int]]) -> None:
        lb = ConnectionLoadBalancer(targets=targets)

        assert len(lb) == len(targets)
        assert lb._targets == targets
        assert all(key in lb._target_weights for key in [f"{h}:{p}" for h, p in targets])
        assert all(key in lb._target_latencies for key in [f"{h}:{p}" for h, p in targets])

    def test_len_method(self, targets: list[tuple[str, int]]) -> None:
        lb = ConnectionLoadBalancer(targets=targets)

        assert len(lb) == len(targets)

    def test_initialization_empty_targets(self) -> None:
        with pytest.raises(ValueError, match="Targets list cannot be empty"):
            ConnectionLoadBalancer(targets=[])

    def test_initialization_duplicate_targets(self) -> None:
        targets = [("server1.com", 443), ("server2.com", 4433), ("server1.com", 443)]

        lb = ConnectionLoadBalancer(targets=targets)

        assert lb._targets == [("server1.com", 443), ("server2.com", 4433)]
        assert len(lb._targets) == 2

    def test_create_factory_method(self, targets: list[tuple[str, int]]) -> None:
        lb = ConnectionLoadBalancer.create(targets=targets)

        assert isinstance(lb, ConnectionLoadBalancer)
        assert set(lb._targets) == set(targets)

    @pytest.mark.asyncio
    async def test_async_context_manager(self, targets: list[tuple[str, int]], mocker: MockerFixture) -> None:
        start_mock = mocker.patch.object(ConnectionLoadBalancer, "_start_health_check_task")
        shutdown_mock = mocker.patch.object(ConnectionLoadBalancer, "shutdown", new_callable=mocker.AsyncMock)

        async with ConnectionLoadBalancer(targets=targets) as lb:
            start_mock.assert_called_once()
            assert isinstance(lb, ConnectionLoadBalancer)

        shutdown_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown(self, lb: ConnectionLoadBalancer, mocker: MockerFixture) -> None:
        close_all_mock = mocker.patch.object(lb, "close_all_connections", new_callable=mocker.AsyncMock)
        assert lb._health_check_task is not None
        task = lb._health_check_task

        await lb.shutdown()

        assert task.done()
        close_all_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_cancellation(self, lb: ConnectionLoadBalancer, mocker: MockerFixture) -> None:
        hanging_task = asyncio.create_task(asyncio.sleep(3600))
        lb._health_check_task = hanging_task
        close_all_mock = mocker.patch.object(lb, "close_all_connections", new_callable=mocker.AsyncMock)
        shutdown_task = asyncio.create_task(lb.shutdown())
        await asyncio.sleep(0)

        shutdown_task.cancel()
        try:
            await shutdown_task
        except asyncio.CancelledError:
            pytest.fail("shutdown() should not have propagated CancelledError")

        close_all_mock.assert_awaited_once()
        hanging_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await hanging_task

    @pytest.mark.asyncio
    async def test_close_all_connections_no_connections(
        self, lb: ConnectionLoadBalancer, mocker: MockerFixture
    ) -> None:
        task_group_mock = mocker.patch("asyncio.TaskGroup")

        await lb.close_all_connections()

        task_group_mock.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("strategy", ["round_robin", "weighted", "least_latency"])
    async def test_get_connection_new(
        self,
        lb: ConnectionLoadBalancer,
        mock_client_config: Any,
        mock_connection: Any,
        mocker: MockerFixture,
        strategy: str,
    ) -> None:
        mock_create_client = mocker.patch(
            "pywebtransport.connection.load_balancer.WebTransportConnection.create_client", return_value=mock_connection
        )
        mocker.patch("random.choices", return_value=[("server2.com", 4433)])

        connection = await lb.get_connection(config=mock_client_config, strategy=strategy)

        assert connection is mock_connection
        mock_create_client.assert_awaited_once()
        target_key = f"{mock_create_client.call_args.kwargs['host']}:{mock_create_client.call_args.kwargs['port']}"
        assert lb._target_latencies[target_key] > 0

    @pytest.mark.asyncio
    async def test_get_connection_reuse(
        self,
        lb: ConnectionLoadBalancer,
        mock_client_config: Any,
        mock_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_create_client = mocker.patch(
            "pywebtransport.connection.load_balancer.WebTransportConnection.create_client", return_value=mock_connection
        )
        target_to_use = ("server1.com", 443)
        mocker.patch.object(lb, "_get_next_target", new_callable=mocker.AsyncMock, return_value=target_to_use)

        conn1 = await lb.get_connection(config=mock_client_config)
        conn2 = await lb.get_connection(config=mock_client_config)

        assert conn1 is conn2
        mock_create_client.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_connection_concurrent_waiter(
        self, lb: ConnectionLoadBalancer, mock_client_config: Any, mocker: MockerFixture
    ) -> None:
        target = lb._targets[0]
        mocker.patch.object(lb, "_get_next_target", new_callable=mocker.AsyncMock, return_value=target)
        creation_started = asyncio.Event()
        creation_finished = asyncio.Event()
        mock_instance = mocker.create_autospec(WebTransportConnection, instance=True)

        async def slow_create(*args: Any, **kwargs: Any) -> WebTransportConnection:
            creation_started.set()
            await creation_finished.wait()
            return mock_instance

        mock_create_client = mocker.patch(
            "pywebtransport.connection.load_balancer.WebTransportConnection.create_client", side_effect=slow_create
        )

        task1 = asyncio.create_task(lb.get_connection(config=mock_client_config))
        await creation_started.wait()
        task2 = asyncio.create_task(lb.get_connection(config=mock_client_config))
        await asyncio.sleep(0)
        creation_finished.set()
        results = await asyncio.gather(task1, task2)

        assert results[0] is mock_instance
        assert results[1] is mock_instance
        mock_create_client.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_connection_with_stale_connection(
        self, lb: ConnectionLoadBalancer, mock_client_config: Any, mocker: MockerFixture
    ) -> None:
        target = lb._targets[0]
        target_key = f"{target[0]}:{target[1]}"
        stale_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        stale_connection.is_connected = False
        lb._connections[target_key] = stale_connection
        new_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        new_connection.is_connected = True
        mock_create_client = mocker.patch(
            "pywebtransport.connection.load_balancer.WebTransportConnection.create_client", return_value=new_connection
        )
        mocker.patch.object(lb, "_get_next_target", new_callable=mocker.AsyncMock, return_value=target)

        connection = await lb.get_connection(config=mock_client_config)

        assert connection is new_connection
        mock_create_client.assert_awaited_once()
        assert lb._connections[target_key] is new_connection

    @pytest.mark.asyncio
    async def test_get_connection_failure(
        self, lb: ConnectionLoadBalancer, mock_client_config: Any, mocker: MockerFixture
    ) -> None:
        target_to_fail = lb._targets[0]
        mocker.patch.object(lb, "_get_next_target", new_callable=mocker.AsyncMock, return_value=target_to_fail)
        mocker.patch(
            "pywebtransport.connection.load_balancer.WebTransportConnection.create_client",
            side_effect=ConnectionError("Failed to connect"),
        )
        target_key = f"{target_to_fail[0]}:{target_to_fail[1]}"

        with pytest.raises(ConnectionError):
            await lb.get_connection(config=mock_client_config)

        assert target_key in lb._failed_targets

    @pytest.mark.asyncio
    async def test_get_connection_no_available_targets(
        self, lb: ConnectionLoadBalancer, mock_client_config: Any
    ) -> None:
        for host, port in lb._targets:
            lb._failed_targets.add(f"{host}:{port}")

        with pytest.raises(ConnectionError, match="No available targets"):
            await lb.get_connection(config=mock_client_config)

    @pytest.mark.asyncio
    async def test_round_robin_strategy(
        self,
        lb: ConnectionLoadBalancer,
        mock_client_config: Any,
        mocker: MockerFixture,
        targets: list[tuple[str, int]],
    ) -> None:
        mock_create_client = mocker.patch(
            "pywebtransport.connection.load_balancer.WebTransportConnection.create_client"
        )
        expected_targets = targets[1:] + targets[:1]

        for expected_host, expected_port in expected_targets:
            await lb.get_connection(config=mock_client_config, strategy="round_robin")
            mock_create_client.assert_awaited_with(
                config=mock_client_config, host=expected_host, port=expected_port, path="/"
            )
            lb._connections.clear()

        await lb.get_connection(config=mock_client_config, strategy="round_robin")
        expected_host, expected_port = expected_targets[0]
        mock_create_client.assert_awaited_with(
            config=mock_client_config, host=expected_host, port=expected_port, path="/"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "strategy, setup",
        [("least_latency", "setup_latencies"), ("weighted", "setup_zero_weights"), ("invalid_strategy", None)],
    )
    async def test_get_next_target_strategies(
        self,
        lb: ConnectionLoadBalancer,
        strategy: str,
        setup: str,
        mocker: MockerFixture,
    ) -> None:
        if setup == "setup_latencies":
            lb._target_latencies[lb._get_target_key(host=lb._targets[0][0], port=lb._targets[0][1])] = 0.5
            lb._target_latencies[lb._get_target_key(host=lb._targets[1][0], port=lb._targets[1][1])] = 0.1
            lb._target_latencies[lb._get_target_key(host=lb._targets[2][0], port=lb._targets[2][1])] = 0.8
            host, port = await lb._get_next_target(strategy="least_latency")
            assert (host, port) == lb._targets[1]
        elif setup == "setup_zero_weights":
            for key in lb._target_weights:
                lb._target_weights[key] = 0.0
            mock_choice = mocker.patch("random.choice", return_value=lb._targets[2])
            target = await lb._get_next_target(strategy="weighted")
            mock_choice.assert_called_once()
            assert target == lb._targets[2]
        elif strategy == "invalid_strategy":
            with pytest.raises(ValueError, match="Unknown load balancing strategy"):
                await lb._get_next_target(strategy="invalid_strategy")

    @pytest.mark.asyncio
    async def test_update_target_weight(self, lb: ConnectionLoadBalancer) -> None:
        target = lb._targets[0]
        target_key = f"{target[0]}:{target[1]}"

        await lb.update_target_weight(host=target[0], port=target[1], weight=5.0)
        assert lb._target_weights[target_key] == 5.0

        await lb.update_target_weight(host=target[0], port=target[1], weight=-1.0)
        assert lb._target_weights[target_key] == 0.0

    @pytest.mark.asyncio
    async def test_update_target_weight_nonexistent_target(self, lb: ConnectionLoadBalancer) -> None:
        initial_weights = lb._target_weights.copy()

        await lb.update_target_weight(host="nonexistent.com", port=1234, weight=99.0)

        assert lb._target_weights == initial_weights

    @pytest.mark.asyncio
    async def test_get_target_stats(self, lb: ConnectionLoadBalancer, mock_connection: Any) -> None:
        target1 = lb._targets[0]
        target2 = lb._targets[1]
        key1 = f"{target1[0]}:{target1[1]}"
        key2 = f"{target2[0]}:{target2[1]}"
        mock_connection.remote_address = (target1[0], target1[1])
        lb._connections[key1] = mock_connection
        lb._failed_targets.add(key2)
        lb._target_latencies[key1] = 0.123

        stats = await lb.get_target_stats()

        assert stats[key1]["connected"] is True
        assert stats[key1]["failed"] is False
        assert stats[key1]["latency"] == 0.123
        assert stats[key2]["connected"] is False
        assert stats[key2]["failed"] is True

    @pytest.mark.asyncio
    async def test_get_load_balancer_stats(self, lb: ConnectionLoadBalancer, mock_connection: Any) -> None:
        lb._failed_targets.add(lb._get_target_key(host=lb._targets[0][0], port=lb._targets[0][1]))
        lb._connections[lb._get_target_key(host=lb._targets[1][0], port=lb._targets[1][1])] = mock_connection

        stats = await lb.get_load_balancer_stats()

        assert stats["total_targets"] == 3
        assert stats["failed_targets"] == 1
        assert stats["active_connections"] == 1
        assert stats["available_targets"] == 2

    @pytest.mark.asyncio
    async def test_start_health_check_task_already_running(
        self, targets: list[tuple[str, int]], mocker: MockerFixture
    ) -> None:
        async with ConnectionLoadBalancer(targets=targets) as lb:
            mocker.patch.object(lb, "_health_check_loop", new=lambda: None)
            mock_create_task = mocker.spy(asyncio, "create_task")

            lb._start_health_check_task()

            mock_create_task.assert_not_called()

    def test_start_health_check_task_no_running_loop(
        self, targets: list[tuple[str, int]], mocker: MockerFixture
    ) -> None:
        def mock_create_task(coro: Coroutine[Any, Any, None]) -> None:
            coro.close()
            raise RuntimeError("no running loop")

        mocker.patch("pywebtransport.connection.load_balancer.asyncio.create_task", side_effect=mock_create_task)
        logger_mock = mocker.patch("pywebtransport.connection.load_balancer.logger")
        lb = ConnectionLoadBalancer(targets=targets)

        lb._start_health_check_task()

        logger_mock.warning.assert_called_once_with("Could not start health check task: no running event loop.")
        assert lb._health_check_task is None

    @pytest.mark.asyncio
    async def test_health_check_loop_target_restored(
        self, mocker: MockerFixture, targets: list[tuple[str, int]]
    ) -> None:
        mock_test_conn = mocker.patch(
            "pywebtransport.connection.load_balancer.test_tcp_connection",
            return_value=True,
        )
        async with ConnectionLoadBalancer(targets=targets, health_check_interval=0.01) as lb:
            target = lb._targets[0]
            target_key = f"{target[0]}:{target[1]}"
            lb._failed_targets.add(target_key)

            await asyncio.sleep(0.05)

            mock_test_conn.assert_awaited_with(host=target[0], port=target[1], timeout=lb._health_check_timeout)
            assert target_key not in lb._failed_targets

    @pytest.mark.asyncio
    async def test_health_check_loop_target_still_failed(
        self, mocker: MockerFixture, targets: list[tuple[str, int]]
    ) -> None:
        mocker.patch("pywebtransport.connection.load_balancer.test_tcp_connection", return_value=False)
        async with ConnectionLoadBalancer(targets=targets, health_check_interval=0.01) as lb:
            target = lb._targets[0]
            target_key = f"{target[0]}:{target[1]}"
            lb._failed_targets.add(target_key)

            await asyncio.sleep(0.05)

            assert target_key in lb._failed_targets

    @pytest.mark.asyncio
    async def test_health_check_loop_ignores_check_exceptions(
        self, mocker: MockerFixture, targets: list[tuple[str, int]]
    ) -> None:
        target_key = f"{targets[0][0]}:{targets[0][1]}"
        mocker.patch(
            "pywebtransport.connection.load_balancer.test_tcp_connection",
            side_effect=Exception("TCP check failed unexpectedly"),
        )
        async with ConnectionLoadBalancer(targets=targets, health_check_interval=0.01) as lb:
            lb._failed_targets.add(target_key)

            await asyncio.sleep(0.05)

            assert target_key in lb._failed_targets

    @pytest.mark.asyncio
    async def test_health_check_loop_critical_error(
        self, targets: list[tuple[str, int]], mocker: MockerFixture
    ) -> None:
        logger_mock = mocker.patch("pywebtransport.connection.load_balancer.logger")
        error = ValueError("Critical loop error")
        error_logged = asyncio.Event()
        mocker.patch(
            "pywebtransport.connection.load_balancer.asyncio.sleep", side_effect=[error, asyncio.CancelledError]
        )
        logger_mock.error.side_effect = lambda *args, **kwargs: error_logged.set()

        async with ConnectionLoadBalancer(targets=targets, health_check_interval=0.01):
            await asyncio.wait_for(error_logged.wait(), timeout=1.0)

        logger_mock.error.assert_called_once_with("Health check loop critical error: %s", error, exc_info=error)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("close_all_connections", {}),
            ("get_connection", {"config": None}),
            ("get_load_balancer_stats", {}),
            ("get_target_stats", {}),
            ("update_target_weight", {"host": "h", "port": 1, "weight": 1.0}),
        ],
    )
    async def test_methods_fail_if_not_activated(
        self, targets: list[tuple[str, int]], method_name: str, kwargs: dict[str, Any]
    ) -> None:
        lb = ConnectionLoadBalancer(targets=targets)
        method: Callable[..., Coroutine[Any, Any, Any]] = getattr(lb, method_name)

        with pytest.raises(ConnectionError, match="has not been activated"):
            if "config" in kwargs:
                kwargs["config"] = ClientConfig()
            await method(**kwargs)
