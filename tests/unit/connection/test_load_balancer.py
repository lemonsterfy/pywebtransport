"""Unit tests for the pywebtransport.connection.load_balancer module."""

import asyncio
from typing import Any, AsyncGenerator, List, Tuple

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError
from pywebtransport.connection import ConnectionLoadBalancer, WebTransportConnection


@pytest.fixture
def targets() -> List[Tuple[str, int]]:
    return [("server1.com", 443), ("server2.com", 4433), ("server3.com", 8443)]


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
async def lb(targets: List[Tuple[str, int]]) -> AsyncGenerator[ConnectionLoadBalancer, None]:
    load_balancer = ConnectionLoadBalancer(targets=targets)
    try:
        yield load_balancer
    finally:
        await load_balancer.shutdown()


class TestConnectionLoadBalancer:
    def test_initialization(self, targets: List[Tuple[str, int]]) -> None:
        lb = ConnectionLoadBalancer(targets=targets)
        assert len(lb) == len(targets)
        assert lb._targets == targets
        assert all(key in lb._target_weights for key in [f"{h}:{p}" for h, p in targets])
        assert all(key in lb._target_latencies for key in [f"{h}:{p}" for h, p in targets])

    def test_initialization_empty_targets(self) -> None:
        with pytest.raises(ValueError, match="Targets list cannot be empty"):
            ConnectionLoadBalancer(targets=[])

    def test_initialization_duplicate_targets(self) -> None:
        targets = [("server1.com", 443), ("server2.com", 4433), ("server1.com", 443)]
        lb = ConnectionLoadBalancer(targets=targets)
        assert lb._targets == [("server1.com", 443), ("server2.com", 4433)]
        assert len(lb._targets) == 2

    def test_create_factory_method(self, targets: List[Tuple[str, int]]) -> None:
        lb = ConnectionLoadBalancer.create(targets=targets)
        assert isinstance(lb, ConnectionLoadBalancer)
        assert set(lb._targets) == set(targets)

    async def test_async_context_manager(self, targets: List[Tuple[str, int]], mocker: MockerFixture) -> None:
        start_mock = mocker.patch.object(ConnectionLoadBalancer, "_start_health_check_task")
        shutdown_mock = mocker.patch.object(ConnectionLoadBalancer, "shutdown", new_callable=mocker.AsyncMock)

        async with ConnectionLoadBalancer(targets=targets) as lb:
            start_mock.assert_called_once()
            assert isinstance(lb, ConnectionLoadBalancer)

        shutdown_mock.assert_awaited_once()

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

        connection = await lb.get_connection(config=mock_client_config, strategy="round_robin")

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
        targets: List[Tuple[str, int]],
    ) -> None:
        mock_create_client = mocker.patch(
            "pywebtransport.connection.load_balancer.WebTransportConnection.create_client"
        )

        for expected_host, expected_port in targets:
            await lb.get_connection(config=mock_client_config, strategy="round_robin")
            mock_create_client.assert_awaited_with(
                config=mock_client_config, host=expected_host, port=expected_port, path="/"
            )

        lb._connections.clear()

        await lb.get_connection(config=mock_client_config, strategy="round_robin")
        expected_host, expected_port = targets[0]
        mock_create_client.assert_awaited_with(
            config=mock_client_config, host=expected_host, port=expected_port, path="/"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "strategy, setup",
        [("least_latency", "setup_latencies"), ("weighted_zero", "setup_zero_weights"), ("invalid_strategy", None)],
    )
    async def test_get_next_target_strategies(
        self,
        lb: ConnectionLoadBalancer,
        mock_client_config: Any,
        mocker: MockerFixture,
        strategy: str,
        setup: str,
    ) -> None:
        if setup == "setup_latencies":
            lb._target_latencies[lb._get_target_key(*lb._targets[0])] = 0.5
            lb._target_latencies[lb._get_target_key(*lb._targets[1])] = 0.1
            lb._target_latencies[lb._get_target_key(*lb._targets[2])] = 0.8
            host, port = await lb._get_next_target("least_latency")
            assert (host, port) == lb._targets[1]
        elif setup == "setup_zero_weights":
            for key in lb._target_weights:
                lb._target_weights[key] = 0.0
            mock_choice = mocker.patch("random.choice", return_value=lb._targets[2])
            await lb._get_next_target("weighted")
            mock_choice.assert_called_once()
        elif strategy == "invalid_strategy":
            with pytest.raises(ValueError, match="Unknown load balancing strategy"):
                await lb._get_next_target("invalid_strategy")

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
        lb._failed_targets.add(lb._get_target_key(*lb._targets[0]))
        lb._connections[lb._get_target_key(*lb._targets[1])] = mock_connection

        stats = await lb.get_load_balancer_stats()

        assert stats["total_targets"] == 3
        assert stats["failed_targets"] == 1
        assert stats["active_connections"] == 1
        assert stats["available_targets"] == 2

    @pytest.mark.asyncio
    async def test_shutdown(self, lb: ConnectionLoadBalancer, mocker: MockerFixture) -> None:
        close_all_mock = mocker.patch.object(lb, "close_all_connections", new_callable=mocker.AsyncMock)

        async def dummy_coro():
            await asyncio.sleep(10)

        lb._health_check_task = asyncio.create_task(dummy_coro())

        await lb.shutdown()

        assert lb._health_check_task.cancelled()
        close_all_mock.assert_awaited_once()

    async def test_start_health_check_task_already_running(
        self, targets: List[Tuple[str, int]], mocker: MockerFixture
    ) -> None:
        lb = ConnectionLoadBalancer(targets=targets)
        mocker.patch.object(lb, "_health_check_loop", new=lambda: None)
        mock_create_task = mocker.patch("asyncio.create_task")

        lb._start_health_check_task()
        lb._start_health_check_task()

        mock_create_task.assert_called_once()

        if lb._health_check_task:
            lb._health_check_task.cancel()

    def test_start_health_check_task_no_running_loop(
        self, targets: List[Tuple[str, int]], mocker: MockerFixture
    ) -> None:
        mocker.patch("asyncio.create_task", side_effect=RuntimeError)
        logger_mock = mocker.patch("pywebtransport.connection.load_balancer.logger")
        lb = ConnectionLoadBalancer(targets=targets)
        mocker.patch.object(lb, "_health_check_loop", new=lambda: None)

        lb._start_health_check_task()

        logger_mock.warning.assert_called_once_with("Could not start health check task: no running event loop.")
        assert lb._health_check_task is None

    @pytest.mark.asyncio
    async def test_health_check_loop_target_restored(self, lb: ConnectionLoadBalancer, mocker: MockerFixture) -> None:
        target = lb._targets[0]
        target_key = f"{target[0]}:{target[1]}"
        lb._failed_targets.add(target_key)

        mock_test_conn = mocker.patch(
            "pywebtransport.connection.utils.test_tcp_connection", new_callable=mocker.AsyncMock, return_value=True
        )
        cycle_done = asyncio.Event()
        original_sleep = asyncio.sleep

        async def controlled_sleep(delay: float):
            cycle_done.set()
            await original_sleep(0)

        mocker.patch("asyncio.sleep", side_effect=controlled_sleep)

        lb._start_health_check_task()
        await asyncio.wait_for(cycle_done.wait(), timeout=1)

        mock_test_conn.assert_awaited_once_with(host=target[0], port=target[1], timeout=lb._health_check_timeout)
        assert target_key not in lb._failed_targets

    @pytest.mark.asyncio
    async def test_health_check_loop_target_still_failed(
        self, lb: ConnectionLoadBalancer, mocker: MockerFixture
    ) -> None:
        target = lb._targets[0]
        target_key = f"{target[0]}:{target[1]}"
        lb._failed_targets.add(target_key)

        mocker.patch(
            "pywebtransport.connection.utils.test_tcp_connection", new_callable=mocker.AsyncMock, return_value=False
        )
        cycle_done = asyncio.Event()
        original_sleep = asyncio.sleep

        async def controlled_sleep(delay: float):
            cycle_done.set()
            await original_sleep(0)

        mocker.patch("asyncio.sleep", side_effect=controlled_sleep)

        lb._start_health_check_task()
        await asyncio.wait_for(cycle_done.wait(), timeout=1)

        assert target_key in lb._failed_targets

    @pytest.mark.asyncio
    async def test_health_check_loop_ignores_check_exceptions(
        self, lb: ConnectionLoadBalancer, mocker: MockerFixture
    ) -> None:
        target_key = lb._get_target_key(*lb._targets[0])
        lb._failed_targets.add(target_key)

        mocker.patch(
            "pywebtransport.connection.utils.test_tcp_connection",
            side_effect=Exception("TCP check failed unexpectedly"),
        )
        cycle_done = asyncio.Event()
        original_sleep = asyncio.sleep

        async def controlled_sleep(delay: float):
            cycle_done.set()
            await original_sleep(0)

        mocker.patch("asyncio.sleep", side_effect=controlled_sleep)

        lb._start_health_check_task()
        await asyncio.wait_for(cycle_done.wait(), timeout=1)

        assert target_key in lb._failed_targets

    @pytest.mark.asyncio
    async def test_health_check_loop_critical_error(self, lb: ConnectionLoadBalancer, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.connection.load_balancer.logger")
        error = ValueError("Critical loop error")
        original_sleep = asyncio.sleep
        sleep_calls = 0

        async def failing_sleep(delay: float):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 1:
                raise error
            await original_sleep(0)

        mocker.patch("asyncio.sleep", side_effect=failing_sleep)

        lb._start_health_check_task()
        await original_sleep(0.01)

        logger_mock.error.assert_called_once_with(f"Health check loop critical error: {error}", exc_info=error)
        assert sleep_calls > 1
