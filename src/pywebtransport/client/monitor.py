"""
WebTransport Client Monitor.
"""

from __future__ import annotations

import asyncio
from collections import deque
from types import TracebackType
from typing import Any, Self, Type

from pywebtransport.client.client import WebTransportClient
from pywebtransport.utils import get_logger, get_timestamp

__all__ = ["ClientMonitor"]

logger = get_logger("client.monitor")


class ClientMonitor:
    """Monitors client performance and health via an async context."""

    def __init__(self, client: WebTransportClient, *, monitoring_interval: float = 30.0):
        """Initialize the client monitor."""
        self._client = client
        self._interval = monitoring_interval
        self._monitor_task: asyncio.Task[None] | None = None
        self._metrics_history: deque[dict[str, Any]] = deque(maxlen=120)
        self._alerts: deque[dict[str, Any]] = deque(maxlen=100)

    @classmethod
    def create(cls, client: WebTransportClient, *, monitoring_interval: float = 30.0) -> Self:
        """Factory method to create a new client monitor instance."""
        return cls(client, monitoring_interval=monitoring_interval)

    @property
    def is_monitoring(self) -> bool:
        """Check if the monitoring task is currently active."""
        return self._monitor_task is not None and not self._monitor_task.done()

    async def __aenter__(self) -> Self:
        """Enter the async context and start the monitoring task."""
        if not self.is_monitoring:
            try:
                self._monitor_task = asyncio.create_task(self._monitor_loop())
                logger.info("Client monitoring started.")
            except RuntimeError:
                logger.error("Failed to start client monitor: No running event loop.")
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
        logger.info("Client monitoring stopped.")

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a summary of the latest metrics and recent alerts."""
        return {
            "latest_metrics": self._metrics_history[-1] if self._metrics_history else {},
            "recent_alerts": list(self._alerts),
            "is_monitoring": self.is_monitoring,
        }

    async def _monitor_loop(self) -> None:
        """Run the main loop for periodically collecting metrics and checking for alerts."""
        try:
            while not self._client.is_closed:
                self._collect_metrics()
                self._check_alerts()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("Client monitor loop has been cancelled.")
        except Exception as e:
            logger.error(f"Client monitor loop encountered a critical error: {e}", exc_info=e)

    def _collect_metrics(self) -> None:
        """Collect a snapshot of the client's current statistics."""
        try:
            timestamp = get_timestamp()
            stats = self._client.stats
            metrics = {"timestamp": timestamp, "stats": stats}
            self._metrics_history.append(metrics)
        except Exception as e:
            logger.error(f"Metrics collection failed: {e}")

    def _check_alerts(self) -> None:
        """Analyze the latest metrics and generate alerts if thresholds are breached."""
        metrics: dict[str, Any] | None = self._metrics_history[-1] if self._metrics_history else None
        if not metrics or not isinstance(metrics.get("stats"), dict):
            return

        stats = metrics["stats"]
        connections_stats = stats.get("connections", {})
        performance_stats = stats.get("performance", {})

        success_rate = connections_stats.get("success_rate", 1.0)
        if connections_stats.get("attempted", 0) > 10 and success_rate < 0.9:
            self._create_alert("low_success_rate", f"Low connection success rate: {success_rate:.2%}")

        avg_connect_time = performance_stats.get("avg_connect_time", 0.0)
        if avg_connect_time > 5.0:
            self._create_alert("slow_connections", f"Slow connections: {avg_connect_time:.2f}s average")

    def _create_alert(self, alert_type: str, message: str) -> None:
        """Create and store a new alert, avoiding duplicates."""
        if not self._alerts or self._alerts[-1].get("message") != message:
            alert = {"type": alert_type, "message": message, "timestamp": get_timestamp()}
            self._alerts.append(alert)
            logger.warning(f"Client Health Alert: {message}")
