"""Utility for monitoring client health."""

from __future__ import annotations

from typing import Any

from pywebtransport.client.client import WebTransportClient
from pywebtransport.monitor._base import _BaseMonitor
from pywebtransport.utils import get_logger, get_timestamp

__all__: list[str] = ["ClientMonitor"]

logger = get_logger(name=__name__)


class ClientMonitor(_BaseMonitor[WebTransportClient]):
    """Monitor client performance and health via an async context."""

    def __init__(self, client: WebTransportClient, *, monitoring_interval: float = 30.0) -> None:
        """Initialize the client monitor."""
        if not isinstance(client, WebTransportClient):
            raise TypeError(
                "ClientMonitor only supports WebTransportClient instances, "
                "not other client-like objects such as ReconnectingClient."
            )

        super().__init__(target=client, monitoring_interval=monitoring_interval)

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a summary of the latest metrics and recent alerts."""
        return {
            "latest_metrics": self._metrics_history[-1] if self._metrics_history else {},
            "recent_alerts": list(self._alerts),
            "is_monitoring": self.is_monitoring,
        }

    def _check_for_alerts(self) -> None:
        """Analyze the latest metrics and generate alerts if thresholds are breached."""
        metrics: dict[str, Any] | None = self._metrics_history[-1] if self._metrics_history else None
        if not metrics or not isinstance(metrics.get("stats"), dict):
            return

        stats = metrics["stats"]
        connections_stats = stats.get("connections", {})
        performance_stats = stats.get("performance", {})

        success_rate = connections_stats.get("success_rate", 1.0)
        if connections_stats.get("attempted", 0) > 10 and success_rate < 0.9:
            self._create_alert(
                alert_type="low_success_rate",
                message=f"Low connection success rate: {success_rate:.2%}",
            )

        avg_connect_time = performance_stats.get("avg_connect_time", 0.0)
        if avg_connect_time > 5.0:
            self._create_alert(
                alert_type="slow_connections",
                message=f"Slow connections: {avg_connect_time:.2f}s average",
            )

    async def _collect_metrics(self) -> None:
        """Collect a snapshot of the client's current statistics."""
        try:
            timestamp = get_timestamp()
            diagnostics = await self._target.diagnostics()
            stats = diagnostics.stats.to_dict()
            metrics = {"timestamp": timestamp, "stats": stats}

            self._metrics_history.append(metrics)
        except Exception as e:
            logger.error("Metrics collection failed: %s", e, exc_info=True)

    def _create_alert(self, *, alert_type: str, message: str) -> None:
        """Create and store a new alert, avoiding duplicates."""
        if not self._alerts or self._alerts[-1].get("message") != message:
            alert = {
                "type": alert_type,
                "message": message,
                "timestamp": get_timestamp(),
            }
            self._alerts.append(alert)
            logger.warning("Client Health Alert: %s", message)
