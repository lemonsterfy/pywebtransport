"""Unit tests for the pywebtransport.connection.load_balancer module."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, cast
from unittest.mock import ANY, AsyncMock

import pytest
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError
from pywebtransport.connection import ConnectionLoadBalancer, WebTransportConnection


class TestConnectionLoadBalancer:

    @asyncio_fixture
    async def load_balancer(
        self,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
    ) -> AsyncGenerator[ConnectionLoadBalancer, None]:
        lb = ConnectionLoadBalancer(
            targets=[("host1", 443), ("host2", 443), ("host1", 443)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
            health_check_interval=0.01,
        )
        async with lb as activated_lb:
            yield activated_lb

    @pytest.fixture
    def mock_connection_factory(self, mocker: MockerFixture) -> AsyncMock:
        async def factory(*args: Any, **kwargs: Any) -> WebTransportConnection:
            conn = mocker.create_autospec(WebTransportConnection, instance=True)
            setattr(type(conn), "is_connected", mocker.PropertyMock(return_value=True))
            conn.close = mocker.AsyncMock()
            return conn

        return cast(AsyncMock, mocker.AsyncMock(side_effect=factory))

    @pytest.fixture
    def mock_health_checker(self, mocker: MockerFixture) -> AsyncMock:
        return cast(AsyncMock, mocker.AsyncMock(return_value=True))

    @pytest.mark.asyncio
    async def test_aexit_with_exception(
        self,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
        mocker: MockerFixture,
    ) -> None:
        lb = ConnectionLoadBalancer(
            targets=[("host1", 443)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
        )
        shutdown_mock = mocker.patch.object(lb, "shutdown", new_callable=AsyncMock)

        with pytest.raises(ValueError, match="Test exception"):
            async with lb:
                raise ValueError("Test exception")

        shutdown_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_connections_no_active(self, load_balancer: ConnectionLoadBalancer) -> None:
        await load_balancer.close_all_connections()

    @pytest.mark.asyncio
    async def test_close_all_connections_with_errors(
        self, load_balancer: ConnectionLoadBalancer, caplog: pytest.LogCaptureFixture
    ) -> None:
        conn1 = await load_balancer.get_connection(config=ClientConfig())
        conn2 = await load_balancer.get_connection(config=ClientConfig())
        cast(AsyncMock, conn1.close).side_effect = ValueError("Close failed")

        await load_balancer.close_all_connections()
        await asyncio.sleep(delay=0)

        cast(AsyncMock, conn1.close).assert_awaited_once()
        cast(AsyncMock, conn2.close).assert_awaited_once()
        stats = await load_balancer.get_load_balancer_stats()
        assert stats["active_connections"] == 0
        assert "Errors occurred while closing connections" in caplog.text

    @pytest.mark.asyncio
    async def test_get_connection_all_targets_failed(self, load_balancer: ConnectionLoadBalancer) -> None:
        load_balancer._failed_targets.add("host1:443")
        load_balancer._failed_targets.add("host2:443")

        with pytest.raises(ConnectionError, match="No available targets"):
            await load_balancer.get_connection(config=ClientConfig())

    @pytest.mark.asyncio
    async def test_get_connection_creates_new(
        self,
        load_balancer: ConnectionLoadBalancer,
        mock_connection_factory: AsyncMock,
    ) -> None:
        config = ClientConfig()

        connection = await load_balancer.get_connection(config=config, path="/test")

        assert connection.is_connected
        mock_connection_factory.assert_awaited_once_with(config=config, host="host2", port=443, path="/test")

    @pytest.mark.asyncio
    async def test_get_connection_dogpiling_prevention(
        self,
        mock_connection_factory: AsyncMock,
        mock_health_checker: AsyncMock,
    ) -> None:
        lb = ConnectionLoadBalancer(
            targets=[("host1", 443)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
        )
        config = ClientConfig()
        original_side_effect = mock_connection_factory.side_effect
        factory_started = asyncio.Event()
        resume_factory = asyncio.Event()

        async def controlled_factory(*args: Any, **kwargs: Any) -> WebTransportConnection:
            factory_started.set()
            await resume_factory.wait()
            factory_callable = cast(Callable[..., Awaitable[WebTransportConnection]], original_side_effect)
            return await factory_callable(*args, **kwargs)

        mock_connection_factory.side_effect = controlled_factory

        async with lb:
            task1 = asyncio.create_task(coro=lb.get_connection(config=config))
            await factory_started.wait()
            tasks = [asyncio.create_task(coro=lb.get_connection(config=config)) for _ in range(4)]
            for _ in range(5):
                await asyncio.sleep(delay=0)
            resume_factory.set()
            results = await asyncio.gather(task1, *tasks)

        assert mock_connection_factory.call_count == 1
        assert len(set(results)) == 1

    @pytest.mark.asyncio
    async def test_get_connection_factory_failure(
        self, load_balancer: ConnectionLoadBalancer, mock_connection_factory: AsyncMock
    ) -> None:
        mock_connection_factory.side_effect = ConnectionError("Failed to connect")

        with pytest.raises(ConnectionError, match="Failed to connect"):
            await load_balancer.get_connection(config=ClientConfig(), strategy="round_robin")

        stats = await load_balancer.get_load_balancer_stats()
        assert stats["failed_targets"] == 1

    @pytest.mark.asyncio
    async def test_get_connection_recreates_if_disconnected(
        self,
        load_balancer: ConnectionLoadBalancer,
        mock_connection_factory: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        config = ClientConfig()
        conn1 = await load_balancer.get_connection(config=config, strategy="round_robin")
        setattr(type(conn1), "is_connected", mocker.PropertyMock(return_value=False))

        conn2 = await load_balancer.get_connection(config=config, strategy="round_robin")

        assert conn1 is not conn2
        assert mock_connection_factory.await_count == 2

    @pytest.mark.asyncio
    async def test_get_connection_reuses_existing(
        self,
        load_balancer: ConnectionLoadBalancer,
        mock_connection_factory: AsyncMock,
    ) -> None:
        config = ClientConfig()
        conn1 = await load_balancer.get_connection(config=config, strategy="round_robin")
        await load_balancer.get_connection(config=config, strategy="round_robin")

        conn3 = await load_balancer.get_connection(config=config, strategy="round_robin")

        assert conn3 is conn1
        assert mock_connection_factory.await_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "strategy, setup_mock",
        [
            (
                "weighted",
                lambda mocker: mocker.patch("random.choices", return_value=[("host1", 443)]),
            ),
            ("least_latency", None),
            ("unknown_strategy", None),
        ],
    )
    async def test_get_connection_strategies(
        self,
        load_balancer: ConnectionLoadBalancer,
        mock_connection_factory: AsyncMock,
        mocker: MockerFixture,
        strategy: str,
        setup_mock: Callable[[MockerFixture], Any] | None,
    ) -> None:
        if setup_mock:
            setup_mock(mocker)
        if strategy == "least_latency":
            load_balancer._target_latencies = {"host1:443": 0.2, "host2:443": 0.1}

        if strategy == "unknown_strategy":
            with pytest.raises(ValueError, match="Unknown load balancing strategy"):
                await load_balancer.get_connection(config=ClientConfig(), strategy=strategy)
            return

        await load_balancer.get_connection(config=ClientConfig(), strategy=strategy)

        if strategy == "weighted":
            mock_connection_factory.assert_awaited_with(config=ANY, host="host1", port=443, path=ANY)
        elif strategy == "least_latency":
            mock_connection_factory.assert_awaited_with(config=ANY, host="host2", port=443, path=ANY)

    @pytest.mark.asyncio
    async def test_get_connection_weighted_all_zero_weight(
        self, load_balancer: ConnectionLoadBalancer, mocker: MockerFixture
    ) -> None:
        choice_mock = mocker.patch("random.choice", return_value=("host1", 443))
        await load_balancer.update_target_weight(host="host1", port=443, weight=0.0)
        await load_balancer.update_target_weight(host="host2", port=443, weight=0.0)

        await load_balancer.get_connection(config=ClientConfig(), strategy="weighted")

        choice_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_target_stats(self, load_balancer: ConnectionLoadBalancer) -> None:
        await load_balancer.get_connection(config=ClientConfig())

        stats = await load_balancer.get_target_stats()

        assert "host1:443" in stats
        assert "host2:443" in stats
        assert stats["host2:443"]["connected"] is True
        assert stats["host1:443"]["connected"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error", [ValueError("Checker error"), asyncio.CancelledError()])
    async def test_health_check_checker_raises_exception(
        self,
        load_balancer: ConnectionLoadBalancer,
        mock_health_checker: AsyncMock,
        error: Exception,
    ) -> None:
        load_balancer._failed_targets.add("host1:443")
        check_called = asyncio.Event()

        async def side_effect(*args: Any, **kwargs: Any) -> bool:
            check_called.set()
            if isinstance(error, asyncio.CancelledError):
                raise error
            raise error

        mock_health_checker.side_effect = side_effect

        try:
            async with asyncio.timeout(delay=1.0):
                await check_called.wait()
        except asyncio.TimeoutError:
            pass

        if isinstance(error, asyncio.CancelledError):
            await asyncio.sleep(delay=0.02)

        stats = await load_balancer.get_load_balancer_stats()
        assert stats["failed_targets"] == 1

    @pytest.mark.asyncio
    async def test_health_check_loop_critical_error(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
    ) -> None:
        lb = ConnectionLoadBalancer(
            targets=[("host1", 443)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
            health_check_interval=0.01,
        )
        error = ValueError("Critical Error")

        async def sleep_side_effect(*args: Any, **kwargs: Any) -> None:
            if cast(Any, sleep_side_effect).calls == 0:
                cast(Any, sleep_side_effect).calls += 1
                raise error
            raise asyncio.CancelledError

        cast(Any, sleep_side_effect).calls = 0
        mocker.patch("pywebtransport.connection.load_balancer.asyncio.sleep", side_effect=sleep_side_effect)

        async with lb:
            if lb._health_check_task:
                try:
                    await lb._health_check_task
                except asyncio.CancelledError:
                    pass

        assert "Health check loop critical error: Critical Error" in caplog.text

    @pytest.mark.asyncio
    async def test_health_check_loop_no_failed_targets(
        self,
        load_balancer: ConnectionLoadBalancer,
        mock_health_checker: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        if load_balancer._health_check_task:
            load_balancer._health_check_task.cancel()
            try:
                await load_balancer._health_check_task
            except asyncio.CancelledError:
                pass

        async def side_effect(*args: Any, **kwargs: Any) -> None:
            cast(Any, side_effect).sleep_call_count += 1
            if cast(Any, side_effect).sleep_call_count >= 2:
                raise asyncio.CancelledError

        cast(Any, side_effect).sleep_call_count = 0
        mocker.patch("pywebtransport.connection.load_balancer.asyncio.sleep", side_effect=side_effect)

        await load_balancer._health_check_loop()

        assert cast(Any, side_effect).sleep_call_count >= 2
        mock_health_checker.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_loop_no_lock(
        self,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
    ) -> None:
        lb = ConnectionLoadBalancer(
            targets=[("h", 1)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
        )

        await lb._health_check_loop()

    @pytest.mark.asyncio
    async def test_health_check_loop_recovers_target(
        self,
        load_balancer: ConnectionLoadBalancer,
        mock_health_checker: AsyncMock,
    ) -> None:
        load_balancer._failed_targets.add("host1:443")
        check_called = asyncio.Event()

        async def checker_side_effect(*args: Any, **kwargs: Any) -> bool:
            check_called.set()
            return True

        mock_health_checker.side_effect = checker_side_effect

        async with asyncio.timeout(delay=1.0):
            await check_called.wait()
        await asyncio.sleep(delay=0.05)

        stats = await load_balancer.get_load_balancer_stats()
        assert stats["failed_targets"] == 0

    @pytest.mark.asyncio
    async def test_health_check_task_group_exception(
        self,
        load_balancer: ConnectionLoadBalancer,
        mocker: MockerFixture,
    ) -> None:
        load_balancer._failed_targets.add("malformed_key")

        async def sleep_side_effect(*args: Any, **kwargs: Any) -> None:
            if cast(Any, sleep_side_effect).calls == 0:
                cast(Any, sleep_side_effect).calls += 1
                return
            raise asyncio.CancelledError

        cast(Any, sleep_side_effect).calls = 0
        mocker.patch("pywebtransport.connection.load_balancer.asyncio.sleep", side_effect=sleep_side_effect)

        mock_tg_cls = mocker.patch("pywebtransport.connection.load_balancer.asyncio.TaskGroup")
        mock_tg = mock_tg_cls.return_value
        mock_tg.__aenter__.return_value = mock_tg
        mock_tg.__aexit__.side_effect = ExceptionGroup("TG Error", [ValueError("Task failed")])

        def create_task_side_effect(coro: Any) -> Any:
            coro.close()
            return mocker.Mock()

        mock_tg.create_task.side_effect = create_task_side_effect

        await load_balancer._health_check_loop()

    def test_initialization(
        self,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
    ) -> None:
        lb = ConnectionLoadBalancer(
            targets=[("host1", 443)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
        )

        assert len(lb) == 1

    def test_initialization_no_targets(
        self,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
    ) -> None:
        with pytest.raises(ValueError, match="Targets list cannot be empty"):
            ConnectionLoadBalancer(
                targets=[],
                connection_factory=mock_connection_factory,
                health_checker=mock_health_checker,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("get_connection", {"config": ClientConfig()}),
            ("close_all_connections", {}),
            ("get_load_balancer_stats", {}),
            ("get_target_stats", {}),
            ("update_target_weight", {"host": "h", "port": 1, "weight": 1.0}),
        ],
    )
    async def test_methods_on_uninitialized_raises_error(
        self,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
        method_name: str,
        kwargs: dict[str, Any],
    ) -> None:
        lb = ConnectionLoadBalancer(
            targets=[("host1", 443)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
        )
        method = getattr(lb, method_name)

        with pytest.raises(ConnectionError, match="has not been activated"):
            await method(**kwargs)

    @pytest.mark.asyncio
    async def test_shutdown_cancels_tasks_and_closes_connections(self, load_balancer: ConnectionLoadBalancer) -> None:
        conn = await load_balancer.get_connection(config=ClientConfig())
        assert load_balancer._health_check_task is not None
        assert not load_balancer._health_check_task.done()

        await load_balancer.shutdown()

        assert load_balancer._health_check_task.done()
        cast(AsyncMock, conn.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_catches_cancelled_error(
        self, load_balancer: ConnectionLoadBalancer, mocker: MockerFixture
    ) -> None:
        async def side_effect(*args: Any, **kwargs: Any) -> None:
            raise asyncio.CancelledError

        mocker.patch("pywebtransport.connection.load_balancer.asyncio.sleep", side_effect=side_effect)

        await load_balancer.shutdown()

    @pytest.mark.asyncio
    async def test_start_health_check_task_already_running(self, load_balancer: ConnectionLoadBalancer) -> None:
        initial_task = load_balancer._health_check_task
        assert initial_task is not None

        load_balancer._start_health_check_task()

        assert load_balancer._health_check_task is initial_task

    @pytest.mark.asyncio
    async def test_start_health_check_task_no_loop(
        self,
        mocker: MockerFixture,
        mock_connection_factory: Callable[..., Awaitable[WebTransportConnection]],
        mock_health_checker: Callable[..., Awaitable[bool]],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("No loop"))
        mocker.patch.object(ConnectionLoadBalancer, "_health_check_loop", new_callable=mocker.Mock)
        lb = ConnectionLoadBalancer(
            targets=[("host1", 443)],
            connection_factory=mock_connection_factory,
            health_checker=mock_health_checker,
        )

        lb._start_health_check_task()

        assert lb._health_check_task is None
        assert "Could not start health check task" in caplog.text

    @pytest.mark.asyncio
    async def test_update_target_weight(self, load_balancer: ConnectionLoadBalancer, mocker: MockerFixture) -> None:
        choices_mock = mocker.patch("random.choices", return_value=[("host2", 443)])
        await load_balancer.update_target_weight(host="host1", port=443, weight=0.0)
        await load_balancer.update_target_weight(host="host2", port=443, weight=100.0)

        await load_balancer.get_connection(config=ClientConfig(), strategy="weighted")

        assert choices_mock.call_args.kwargs["weights"] == [0.0, 100.0]

    @pytest.mark.asyncio
    async def test_update_target_weight_nonexistent_target(self, load_balancer: ConnectionLoadBalancer) -> None:
        await load_balancer.update_target_weight(host="nonexistent", port=123, weight=100.0)

        stats = await load_balancer.get_target_stats()

        assert "nonexistent:123" not in stats
