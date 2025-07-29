"""Unit tests for the pywebtransport.server.monitor module."""

import asyncio
from collections import deque
from typing import Any, Dict, Optional, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport.server import ServerMonitor, WebTransportServer


class TestServerMonitor:
    @pytest.fixture
    def mock_server(self, mocker: MockerFixture) -> Any:
        return mocker.create_autospec(WebTransportServer, instance=True)

    @pytest.fixture
    def mock_logger(self, mocker: MockerFixture) -> Any:
        return mocker.patch("pywebtransport.server.monitor.logger")

    @pytest.fixture
    def mock_timestamp(self, mocker: MockerFixture) -> Any:
        return mocker.patch("pywebtransport.server.monitor.get_timestamp", return_value=12345.0)

    @pytest.mark.parametrize("interval", [15.0, 60.0])
    def test_initialization(self, mock_server: Any, interval: float) -> None:
        monitor = ServerMonitor(mock_server, monitoring_interval=interval)

        assert monitor._server is mock_server
        assert monitor._interval == interval
        assert monitor._monitor_task is None
        assert isinstance(monitor._metrics_history, deque)
        assert monitor._metrics_history.maxlen == 120
        assert isinstance(monitor._alerts, deque)
        assert monitor._alerts.maxlen == 100

    def test_create_factory_method(self, mock_server: Any) -> None:
        monitor = ServerMonitor.create(mock_server, monitoring_interval=42.0)

        assert isinstance(monitor, ServerMonitor)
        assert monitor._interval == 42.0

    def test_is_monitoring_property(self, mocker: MockerFixture, mock_server: Any) -> None:
        monitor = ServerMonitor(mock_server)
        assert not monitor.is_monitoring

        mock_task = mocker.create_autospec(asyncio.Task, instance=True)
        mock_task.done.return_value = False
        monitor._monitor_task = mock_task
        assert monitor.is_monitoring

        mock_task.done.return_value = True  # type: ignore[unreachable]
        assert not monitor.is_monitoring

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mocker: MockerFixture, mock_server: Any, mock_logger: Any) -> None:
        create_task_spy = mocker.spy(asyncio, "create_task")
        mocker.patch("asyncio.sleep")

        async with ServerMonitor(mock_server) as monitor:
            assert monitor.is_monitoring
            create_task_spy.assert_called_once()
            mock_logger.info.assert_any_call("Server monitoring started.")

        real_task = create_task_spy.spy_return
        assert not monitor.is_monitoring
        assert real_task.cancelled()  # type: ignore[unreachable]
        mock_logger.info.assert_any_call("Server monitoring stopped.")

    @pytest.mark.asyncio
    async def test_context_manager_idempotency(self, mocker: MockerFixture, mock_server: Any) -> None:
        create_task_spy = mocker.spy(asyncio, "create_task")
        mocker.patch("asyncio.sleep")
        monitor = ServerMonitor(mock_server)

        await monitor.__aenter__()
        create_task_spy.assert_called_once()

        await monitor.__aenter__()
        create_task_spy.assert_called_once()

        await monitor.__aexit__(None, None, None)
        real_task = create_task_spy.spy_return
        assert real_task.cancelled()

    @pytest.mark.asyncio
    async def test_aenter_handles_runtime_error(
        self, mock_server: Any, mocker: MockerFixture, mock_logger: Any
    ) -> None:
        mocker.patch.object(ServerMonitor, "_monitor_loop", new=mocker.MagicMock())
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("No running event loop."))
        monitor = ServerMonitor(mock_server)

        await monitor.__aenter__()

        assert not monitor.is_monitoring
        mock_logger.error.assert_called_once_with("Failed to start server monitor: No running event loop.")

    @pytest.mark.asyncio
    async def test_aexit_no_task(self, mock_server: Any, mock_logger: Any) -> None:
        monitor = ServerMonitor(mock_server)
        monitor._monitor_task = None

        await monitor.__aexit__(None, None, None)

        mock_logger.info.assert_called_once_with("Server monitoring stopped.")

    @pytest.mark.asyncio
    async def test_monitor_loop_logic(self, mocker: MockerFixture, mock_server: Any, mock_logger: Any) -> None:
        monitor = ServerMonitor(mock_server, monitoring_interval=0.01)
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mocker.patch.object(monitor, "_collect_metrics", new_callable=mocker.AsyncMock)
        mocker.patch.object(monitor, "_check_for_alerts", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = asyncio.CancelledError

        await monitor._monitor_loop()

        cast(Any, monitor._collect_metrics).assert_awaited_once()
        cast(Any, monitor._check_for_alerts).assert_awaited_once()
        mock_sleep.assert_awaited_once_with(0.01)
        mock_logger.info.assert_called_with("Server monitor loop has been cancelled.")

    @pytest.mark.asyncio
    async def test_monitor_loop_exception_handling(
        self, mocker: MockerFixture, mock_server: Any, mock_logger: Any
    ) -> None:
        monitor = ServerMonitor(mock_server)
        error = RuntimeError("Something went wrong")
        mocker.patch.object(monitor, "_collect_metrics", side_effect=error, new_callable=mocker.AsyncMock)

        await monitor._monitor_loop()

        mock_logger.error.assert_called_once_with(
            f"Server monitor loop encountered a critical error: {error}", exc_info=error
        )

    @pytest.mark.asyncio
    async def test_collect_metrics_success(self, mock_server: Any, mock_timestamp: Any, mocker: MockerFixture) -> None:
        stats_data = {"connections": {"active": 5}}
        mock_server.get_server_stats = mocker.AsyncMock(return_value=stats_data)
        monitor = ServerMonitor(mock_server)

        await monitor._collect_metrics()

        assert len(monitor._metrics_history) == 1
        expected_metric = {"timestamp": 12345.0, "stats": stats_data}
        assert monitor.get_current_metrics() == expected_metric

    @pytest.mark.asyncio
    async def test_collect_metrics_failure(self, mock_server: Any, mock_logger: Any, mocker: MockerFixture) -> None:
        error = Exception("Failed to get stats")
        mock_server.get_server_stats = mocker.AsyncMock(side_effect=error)
        monitor = ServerMonitor(mock_server)

        await monitor._collect_metrics()

        assert len(monitor._metrics_history) == 0
        mock_logger.error.assert_called_once_with(f"Metrics collection failed: {error}")

    @pytest.mark.asyncio
    async def test_check_for_alerts_generation_and_deduplication(
        self, mocker: MockerFixture, mock_server: Any, mock_logger: Any, mock_timestamp: Any
    ) -> None:
        monitor = ServerMonitor(mock_server)
        mock_health_status = mocker.patch.object(monitor, "get_health_status")

        unhealthy_status = {"status": "unhealthy", "reason": "Server is not serving."}
        mock_health_status.return_value = unhealthy_status
        await monitor._check_for_alerts()

        assert len(monitor.get_alerts()) == 1
        assert monitor.get_alerts()[0]["reason"] == "Server is not serving."
        mock_logger.warning.assert_called_once_with("Health Alert: unhealthy - Server is not serving.")

        await monitor._check_for_alerts()
        assert len(monitor.get_alerts()) == 1
        mock_logger.warning.assert_called_once()

        degraded_status = {"status": "degraded", "reason": "Low success rate."}
        mock_health_status.return_value = degraded_status
        await monitor._check_for_alerts()

        assert len(monitor.get_alerts()) == 2
        assert monitor.get_alerts()[1]["reason"] == "Low success rate."
        mock_logger.warning.assert_called_with("Health Alert: degraded - Low success rate.")

    @pytest.mark.asyncio
    async def test_check_for_alerts_handles_exception(
        self, mocker: MockerFixture, mock_server: Any, mock_logger: Any
    ) -> None:
        monitor = ServerMonitor(mock_server)
        error = RuntimeError("Health check failed")
        mocker.patch.object(monitor, "get_health_status", side_effect=error)

        await monitor._check_for_alerts()

        mock_logger.error.assert_called_once_with(f"Alert check failed: {error}")

    @pytest.mark.parametrize(
        "description, metrics, is_serving, expected_status",
        [
            ("No metrics collected yet", None, True, {"status": "unknown", "reason": "No metrics collected yet."}),
            (
                "Server is not serving",
                {"stats": {}},
                False,
                {"status": "unhealthy", "reason": "Server is not serving."},
            ),
            (
                "Healthy with active connections",
                {"stats": {"connections": {"active": 10}}},
                True,
                {"status": "healthy", "reason": "Server is operating normally."},
            ),
            (
                "Idle with no active connections",
                {"stats": {"connections": {"active": 0}}},
                True,
                {"status": "idle", "reason": "Server is running but has no active connections."},
            ),
            (
                "Degraded due to low connection success rate",
                {"stats": {"connections": {"active": 8}, "connections_accepted": 85, "connections_rejected": 15}},
                True,
                {"status": "degraded", "reason": "Low connection success rate: 85.00%"},
            ),
        ],
    )
    def test_get_health_status(
        self,
        mocker: MockerFixture,
        mock_server: Any,
        description: str,
        metrics: Optional[Dict[str, Any]],
        is_serving: bool,
        expected_status: Dict[str, str],
    ) -> None:
        monitor = ServerMonitor(mock_server)
        mocker.patch.object(monitor, "get_current_metrics", return_value=metrics)
        type(mock_server).is_serving = mocker.PropertyMock(return_value=is_serving)

        health = monitor.get_health_status()
        assert health == expected_status

    def test_history_and_alert_retrieval(self, mock_server: Any) -> None:
        monitor = ServerMonitor(mock_server)
        monitor._metrics_history.extend([{"id": i} for i in range(5)])
        monitor._alerts.extend([{"id": i} for i in range(3)])

        assert monitor.get_current_metrics() == {"id": 4}
        assert len(monitor.get_metrics_history(limit=3)) == 3
        assert monitor.get_metrics_history(limit=3)[-1] == {"id": 4}
        assert len(monitor.get_alerts(limit=2)) == 2
        assert monitor.get_alerts(limit=2)[-1] == {"id": 2}

    def test_clear_history(self, mock_server: Any, mock_logger: Any) -> None:
        monitor = ServerMonitor(mock_server)
        monitor._metrics_history.append({"id": 1})
        monitor._alerts.append({"id": 1})

        monitor.clear_history()

        assert len(monitor._metrics_history) == 0
        assert len(monitor._alerts) == 0
        mock_logger.info.assert_called_once_with("Metrics and alerts history cleared.")
