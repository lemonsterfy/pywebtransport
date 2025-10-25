"""Unit tests for the pywebtransport.monitor._base module."""

import asyncio
from typing import Any, Coroutine

import pytest
from pytest_mock import MockerFixture

from pywebtransport.monitor._base import _BaseMonitor


class MockTarget:
    def __init__(self) -> None:
        self.stats = {"connections": 0}


class SyncControllableMonitor(_BaseMonitor[MockTarget]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.loop_ran = asyncio.Event()

    def _collect_metrics(self) -> None:
        self._metrics_history.append(self._target.stats)

    def _check_for_alerts(self) -> None:
        self.loop_ran.set()


class AsyncControllableMonitor(_BaseMonitor[MockTarget]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.loop_ran = asyncio.Event()

    async def _collect_metrics(self) -> None:
        self._metrics_history.append(self._target.stats)

    async def _check_for_alerts(self) -> None:
        self.loop_ran.set()


class FailingMonitor(_BaseMonitor[MockTarget]):
    def _collect_metrics(self) -> None:
        raise ValueError("Collection failed")

    def _check_for_alerts(self) -> None:
        pass


class TestBaseMonitor:
    @pytest.fixture
    def mock_target(self) -> MockTarget:
        return MockTarget()

    @pytest.mark.asyncio
    async def test_aenter_handles_no_running_loop(self, mock_target: MockTarget, mocker: MockerFixture) -> None:
        def close_coro_and_raise(coro: Coroutine[Any, Any, None]) -> None:
            coro.close()
            raise RuntimeError("No loop")

        mocker.patch("asyncio.create_task", side_effect=close_coro_and_raise)
        monitor = SyncControllableMonitor(target=mock_target)
        async with monitor:
            assert not monitor.is_monitoring

    @pytest.mark.asyncio
    async def test_aenter_is_idempotent(self, mock_target: MockTarget) -> None:
        monitor = SyncControllableMonitor(target=mock_target)
        async with monitor:
            initial_task = monitor._monitor_task
            async with monitor:
                assert monitor._monitor_task is initial_task

    @pytest.mark.asyncio
    async def test_aexit_handles_already_done_task(self, mock_target: MockTarget) -> None:
        monitor = FailingMonitor(target=mock_target)
        async with monitor:
            await asyncio.sleep(0.01)
            assert monitor._monitor_task is not None
            assert monitor._monitor_task.done()
        assert not monitor.is_monitoring

    def test_get_and_clear_history(self, mock_target: MockTarget) -> None:
        monitor = SyncControllableMonitor(target=mock_target, metrics_maxlen=3)
        for i in range(5):
            monitor._metrics_history.append({"val": i})
            monitor._alerts.append({"val": i})

        assert len(monitor.get_metrics_history(limit=2)) == 2
        assert len(monitor.get_metrics_history(limit=10)) == 3
        assert len(monitor.get_alerts(limit=10)) == 5

        monitor.clear_history()
        assert not monitor.get_metrics_history()
        assert not monitor.get_alerts()

    def test_initialization(self, mock_target: MockTarget) -> None:
        monitor = SyncControllableMonitor(target=mock_target, monitoring_interval=10.0)
        assert not monitor.is_monitoring
        assert monitor._interval == 10.0

    @pytest.mark.asyncio
    async def test_lifecycle_starts_and_stops_task(self, mock_target: MockTarget) -> None:
        monitor = SyncControllableMonitor(target=mock_target)
        async with monitor:
            await asyncio.wait_for(monitor.loop_ran.wait(), timeout=1)
            assert monitor.is_monitoring
            assert monitor._monitor_task is not None

        assert not monitor.is_monitoring

    @pytest.mark.asyncio
    async def test_loop_handles_async_methods(self, mock_target: MockTarget) -> None:
        monitor = AsyncControllableMonitor(target=mock_target)
        async with monitor:
            await asyncio.wait_for(monitor.loop_ran.wait(), timeout=1)
            assert len(monitor.get_metrics_history()) == 1

    @pytest.mark.asyncio
    async def test_loop_handles_critical_error(self, mock_target: MockTarget, mocker: MockerFixture) -> None:
        error_logger_mock = mocker.patch("pywebtransport.monitor._base.logger.error")
        monitor = FailingMonitor(target=mock_target)
        async with monitor:
            await asyncio.sleep(0.01)

        assert monitor._monitor_task is not None
        assert monitor._monitor_task.done()
        error_logger_mock.assert_called_once()
