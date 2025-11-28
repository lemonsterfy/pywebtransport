"""Unit tests for the pywebtransport.monitor.server module."""

from typing import Any, cast
from unittest.mock import AsyncMock, PropertyMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport.monitor import ServerMonitor
from pywebtransport.server import ServerDiagnostics, ServerStats, WebTransportServer
from pywebtransport.types import ConnectionState


class TestServerMonitor:
    @pytest.fixture
    def monitor(self, mock_server: WebTransportServer) -> ServerMonitor:
        return ServerMonitor(server=mock_server)

    @pytest.fixture
    def mock_server(self, mocker: MockerFixture) -> WebTransportServer:
        server = mocker.create_autospec(WebTransportServer, instance=True)
        type(server).is_serving = PropertyMock(return_value=True)

        stats = ServerStats(connections_accepted=0, connections_rejected=0)
        diagnostics = ServerDiagnostics(
            stats=stats,
            connection_states={ConnectionState.CONNECTED: 0},
            session_states={},
            is_serving=True,
            certfile_path="",
            keyfile_path="",
            max_connections=100,
        )
        server.diagnostics = AsyncMock(return_value=diagnostics)
        return server

    def test_check_for_alerts_deduplication(self, monitor: ServerMonitor, mocker: MockerFixture) -> None:
        alert = {"reason": "Test reason"}
        monitor._alerts.append(alert)
        mocker.patch.object(monitor, "get_health_status", return_value={"status": "degraded", "reason": "Test reason"})

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1

    def test_check_for_alerts_failure(self, monitor: ServerMonitor, mocker: MockerFixture) -> None:
        mocker.patch.object(monitor, "get_health_status", side_effect=ValueError)
        logger_mock = mocker.patch("pywebtransport.monitor.server.logger.error")

        monitor._check_for_alerts()

        logger_mock.assert_called_once()

    def test_check_for_alerts_no_trigger(self, monitor: ServerMonitor, mocker: MockerFixture) -> None:
        mocker.patch.object(monitor, "get_health_status", return_value={"status": "healthy", "reason": "OK"})

        monitor._check_for_alerts()

        assert not monitor._alerts

    def test_check_for_alerts_trigger(self, monitor: ServerMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.server.logger.warning")
        mocker.patch.object(monitor, "get_health_status", return_value={"status": "degraded", "reason": "Test reason"})

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        assert monitor._alerts[0]["reason"] == "Test reason"
        logger_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_metrics_failure(self, monitor: ServerMonitor, mocker: MockerFixture) -> None:
        stats_mock = monitor._target.diagnostics
        cast(AsyncMock, stats_mock).side_effect = ValueError
        logger_mock = mocker.patch("pywebtransport.monitor.server.logger.error")

        await monitor._collect_metrics()

        assert not monitor._metrics_history
        logger_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_metrics_success(self, monitor: ServerMonitor, mock_server: WebTransportServer) -> None:
        await monitor._collect_metrics()

        assert len(monitor._metrics_history) == 1
        metrics = monitor._metrics_history[0]
        assert "timestamp" in metrics
        assert "stats" in metrics
        assert "connection_states" in metrics
        assert metrics["stats"]["connections_accepted"] == 0
        cast(AsyncMock, mock_server.diagnostics).assert_awaited_once()

    def test_get_current_metrics(self, monitor: ServerMonitor) -> None:
        assert monitor.get_current_metrics() is None

        monitor._metrics_history.append({"test": "data"})

        assert monitor.get_current_metrics() == {"test": "data"}

    @pytest.mark.parametrize(
        "metrics, is_serving, expected_status, expected_reason",
        [
            (None, True, "unknown", "No metrics collected yet."),
            ({}, False, "unhealthy", "Server is not serving."),
            ({}, True, "idle", "no active connections"),
            (
                {"stats": {"connections_accepted": 8, "connections_rejected": 3}},
                True,
                "degraded",
                "Low connection success rate",
            ),
            ({"stats": {"connections_accepted": 10, "connections_rejected": 1}}, True, "idle", "no active connections"),
            (
                {
                    "stats": {"connections_accepted": 10, "connections_rejected": 1},
                    "connection_states": {ConnectionState.CONNECTED.value: 5},
                },
                True,
                "healthy",
                "operating normally",
            ),
            (
                {"stats": {"connections_accepted": 5, "connections_rejected": 1}, "connection_states": {}},
                True,
                "idle",
                "no active connections",
            ),
        ],
    )
    def test_get_health_status(
        self,
        monitor: ServerMonitor,
        mock_server: WebTransportServer,
        mocker: MockerFixture,
        metrics: dict[str, Any] | None,
        is_serving: bool,
        expected_status: str,
        expected_reason: str,
    ) -> None:
        if metrics is not None:
            monitor._metrics_history.append(metrics)
        mocker.patch.object(type(mock_server), "is_serving", new_callable=PropertyMock, return_value=is_serving)

        status = monitor.get_health_status()

        assert status["status"] == expected_status
        assert expected_reason in status["reason"]
