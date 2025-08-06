"""
WebTransport Server Monitor.
"""

from __future__ import annotations

import asyncio
from collections import deque
from types import TracebackType
from typing import Any, Self, Type

from pywebtransport.server.server import WebTransportServer
from pywebtransport.utils import get_logger, get_timestamp

__all__ = ["ServerMonitor"]

logger = get_logger("server.monitor")


class ServerMonitor:
    """Monitors server performance and health via an async context."""

    def __init__(self, server: WebTransportServer, *, monitoring_interval: float = 30.0):
        """Initialize the server monitor."""
        self._server = server
        self._interval = monitoring_interval
        self._monitor_task: asyncio.Task[None] | None = None
        self._metrics_history: deque[dict[str, Any]] = deque(maxlen=120)
        self._alerts: deque[dict[str, Any]] = deque(maxlen=100)

    @classmethod
    def create(cls, server: WebTransportServer, *, monitoring_interval: float = 30.0) -> Self:
        """Factory method to create a new server monitor instance."""
        return cls(server, monitoring_interval=monitoring_interval)

    @property
    def is_monitoring(self) -> bool:
        """Check if the monitoring task is currently active."""
        return self._monitor_task is not None and not self._monitor_task.done()

    async def __aenter__(self) -> Self:
        """Enter the async context and start the monitoring task."""
        if self.is_monitoring:
            return self
        try:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Server monitoring started.")
        except RuntimeError:
            logger.error("Failed to start server monitor: No running event loop.")
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and stop the monitoring task."""
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Server monitoring stopped.")

    def get_health_status(self) -> dict[str, Any]:
        """Get the current server health status based on the latest metrics."""
        metrics = self.get_current_metrics()
        if not metrics:
            return {"status": "unknown", "reason": "No metrics collected yet."}

        stats = metrics.get("stats", {})
        if not self._server.is_serving:
            return {"status": "unhealthy", "reason": "Server is not serving."}

        connections = stats.get("connections", {})
        accepted = stats.get("connections_accepted", 0)
        rejected = stats.get("connections_rejected", 0)
        total_attempts = accepted + rejected

        if total_attempts > 10:
            success_rate = accepted / total_attempts if total_attempts > 0 else 1.0
            if success_rate < 0.9:
                return {"status": "degraded", "reason": f"Low connection success rate: {success_rate:.2%}"}

        if connections.get("active", 0) > 0:
            return {"status": "healthy", "reason": "Server is operating normally."}

        return {"status": "idle", "reason": "Server is running but has no active connections."}

    def get_alerts(self, limit: int = 25) -> list[dict[str, Any]]:
        """Get a list of recently generated alerts."""
        return list(self._alerts)[-limit:]

    def get_current_metrics(self) -> dict[str, Any] | None:
        """Get the latest collected metrics."""
        return self._metrics_history[-1] if self._metrics_history else None

    def get_metrics_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get a list of recent metrics history."""
        return list(self._metrics_history)[-limit:]

    def clear_history(self) -> None:
        """Clear all collected metrics and alerts history."""
        self._metrics_history.clear()
        self._alerts.clear()
        logger.info("Metrics and alerts history cleared.")

    async def _monitor_loop(self) -> None:
        """Run the main loop for periodically collecting metrics and checking health."""
        try:
            while True:
                await self._collect_metrics()
                await self._check_for_alerts()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("Server monitor loop has been cancelled.")
        except Exception as e:
            logger.error(f"Server monitor loop encountered a critical error: {e}", exc_info=e)

    async def _collect_metrics(self) -> None:
        """Collect a snapshot of the server's current statistics."""
        try:
            timestamp = get_timestamp()
            stats = await self._server.get_server_stats()
            metrics = {"timestamp": timestamp, "stats": stats}
            self._metrics_history.append(metrics)
        except Exception as e:
            logger.error(f"Metrics collection failed: {e}")

    async def _check_for_alerts(self) -> None:
        """Analyze the latest metrics and generate alerts if thresholds are breached."""
        try:
            health = self.get_health_status()
            if health["status"] in ("unhealthy", "degraded"):
                if not self._alerts or self._alerts[-1].get("reason") != health["reason"]:
                    alert = {"timestamp": get_timestamp(), "status": health["status"], "reason": health["reason"]}
                    self._alerts.append(alert)
                    logger.warning(f"Health Alert: {health['status']} - {health['reason']}")
        except Exception as e:
            logger.error(f"Alert check failed: {e}")
