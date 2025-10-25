"""Unit tests for the pywebtransport.monitor.client module."""

from typing import cast
from unittest.mock import AsyncMock, PropertyMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import WebTransportClient
from pywebtransport.client import ClientDiagnostics, ClientStats
from pywebtransport.monitor import ClientMonitor


class TestClientMonitor:
    @pytest.fixture
    def mock_client(self, mocker: MockerFixture) -> WebTransportClient:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        stats = ClientStats(created_at=0)
        diagnostics = ClientDiagnostics(stats=stats, connection_states={})
        client.diagnostics = AsyncMock(return_value=diagnostics)
        return client

    @pytest.fixture
    def monitor(self, mock_client: WebTransportClient) -> ClientMonitor:
        return ClientMonitor(client=mock_client)

    def test_check_for_alerts_malformed_metrics(self, monitor: ClientMonitor) -> None:
        monitor._metrics_history.append({"stats": "not a dict"})
        monitor._check_for_alerts()
        assert not monitor._alerts

    def test_check_for_alerts_no_metrics(self, monitor: ClientMonitor) -> None:
        monitor._check_for_alerts()
        assert not monitor._alerts

    @pytest.mark.asyncio
    async def test_collect_metrics_failure(
        self, monitor: ClientMonitor, mock_client: WebTransportClient, mocker: MockerFixture
    ) -> None:
        cast(AsyncMock, mock_client.diagnostics).side_effect = ValueError
        logger_mock = mocker.patch("pywebtransport.monitor.client.logger.error")

        await monitor._collect_metrics()
        assert not monitor._metrics_history
        logger_mock.assert_called_once_with("Metrics collection failed: %s", mocker.ANY, exc_info=True)

    @pytest.mark.asyncio
    async def test_collect_metrics_success(self, monitor: ClientMonitor, mock_client: WebTransportClient) -> None:
        await monitor._collect_metrics()
        assert len(monitor._metrics_history) == 1
        metrics = monitor._metrics_history[0]
        assert "timestamp" in metrics
        cast(AsyncMock, mock_client.diagnostics).assert_awaited_once()

    def test_create_alert_deduplication(self, monitor: ClientMonitor) -> None:
        monitor._create_alert(alert_type="test", message="This is a test")
        monitor._create_alert(alert_type="test", message="This is a test")
        assert len(monitor._alerts) == 1

        monitor._create_alert(alert_type="test", message="This is a new test")
        assert len(monitor._alerts) == 2

    def test_get_metrics_summary(self, monitor: ClientMonitor) -> None:
        summary = monitor.get_metrics_summary()
        assert summary["latest_metrics"] == {}
        assert summary["recent_alerts"] == []
        assert not summary["is_monitoring"]

        monitor._metrics_history.append({"stats": {"key": "value"}})
        monitor._alerts.append({"type": "test_alert"})
        summary = monitor.get_metrics_summary()

        assert summary["latest_metrics"] == {"stats": {"key": "value"}}
        assert len(summary["recent_alerts"]) == 1

    def test_initialization_rejects_invalid_client_type(self, mocker: MockerFixture) -> None:
        with pytest.raises(TypeError, match="only supports WebTransportClient"):
            ClientMonitor(client=mocker.MagicMock())

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "attempted, successful",
        [
            (5, 2),
            (15, 14),
        ],
    )
    async def test_low_success_rate_alert_not_triggered(
        self,
        monitor: ClientMonitor,
        mock_client: WebTransportClient,
        attempted: int,
        successful: int,
    ) -> None:
        stats = ClientStats(created_at=0)
        stats.connections_attempted = attempted
        stats.connections_successful = successful
        diagnostics = ClientDiagnostics(stats=stats, connection_states={})
        cast(AsyncMock, mock_client.diagnostics).return_value = diagnostics

        await monitor._collect_metrics()
        monitor._check_for_alerts()
        assert not monitor._alerts

    @pytest.mark.asyncio
    async def test_low_success_rate_alert_triggered(
        self, monitor: ClientMonitor, mock_client: WebTransportClient, mocker: MockerFixture
    ) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.client.logger.warning")
        stats = ClientStats(created_at=0)
        stats.connections_attempted = 20
        stats.connections_successful = 16
        diagnostics = ClientDiagnostics(stats=stats, connection_states={})
        cast(AsyncMock, mock_client.diagnostics).return_value = diagnostics

        await monitor._collect_metrics()
        monitor._check_for_alerts()
        assert len(monitor._alerts) == 1
        assert monitor._alerts[0]["type"] == "low_success_rate"
        logger_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_slow_connections_alert_not_triggered(
        self, monitor: ClientMonitor, mock_client: WebTransportClient, mocker: MockerFixture
    ) -> None:
        stats = ClientStats(created_at=0)
        stats.total_connect_time = 9.8
        stats.connections_successful = 2
        diagnostics = ClientDiagnostics(stats=stats, connection_states={})
        cast(AsyncMock, mock_client.diagnostics).return_value = diagnostics
        mocker.patch.object(ClientStats, "avg_connect_time", new_callable=PropertyMock, return_value=4.9)

        await monitor._collect_metrics()
        monitor._check_for_alerts()
        assert not monitor._alerts

    @pytest.mark.asyncio
    async def test_slow_connections_alert_triggered(
        self, monitor: ClientMonitor, mock_client: WebTransportClient, mocker: MockerFixture
    ) -> None:
        stats = ClientStats(created_at=0)
        stats.total_connect_time = 13.0
        stats.connections_successful = 2
        diagnostics = ClientDiagnostics(stats=stats, connection_states={})
        cast(AsyncMock, mock_client.diagnostics).return_value = diagnostics
        mocker.patch.object(ClientStats, "avg_connect_time", new_callable=PropertyMock, return_value=6.5)

        await monitor._collect_metrics()
        monitor._check_for_alerts()
        assert len(monitor._alerts) == 1
        assert monitor._alerts[0]["type"] == "slow_connections"
