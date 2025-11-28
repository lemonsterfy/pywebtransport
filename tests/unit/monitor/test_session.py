"""Unit tests for the pywebtransport.monitor.session module."""

from dataclasses import dataclass, field
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport.monitor.session import SessionMonitor
from pywebtransport.session.session import WebTransportSession
from pywebtransport.types import SessionState


@dataclass
class MockSessionDiagnostics:
    state: str
    pending_bidi_stream_futures: list[str] = field(default_factory=list)
    datagram_queue_size: int = 0


class TestSessionMonitor:
    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> WebTransportSession:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        diagnostics_data = MockSessionDiagnostics(state=SessionState.CONNECTED.value, pending_bidi_stream_futures=[])
        session.diagnostics = AsyncMock(return_value=diagnostics_data)
        return session

    @pytest.fixture
    def monitor(self, mock_session: WebTransportSession) -> SessionMonitor:
        return SessionMonitor(session=mock_session)

    def test_check_for_alerts_deduplication(self, monitor: SessionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.session.logger.warning")

        metrics_unhealthy = {"state": SessionState.CLOSED.value, "timestamp": 12345.0}
        monitor._metrics_history.append(metrics_unhealthy)

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        logger_mock.assert_called_once()

        logger_mock.reset_mock()
        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        logger_mock.assert_not_called()

    def test_check_for_alerts_healthy(self, monitor: SessionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.session.logger.warning")
        metrics = {"state": SessionState.CONNECTED.value, "pending_bidi_stream_futures": [], "timestamp": 12345.0}
        monitor._metrics_history.append(metrics)

        monitor._check_for_alerts()

        assert not monitor._alerts
        logger_mock.assert_not_called()

    def test_check_for_alerts_high_stream_contention(self, monitor: SessionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.session.logger.warning")
        metrics = {
            "state": SessionState.CONNECTED.value,
            "pending_bidi_stream_futures": ["stream_1"] * 15,
            "timestamp": 12345.0,
        }
        monitor._metrics_history.append(metrics)

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        alert = monitor._alerts[0]
        assert alert["type"] == "high_stream_contention"
        assert "15 pending" in alert["message"]
        logger_mock.assert_called_once()

    def test_check_for_alerts_no_metrics(self, monitor: SessionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.session.logger.warning")

        monitor._check_for_alerts()

        assert not monitor._alerts
        logger_mock.assert_not_called()

    def test_check_for_alerts_unhealthy_state(self, monitor: SessionMonitor, mocker: MockerFixture) -> None:
        logger_mock = mocker.patch("pywebtransport.monitor.session.logger.warning")
        metrics = {"state": SessionState.CLOSED.value, "pending_bidi_stream_futures": [], "timestamp": 12345.0}
        monitor._metrics_history.append(metrics)

        monitor._check_for_alerts()

        assert len(monitor._alerts) == 1
        alert = monitor._alerts[0]
        assert alert["type"] == "session_not_healthy"
        logger_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_metrics_failure(
        self, monitor: SessionMonitor, mock_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        cast(AsyncMock, mock_session.diagnostics).side_effect = ValueError("Diagnostics error")
        logger_mock = mocker.patch("pywebtransport.monitor.session.logger.error")

        await monitor._collect_metrics()

        assert not monitor._metrics_history
        logger_mock.assert_called_once_with("Session metrics collection failed: %s", mocker.ANY, exc_info=True)

    @pytest.mark.asyncio
    async def test_collect_metrics_success(
        self, monitor: SessionMonitor, mock_session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.monitor.session.get_timestamp", return_value=1600000000.0)

        await monitor._collect_metrics()

        assert len(monitor._metrics_history) == 1
        metrics = monitor._metrics_history[0]
        assert metrics["timestamp"] == 1600000000.0
        assert metrics["state"] == SessionState.CONNECTED.value
        assert metrics["pending_bidi_stream_futures"] == []
        cast(AsyncMock, mock_session.diagnostics).assert_awaited_once()

    def test_get_current_metrics(self, monitor: SessionMonitor) -> None:
        assert monitor.get_current_metrics() is None

        metrics = {"state": "test", "timestamp": 123.0}
        monitor._metrics_history.append(metrics)

        assert monitor.get_current_metrics() == metrics

    def test_init(self, monitor: SessionMonitor, mock_session: WebTransportSession) -> None:
        assert monitor._target is mock_session
