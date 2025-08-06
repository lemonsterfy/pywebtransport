"""Unit tests for the pywebtransport.datagram.monitor module."""

import asyncio
from typing import Any, Coroutine, NoReturn

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import WebTransportDatagramDuplexStream
from pywebtransport.datagram import DatagramMonitor


class TestDatagramMonitor:
    @pytest.fixture
    def monitor(self, mock_stream: Any) -> DatagramMonitor:
        return DatagramMonitor(mock_stream)

    @pytest.fixture
    def mock_stream(self, mocker: MockerFixture) -> Any:
        stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        stream.session_id = "test-session-id-12345678"
        stream.outgoing_high_water_mark = 100
        stats_dict = {
            "datagrams_sent": 100,
            "datagrams_received": 95,
            "send_success_rate": 0.99,
            "avg_send_time": 0.01,
        }
        stream.stats.get.side_effect = lambda key, default=None: stats_dict.get(key, default)
        stream.get_queue_stats = mocker.MagicMock(return_value={"outgoing": {"size": 10}, "incoming": {"size": 5}})
        return stream

    def test_initialization(self, mock_stream: Any) -> None:
        mon = DatagramMonitor(mock_stream)

        assert mon._stream is mock_stream
        assert mon._interval == 5.0
        assert mon._samples.maxlen == 100
        assert mon._alerts.maxlen == 50

    def test_create_factory(self, mock_stream: Any) -> None:
        mon = DatagramMonitor.create(mock_stream, monitoring_interval=10.0)

        assert isinstance(mon, DatagramMonitor)
        assert mon._interval == 10.0

    @pytest.mark.asyncio
    async def test_lifecycle_and_context_manager(self, monitor: DatagramMonitor, mocker: MockerFixture) -> None:
        create_task_spy = mocker.spy(asyncio, "create_task")
        mocker.patch("asyncio.sleep")
        assert not monitor.is_monitoring

        async with monitor:
            assert monitor.is_monitoring
            create_task_spy.assert_called_once()  # type: ignore[unreachable]

        real_task = create_task_spy.spy_return  # type: ignore[unreachable]
        assert not monitor.is_monitoring
        assert real_task.cancelled()

    @pytest.mark.asyncio
    async def test_aenter_idempotent(self, monitor: DatagramMonitor, mocker: MockerFixture) -> None:
        fake_task = asyncio.create_task(asyncio.sleep(0))
        monitor._monitor_task = fake_task
        mock_create_task = mocker.patch("asyncio.create_task")

        async with monitor:
            mock_create_task.assert_not_called()

        assert fake_task.cancelled()

    @pytest.mark.asyncio
    async def test_aexit_no_task(self, monitor: DatagramMonitor) -> None:
        await monitor.__aexit__(None, None, None)

        assert monitor._monitor_task is None

    @pytest.mark.asyncio
    async def test_aenter_handles_runtime_error(
        self, monitor: DatagramMonitor, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        def mock_create_task_with_error(coro: Coroutine[Any, Any, Any]) -> NoReturn:
            coro.close()
            raise RuntimeError("no loop")

        mocker.patch("asyncio.create_task", side_effect=mock_create_task_with_error)

        await monitor.__aenter__()

        assert not monitor.is_monitoring
        assert "Failed to start datagram monitor" in caplog.text

    def test_get_samples_and_alerts_initially_empty(self, monitor: DatagramMonitor) -> None:
        assert monitor.get_samples() == []
        assert monitor.get_alerts() == []

    def test_get_samples_with_limit(self, monitor: DatagramMonitor) -> None:
        monitor._samples.extend([{"id": 1}, {"id": 2}, {"id": 3}])

        samples = monitor.get_samples(limit=2)

        assert len(samples) == 2
        assert samples[0]["id"] == 2
        assert samples[1]["id"] == 3

    @pytest.mark.asyncio
    async def test_monitor_loop_collects_samples(self, monitor: DatagramMonitor, mocker: MockerFixture) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

        async def sleep_side_effect(*args: Any, **kwargs: Any) -> None:
            if mock_sleep.await_count > 1:
                raise asyncio.CancelledError

        mock_sleep.side_effect = sleep_side_effect

        await monitor._monitor_loop()

        assert len(monitor.get_samples()) == 1
        sample = monitor.get_samples()[0]
        assert sample["datagrams_sent"] == 100
        assert sample["outgoing_queue_size"] == 10

    @pytest.mark.asyncio
    async def test_monitor_loop_handles_exception(
        self, monitor: DatagramMonitor, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock, side_effect=ValueError("Test Exception"))

        await monitor._monitor_loop()

        assert "Monitor loop error: Test Exception" in caplog.text

    @pytest.mark.asyncio
    async def test_check_alerts_high_queue_size(self, monitor: DatagramMonitor, mock_stream: Any) -> None:
        mock_stream.get_queue_stats.return_value = {"outgoing": {"size": 95}}
        sample: dict[str, Any] = {
            "outgoing_queue_size": 95,
            "send_success_rate": 1.0,
            "timestamp": 123,
            "avg_send_time": 0.01,
        }

        await monitor._check_alerts(sample)

        assert len(monitor.get_alerts()) == 1
        alert = monitor.get_alerts()[0]
        assert alert["type"] == "high_queue_size"
        assert "Outgoing queue size high: 95" in alert["message"]

    @pytest.mark.asyncio
    async def test_check_alerts_low_success_rate(self, monitor: DatagramMonitor) -> None:
        sample: dict[str, Any] = {
            "outgoing_queue_size": 10,
            "send_success_rate": 0.7,
            "timestamp": 123,
            "avg_send_time": 0.01,
        }

        await monitor._check_alerts(sample)

        assert len(monitor.get_alerts()) == 1
        alert = monitor.get_alerts()[0]
        assert alert["type"] == "low_success_rate"
        assert "Low send success rate: 70.00%" in alert["message"]

    @pytest.mark.asyncio
    async def test_check_alerts_increasing_send_time(self, monitor: DatagramMonitor) -> None:
        monitor._samples.extend(
            [{"avg_send_time": 0.01} for _ in range(5)] + [{"avg_send_time": 0.05} for _ in range(5)]
        )
        sample: dict[str, Any] = {
            "outgoing_queue_size": 10,
            "send_success_rate": 1.0,
            "avg_send_time": 0.05,
            "timestamp": 123,
        }

        await monitor._check_alerts(sample)

        assert len(monitor.get_alerts()) == 1
        alert = monitor.get_alerts()[0]
        assert alert["type"] == "increasing_send_time"
        assert "Average send time is increasing" in alert["message"]

    @pytest.mark.asyncio
    async def test_check_alerts_no_issues(self, monitor: DatagramMonitor) -> None:
        sample: dict[str, Any] = {
            "outgoing_queue_size": 10,
            "send_success_rate": 0.99,
            "timestamp": 123,
            "avg_send_time": 0.01,
        }

        await monitor._check_alerts(sample)

        assert len(monitor.get_alerts()) == 0

    @pytest.mark.parametrize(
        "values, expected_trend",
        [
            ([0.1] * 10, "stable"),
            ([0.0] * 5 + [0.1] * 5, "increasing"),
            ([0.1] * 5 + [0.2] * 5, "increasing"),
            ([0.2] * 5 + [0.1] * 5, "decreasing"),
            ([0.1] * 5 + [0.11] * 5, "stable"),
            ([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], "increasing"),
        ],
    )
    def test_analyze_trend(self, monitor: DatagramMonitor, values: list[float], expected_trend: str) -> None:
        monitor._trend_analysis_window = len(values)

        trend = monitor._analyze_trend(values)

        assert trend == expected_trend

    def test_analyze_trend_insufficient_data(self, monitor: DatagramMonitor) -> None:
        monitor._trend_analysis_window = 10

        trend = monitor._analyze_trend([1.0] * 9)

        assert trend == "stable"
