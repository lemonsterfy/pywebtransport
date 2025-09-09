"""Unit tests for the pywebtransport.client.monitor module."""

import asyncio
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import WebTransportClient
from pywebtransport.client import ClientMonitor


class TestClientMonitor:
    @pytest.fixture
    def mock_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.is_closed = False
        type(client).stats = mocker.PropertyMock(
            return_value={
                "connections": {"attempted": 0, "success_rate": 1.0},
                "performance": {"avg_connect_time": 0.0},
            }
        )
        return client

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.client.monitor.get_timestamp", return_value=12345.0)

    def test_create_factory(self, mocker: MockerFixture, mock_client: Any) -> None:
        mock_init = mocker.patch("pywebtransport.client.monitor.ClientMonitor.__init__", return_value=None)

        ClientMonitor.create(client=mock_client, monitoring_interval=15.0)

        mock_init.assert_called_once_with(client=mock_client, monitoring_interval=15.0)

    def test_collect_metrics(self, mock_client: Any) -> None:
        monitor = ClientMonitor(client=mock_client)

        monitor._collect_metrics()

        assert len(monitor._metrics_history) == 1
        latest_metrics = monitor._metrics_history[0]
        assert latest_metrics["timestamp"] == 12345.0
        assert latest_metrics["stats"] == mock_client.stats

    def test_collect_metrics_handles_exception(self, mocker: MockerFixture, mock_client: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.client.monitor.logger")
        error = ValueError("Stat collection failed")
        type(mock_client).stats = mocker.PropertyMock(side_effect=error)
        monitor = ClientMonitor(client=mock_client)

        monitor._collect_metrics()

        assert not monitor._metrics_history
        mock_logger.error.assert_called_once_with("Metrics collection failed: %s", error, exc_info=True)

    def test_check_alerts_low_success_rate(self, mock_client: Any, mocker: MockerFixture) -> None:
        type(mock_client).stats = mocker.PropertyMock(
            return_value={"connections": {"attempted": 20, "success_rate": 0.8}, "performance": {}}
        )
        monitor = ClientMonitor(client=mock_client)

        monitor._collect_metrics()
        monitor._check_alerts()

        assert len(monitor._alerts) == 1
        alert = monitor._alerts[0]
        assert alert["type"] == "low_success_rate"

    def test_check_alerts_slow_connections(self, mock_client: Any, mocker: MockerFixture) -> None:
        type(mock_client).stats = mocker.PropertyMock(
            return_value={"connections": {}, "performance": {"avg_connect_time": 6.5}}
        )
        monitor = ClientMonitor(client=mock_client)

        monitor._collect_metrics()
        monitor._check_alerts()

        assert len(monitor._alerts) == 1
        alert = monitor._alerts[0]
        assert alert["type"] == "slow_connections"

    def test_check_alerts_no_alert_if_attempts_low(self, mock_client: Any, mocker: MockerFixture) -> None:
        type(mock_client).stats = mocker.PropertyMock(
            return_value={"connections": {"attempted": 5, "success_rate": 0.5}, "performance": {}}
        )
        monitor = ClientMonitor(client=mock_client)

        monitor._collect_metrics()
        monitor._check_alerts()

        assert not monitor._alerts

    def test_check_alerts_no_metrics(self, mock_client: Any) -> None:
        monitor = ClientMonitor(client=mock_client)

        monitor._check_alerts()

        assert not monitor._alerts

    def test_create_alert_avoids_duplicates(self, mock_client: Any) -> None:
        monitor = ClientMonitor(client=mock_client)

        monitor._create_alert(alert_type="test_alert", message="This is a test.")
        monitor._create_alert(alert_type="test_alert", message="This is a test.")
        assert len(monitor._alerts) == 1

        monitor._create_alert(alert_type="test_alert", message="This is a new test.")
        assert len(monitor._alerts) == 2

    def test_get_metrics_summary(self, mock_client: Any) -> None:
        monitor = ClientMonitor(client=mock_client)
        monitor._collect_metrics()
        monitor._create_alert(alert_type="test_alert", message="Test")

        summary = monitor.get_metrics_summary()

        assert "latest_metrics" in summary
        assert "recent_alerts" in summary
        assert summary["latest_metrics"] == monitor._metrics_history[0]
        assert len(summary["recent_alerts"]) == 1

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mocker: MockerFixture, mock_client: Any) -> None:
        mocker.patch("pywebtransport.client.monitor.ClientMonitor._monitor_loop", new_callable=mocker.MagicMock)
        mock_task: asyncio.Future[Any] = asyncio.Future()
        mock_create_task = mocker.patch("asyncio.create_task", return_value=mock_task)
        monitor = ClientMonitor(client=mock_client)

        async with monitor as returned_monitor:
            assert returned_monitor is monitor
            mock_create_task.assert_called_once()
            assert monitor.is_monitoring

        assert mock_task.cancelled()
        assert not monitor.is_monitoring

    @pytest.mark.asyncio
    async def test_aenter_handles_runtime_error(self, mocker: MockerFixture, mock_client: Any) -> None:
        mocker.patch("pywebtransport.client.monitor.ClientMonitor._monitor_loop", new_callable=mocker.MagicMock)
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("No loop"))
        mock_logger = mocker.patch("pywebtransport.client.monitor.logger")
        monitor = ClientMonitor(client=mock_client)

        async with monitor:
            pass

        mock_logger.error.assert_called_once_with(
            "Failed to start client monitor: No running event loop.", exc_info=True
        )

    @pytest.mark.asyncio
    async def test_aexit_handles_cancelled_error(self, mocker: MockerFixture, mock_client: Any) -> None:
        mocker.patch("pywebtransport.client.monitor.ClientMonitor._monitor_loop", new_callable=mocker.MagicMock)
        mock_task: asyncio.Future[Any] = asyncio.Future()
        mocker.patch("asyncio.create_task", return_value=mock_task)
        monitor = ClientMonitor(client=mock_client)

        async with monitor:
            pass

        assert mock_task.cancelled()

    @pytest.mark.asyncio
    async def test_monitor_loop_collects_and_checks(self, mocker: MockerFixture, mock_client: Any) -> None:
        mocker.stopall()
        mocker.patch("pywebtransport.client.monitor.get_timestamp", return_value=12345.0)
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = [None, asyncio.CancelledError]
        mock_collect = mocker.patch.object(ClientMonitor, "_collect_metrics")
        mock_check = mocker.patch.object(ClientMonitor, "_check_alerts")
        monitor = ClientMonitor(client=mock_client, monitoring_interval=10.0)

        await monitor._monitor_loop()

        assert mock_collect.call_count == 2
        assert mock_check.call_count == 2
        mock_sleep.assert_awaited_with(10.0)

    @pytest.mark.asyncio
    async def test_monitor_loop_stops_when_client_is_closed(self, mocker: MockerFixture, mock_client: Any) -> None:
        mocker.stopall()
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_collect = mocker.patch.object(ClientMonitor, "_collect_metrics")
        mock_client.is_closed = True
        monitor = ClientMonitor(client=mock_client)

        await monitor._monitor_loop()

        mock_collect.assert_not_called()

    def test_init_raises_error_for_incompatible_client_type(self) -> None:
        class IncompatibleClient:
            pass

        incompatible_client = IncompatibleClient()

        with pytest.raises(TypeError, match="ClientMonitor only supports WebTransportClient instances"):
            ClientMonitor(client=incompatible_client)  # type: ignore[arg-type]
