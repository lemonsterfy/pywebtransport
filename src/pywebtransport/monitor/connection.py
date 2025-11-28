"""Utility for monitoring connection health."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pywebtransport.connection.connection import ConnectionDiagnostics
from pywebtransport.monitor._base import _BaseMonitor
from pywebtransport.types import ConnectionState
from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.connection.connection import WebTransportConnection


__all__: list[str] = ["ConnectionMonitor"]

logger = get_logger(name=__name__)


class ConnectionMonitor(_BaseMonitor["WebTransportConnection"]):
    """Monitor connection performance and health via an async context."""

    def __init__(self, connection: WebTransportConnection, *, monitoring_interval: float = 15.0) -> None:
        """Initialize the connection monitor."""
        super().__init__(target=connection, monitoring_interval=monitoring_interval)

    def get_current_metrics(self) -> dict[str, Any] | None:
        """Get the latest collected metrics."""
        return self._metrics_history[-1] if self._metrics_history else None

    def _check_for_alerts(self) -> None:
        """Analyze the latest metrics and generate alerts if thresholds are breached."""
        metrics: dict[str, Any] | None = self._metrics_history[-1] if self._metrics_history else None
        if not metrics:
            return

        state = metrics.get("state")
        if state not in (ConnectionState.CONNECTING.value, ConnectionState.CONNECTED.value):
            self._create_alert(alert_type="connection_not_healthy", message=f"Connection state is unhealthy: {state}")

        session_count = metrics.get("session_count")
        if session_count is not None and session_count > 1000:
            self._create_alert(
                alert_type="high_session_count", message=f"Connection has a high session count: {session_count}"
            )

    async def _collect_metrics(self) -> None:
        """Collect a snapshot of the connection's current statistics."""
        try:
            timestamp = get_timestamp()
            diagnostics_obj: ConnectionDiagnostics = await self._target.diagnostics()
            metrics = {"timestamp": timestamp, **asdict(diagnostics_obj)}
            self._metrics_history.append(metrics)
        except Exception as e:
            logger.error("Connection metrics collection failed: %s", e, exc_info=True)

    def _create_alert(self, *, alert_type: str, message: str) -> None:
        """Create and store a new alert, avoiding duplicates."""
        if not self._alerts or self._alerts[-1].get("message") != message:
            alert = {"type": alert_type, "message": message, "timestamp": get_timestamp()}
            self._alerts.append(alert)
            logger.warning("Connection Health Alert: %s", message)
