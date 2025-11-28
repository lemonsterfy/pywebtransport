"""Unit tests for the pywebtransport.monitor.connection module."""

from dataclasses import dataclass
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.monitor.connection import ConnectionMonitor
from pywebtransport.types import ConnectionState


@dataclass
class MockConnectionDiagnostics:
    state: str
    session_count: int
    recv_throughput: float = 0.0
    send_throughput: float = 0.0
    rtt: float = 0.0


class TestConnectionMonitor:
    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture) -> WebTransportConnection:
        connection = mocker.create_autospec(WebTransportConnection, instance=True)
        diagnostics_data = MockConnectionDiagnostics(state=ConnectionState.CONNECTED.value, session_count=10)
        connection.diagnostics = AsyncMock(return_value=diagnostics_data)
        return connection

    @pytest.fixture
    def monitor(self, mock_connection: WebTransportConnection) -> ConnectionMonitor:
        return ConnectionMonitor(connection=mock_connection)

    def test_check_for_alerts_deduplication(self, monitor: ConnectionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.connection.logger.warning")

        metrics_unhealthy = {"state": ConnectionState.CLOSED.value, "session_count": 10, "timestamp": 12345.0}
        monitor._metrics_history.append(metrics_unhealthy)

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        logger_mock.assert_called_once()

        logger_mock.reset_mock()
        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        logger_mock.assert_not_called()

    def test_check_for_alerts_healthy(self, monitor: ConnectionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.connection.logger.warning")
        metrics = {"state": ConnectionState.CONNECTED.value, "session_count": 100, "timestamp": 12345.0}
        monitor._metrics_history.append(metrics)

        monitor._check_for_alerts()

        assert not monitor._alerts
        logger_mock.assert_not_called()

    def test_check_for_alerts_high_session_count(self, monitor: ConnectionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.connection.logger.warning")
        metrics = {"state": ConnectionState.CONNECTED.value, "session_count": 1500, "timestamp": 12345.0}
        monitor._metrics_history.append(metrics)

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        alert = monitor._alerts[0]
        assert alert["type"] == "high_session_count"
        assert "1500" in alert["message"]
        logger_mock.assert_called_once()

    def test_check_for_alerts_no_metrics(self, monitor: ConnectionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.connection.logger.warning")

        monitor._check_for_alerts()

        assert not monitor._alerts
        logger_mock.assert_not_called()

    def test_check_for_alerts_unhealthy_state(self, monitor: ConnectionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.connection.logger.warning")
        metrics = {"state": ConnectionState.FAILED.value, "session_count": 0, "timestamp": 12345.0}
        monitor._metrics_history.append(metrics)

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        alert = monitor._alerts[0]
        assert alert["type"] == "connection_not_healthy"
        logger_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_metrics_failure(
        self, monitor: ConnectionMonitor, mock_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        cast(AsyncMock, mock_connection.diagnostics).side_effect = ValueError("Diagnostics error")
        logger_mock = mocker.patch("pywebtransport.monitor.connection.logger.error")

        await monitor._collect_metrics()

        assert not monitor._metrics_history
        logger_mock.assert_called_once_with("Connection metrics collection failed: %s", mocker.ANY, exc_info=True)

    @pytest.mark.asyncio
    async def test_collect_metrics_success(
        self, monitor: ConnectionMonitor, mock_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.monitor.connection.get_timestamp", return_value=1600000000.0)

        await monitor._collect_metrics()

        assert len(monitor._metrics_history) == 1
        metrics = monitor._metrics_history[0]
        assert metrics["timestamp"] == 1600000000.0
        assert metrics["state"] == ConnectionState.CONNECTED.value
        assert metrics["session_count"] == 10
        cast(AsyncMock, mock_connection.diagnostics).assert_awaited_once()

    def test_get_current_metrics(self, monitor: ConnectionMonitor) -> None:
        assert monitor.get_current_metrics() is None

        metrics = {"state": "test", "timestamp": 123.0}
        monitor._metrics_history.append(metrics)

        assert monitor.get_current_metrics() == metrics

    def test_init(self, monitor: ConnectionMonitor, mock_connection: WebTransportConnection) -> None:
        assert monitor._target is mock_connection
