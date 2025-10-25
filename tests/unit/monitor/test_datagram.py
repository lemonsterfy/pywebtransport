"""Unit tests for the pywebtransport.monitor.datagram module."""

import pytest
from pytest_mock import MockerFixture

from pywebtransport import WebTransportDatagramTransport
from pywebtransport.datagram import DatagramStats, DatagramTransportDiagnostics
from pywebtransport.monitor import DatagramMonitor


class TestDatagramMonitor:
    @pytest.fixture
    def mock_transport(self, mocker: MockerFixture) -> WebTransportDatagramTransport:
        transport = mocker.create_autospec(WebTransportDatagramTransport, instance=True)
        stats = DatagramStats(
            session_id="sid",
            created_at=0,
            datagrams_sent=99,
            send_failures=1,
            datagrams_received=90,
            total_send_time=0.99,
        )
        queue_stats = {"outgoing": {"size": 10}}
        diagnostics = DatagramTransportDiagnostics(stats=stats, queue_stats=queue_stats, is_closed=False)
        type(transport).diagnostics = mocker.PropertyMock(return_value=diagnostics)
        type(transport).outgoing_high_water_mark = mocker.PropertyMock(return_value=1000)
        return transport

    @pytest.fixture
    def monitor(self, mock_transport: WebTransportDatagramTransport) -> DatagramMonitor:
        return DatagramMonitor(
            datagram_transport=mock_transport,
            trend_analysis_window=4,
            monitoring_interval=0.01,
        )

    @pytest.mark.parametrize(
        "values, expected",
        [
            ([1, 1, 1], "stable"),
            ([], "stable"),
            ([1], "stable"),
            ([0, 0, 10, 10], "increasing"),
            ([0, 0, 0, 0], "stable"),
            ([10, 10, 0, 0], "decreasing"),
            ([10, 10, 20, 20], "increasing"),
            ([20, 20, 10, 10], "decreasing"),
            ([10, 10, 11, 11], "stable"),
            ([5, 5, 5, 5], "stable"),
        ],
    )
    def test_analyze_trend(self, monitor: DatagramMonitor, values: list[float], expected: str) -> None:
        trend = monitor._analyze_trend(values=values)
        assert trend == expected

    def test_check_for_alerts_no_history(self, monitor: DatagramMonitor) -> None:
        monitor._check_for_alerts()
        assert not monitor.get_alerts()

    def test_collect_metrics_failure(self, monitor: DatagramMonitor, mocker: MockerFixture) -> None:
        mocker.patch.object(
            type(monitor._target),
            "diagnostics",
            new_callable=mocker.PropertyMock,
            side_effect=ValueError,
        )
        logger_mock = mocker.patch("pywebtransport.monitor.datagram.logger.error")

        monitor._collect_metrics()
        assert not monitor.get_samples()
        logger_mock.assert_called_once_with("Datagram metrics collection failed: %s", mocker.ANY, exc_info=True)

    def test_collect_metrics_success(self, monitor: DatagramMonitor) -> None:
        monitor._collect_metrics()
        samples = monitor.get_samples()
        assert len(samples) == 1
        sample = samples[0]
        assert sample["datagrams_sent"] == 99
        assert sample["send_success_rate"] == 0.99
        assert sample["outgoing_queue_size"] == 10

    def test_get_samples(self, monitor: DatagramMonitor) -> None:
        monitor._metrics_history.extend([{"v": 1}, {"v": 2}, {"v": 3}])
        assert monitor.get_samples() == [{"v": 1}, {"v": 2}, {"v": 3}]
        assert monitor.get_samples(limit=2) == [{"v": 2}, {"v": 3}]
        assert monitor.get_samples(limit=0) == []
        assert monitor.get_samples(limit=None) == [{"v": 1}, {"v": 2}, {"v": 3}]

    def test_high_queue_size_alert(
        self,
        monitor: DatagramMonitor,
        mock_transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
    ) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        queue_stats = {"outgoing": {"size": 950}}
        diagnostics = DatagramTransportDiagnostics(stats=stats, queue_stats=queue_stats, is_closed=False)
        mocker.patch.object(
            type(mock_transport),
            "diagnostics",
            new_callable=mocker.PropertyMock,
            return_value=diagnostics,
        )
        monitor._collect_metrics()
        monitor._check_for_alerts()
        alerts = monitor.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["type"] == "high_queue_size"

    def test_increasing_send_time_alert(self, monitor: DatagramMonitor) -> None:
        base_sample = {
            "outgoing_queue_size": 10,
            "send_success_rate": 0.99,
            "timestamp": 123,
        }
        monitor._metrics_history.extend(
            [
                {**base_sample, "avg_send_time": 0.01},
                {**base_sample, "avg_send_time": 0.01},
                {**base_sample, "avg_send_time": 0.05},
                {**base_sample, "avg_send_time": 0.05},
            ]
        )
        monitor._check_for_alerts()
        alerts = monitor.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["type"] == "increasing_send_time"

    def test_initialization(self, mock_transport: WebTransportDatagramTransport) -> None:
        monitor = DatagramMonitor(
            datagram_transport=mock_transport,
            samples_maxlen=50,
            queue_size_threshold=0.8,
            success_rate_threshold=0.7,
            trend_analysis_window=5,
        )
        assert monitor._metrics_history.maxlen == 50
        assert monitor._queue_size_threshold == 0.8
        assert monitor._success_rate_threshold == 0.7
        assert monitor._trend_analysis_window == 5

    def test_low_success_rate_alert(
        self,
        monitor: DatagramMonitor,
        mock_transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
    ) -> None:
        stats = DatagramStats(session_id="sid", created_at=0, datagrams_sent=75, send_failures=25)
        queue_stats = {"outgoing": {"size": 10}}
        diagnostics = DatagramTransportDiagnostics(stats=stats, queue_stats=queue_stats, is_closed=False)
        mocker.patch.object(
            type(mock_transport),
            "diagnostics",
            new_callable=mocker.PropertyMock,
            return_value=diagnostics,
        )
        monitor._collect_metrics()
        monitor._check_for_alerts()
        alerts = monitor.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["type"] == "low_success_rate"

    def test_no_alerts_when_healthy(self, monitor: DatagramMonitor) -> None:
        monitor._collect_metrics()
        monitor._check_for_alerts()
        assert not monitor.get_alerts()

    def test_no_increasing_send_time_alert_with_stable_trend(self, monitor: DatagramMonitor) -> None:
        base_sample = {
            "outgoing_queue_size": 10,
            "send_success_rate": 0.99,
            "timestamp": 123,
            "avg_send_time": 0.01,
        }
        monitor._metrics_history.extend([base_sample] * monitor._trend_analysis_window)

        monitor._check_for_alerts()

        assert not monitor.get_alerts()

    def test_no_trend_alert_with_insufficient_history(self, monitor: DatagramMonitor) -> None:
        base_sample = {
            "outgoing_queue_size": 10,
            "send_success_rate": 0.99,
            "timestamp": 123,
            "avg_send_time": 0.01,
        }
        monitor._metrics_history.extend([base_sample] * (monitor._trend_analysis_window - 1))

        monitor._check_for_alerts()

        assert not monitor.get_alerts()
