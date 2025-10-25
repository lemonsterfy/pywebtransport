"""Utility for monitoring server health."""

from __future__ import annotations

from typing import Any

from pywebtransport.monitor._base import _BaseMonitor
from pywebtransport.server.server import WebTransportServer
from pywebtransport.types import ConnectionState
from pywebtransport.utils import get_logger, get_timestamp

__all__: list[str] = ["ServerMonitor"]

logger = get_logger(name=__name__)


class ServerMonitor(_BaseMonitor[WebTransportServer]):
    """Monitor server performance and health via an async context."""

    def __init__(self, server: WebTransportServer, *, monitoring_interval: float = 30.0) -> None:
        """Initialize the server monitor."""
        super().__init__(target=server, monitoring_interval=monitoring_interval)

    def get_current_metrics(self) -> dict[str, Any] | None:
        """Get the latest collected metrics."""
        return self._metrics_history[-1] if self._metrics_history else None

    def get_health_status(self) -> dict[str, Any]:
        """Get the current server health status based on the latest metrics."""
        metrics = self.get_current_metrics()
        if metrics is None:
            return {"status": "unknown", "reason": "No metrics collected yet."}

        stats = metrics.get("stats", {})
        if not self._target.is_serving:
            return {"status": "unhealthy", "reason": "Server is not serving."}

        connections = stats.get("connections", {})
        accepted = stats.get("connections_accepted", 0)
        rejected = stats.get("connections_rejected", 0)
        total_attempts = accepted + rejected

        if total_attempts > 10:
            success_rate = accepted / total_attempts if total_attempts > 0 else 1.0
            if success_rate < 0.9:
                return {
                    "status": "degraded",
                    "reason": f"Low connection success rate: {success_rate:.2%}",
                }

        if connections and connections.get("active", 0) > 0:
            return {"status": "healthy", "reason": "Server is operating normally."}

        return {"status": "idle", "reason": "Server is running but has no active connections."}

    def _check_for_alerts(self) -> None:
        """Analyze the latest metrics and generate alerts if thresholds are breached."""
        try:
            health = self.get_health_status()
            if health["status"] in ("unhealthy", "degraded"):
                if not self._alerts or self._alerts[-1].get("reason") != health["reason"]:
                    alert = {
                        "timestamp": get_timestamp(),
                        "status": health["status"],
                        "reason": health["reason"],
                    }
                    self._alerts.append(alert)
                    logger.warning("Health Alert: %s - %s", health["status"], health["reason"])
        except Exception as e:
            logger.error("Alert check failed: %s", e, exc_info=True)

    async def _collect_metrics(self) -> None:
        """Collect a snapshot of the server's current statistics."""
        try:
            timestamp = get_timestamp()
            diagnostics = await self._target.diagnostics()

            stats = diagnostics.stats.to_dict()
            stats["connections"] = {
                "active": diagnostics.connection_states.get(ConnectionState.CONNECTED, 0),
            }

            metrics = {"timestamp": timestamp, "stats": stats}
            self._metrics_history.append(metrics)
        except Exception as e:
            logger.error("Metrics collection failed: %s", e, exc_info=True)
