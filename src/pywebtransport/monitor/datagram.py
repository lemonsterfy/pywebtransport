"""Utility for monitoring datagram transport health."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pywebtransport.monitor._base import _BaseMonitor
from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.datagram.transport import WebTransportDatagramTransport


__all__: list[str] = ["DatagramMonitor"]

logger = get_logger(name=__name__)


class DatagramMonitor(_BaseMonitor["WebTransportDatagramTransport"]):
    """Monitor datagram transport performance and generate alerts."""

    def __init__(
        self,
        datagram_transport: WebTransportDatagramTransport,
        *,
        monitoring_interval: float = 5.0,
        samples_maxlen: int = 100,
        alerts_maxlen: int = 50,
        queue_size_threshold: float = 0.9,
        success_rate_threshold: float = 0.8,
        trend_analysis_window: int = 10,
    ) -> None:
        """Initialize the datagram performance monitor."""
        super().__init__(
            target=datagram_transport,
            monitoring_interval=monitoring_interval,
            metrics_maxlen=samples_maxlen,
            alerts_maxlen=alerts_maxlen,
        )
        self._queue_size_threshold = queue_size_threshold
        self._success_rate_threshold = success_rate_threshold
        self._trend_analysis_window = trend_analysis_window

    def get_samples(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Get a copy of the collected performance samples."""
        samples_list = list(self._metrics_history)
        if limit is not None:
            if limit == 0:
                return []
            return samples_list[-limit:]
        return samples_list

    def _analyze_trend(self, *, values: list[float]) -> str:
        """Perform a simple trend analysis on a series of values."""
        if len(values) < self._trend_analysis_window:
            return "stable"

        first_half = values[: len(values) // 2]
        second_half = values[len(values) // 2 :]

        first_avg = sum(first_half) / len(first_half)
        second_avg = sum(second_half) / len(second_half)

        if first_avg == 0 and second_avg > 0:
            return "increasing"

        if first_avg > 0:
            change = (second_avg - first_avg) / first_avg
            if change > 0.25:
                return "increasing"
            elif change < -0.25:
                return "decreasing"

        return "stable"

    def _check_for_alerts(self) -> None:
        """Check the current sample against configured alert thresholds."""
        if not self._metrics_history:
            return

        current_sample = self._metrics_history[-1]
        if current_sample["outgoing_queue_size"] > self._target.outgoing_high_water_mark * self._queue_size_threshold:
            self._alerts.append(
                {
                    "type": "high_queue_size",
                    "message": f"Outgoing queue size high: {current_sample['outgoing_queue_size']}",
                    "timestamp": current_sample["timestamp"],
                }
            )

        if current_sample["send_success_rate"] < self._success_rate_threshold:
            self._alerts.append(
                {
                    "type": "low_success_rate",
                    "message": f"Low send success rate: {current_sample['send_success_rate']:.2%}",
                    "timestamp": current_sample["timestamp"],
                }
            )

        if len(self._metrics_history) >= self._trend_analysis_window:
            recent_send_times = [s["avg_send_time"] for s in self._metrics_history]
            trend = self._analyze_trend(values=recent_send_times)
            if trend == "increasing":
                self._alerts.append(
                    {
                        "type": "increasing_send_time",
                        "message": f"Average send time is increasing (current: {current_sample['avg_send_time']:.3f}s)",
                        "timestamp": current_sample["timestamp"],
                    }
                )

    def _collect_metrics(self) -> None:
        """Collect a snapshot of the datagram transport's current statistics."""
        try:
            diagnostics = self._target.diagnostics
            stats = diagnostics.stats.to_dict()
            queue_stats = diagnostics.queue_stats
            sample = {
                "timestamp": get_timestamp(),
                "datagrams_sent": stats.get("datagrams_sent", 0),
                "datagrams_received": stats.get("datagrams_received", 0),
                "send_success_rate": stats.get("send_success_rate", 0.0),
                "avg_send_time": stats.get("avg_send_time", 0.0),
                "outgoing_queue_size": queue_stats.get("outgoing", {}).get("size", 0),
            }
            self._metrics_history.append(sample)
        except Exception as e:
            logger.error("Datagram metrics collection failed: %s", e, exc_info=True)
