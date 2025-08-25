"""
WebTransport Datagram Performance Monitor.
"""

from __future__ import annotations

import asyncio
from collections import deque
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, Type

from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.datagram.transport import WebTransportDatagramDuplexStream


__all__ = ["DatagramMonitor"]

logger = get_logger("datagram.monitor")


class DatagramMonitor:
    """Monitors datagram stream performance and generates alerts."""

    def __init__(
        self,
        datagram_stream: WebTransportDatagramDuplexStream,
        *,
        monitoring_interval: float = 5.0,
        samples_maxlen: int = 100,
        alerts_maxlen: int = 50,
        queue_size_threshold: float = 0.9,
        success_rate_threshold: float = 0.8,
        trend_analysis_window: int = 10,
    ):
        """Initialize the datagram performance monitor."""
        self._stream = datagram_stream
        self._interval = monitoring_interval
        self._monitor_task: asyncio.Task[None] | None = None
        self._samples: deque[dict[str, Any]] = deque(maxlen=samples_maxlen)
        self._alerts: deque[dict[str, Any]] = deque(maxlen=alerts_maxlen)
        self._queue_size_threshold = queue_size_threshold
        self._success_rate_threshold = success_rate_threshold
        self._trend_analysis_window = trend_analysis_window

    @classmethod
    def create(
        cls,
        datagram_stream: WebTransportDatagramDuplexStream,
        *,
        monitoring_interval: float = 5.0,
    ) -> Self:
        """Factory method to create a new datagram monitor for a stream."""
        return cls(datagram_stream, monitoring_interval=monitoring_interval)

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
            logger.info(f"Datagram monitoring started for session {self._stream.session_id[:12]}...")
        except RuntimeError:
            logger.error("Failed to start datagram monitor: No running event loop.")

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
        logger.info(f"Datagram monitoring stopped for session {self._stream.session_id[:12]}...")

    def get_alerts(self) -> list[dict[str, Any]]:
        """Get a copy of the currently active alerts."""
        return list(self._alerts)

    def get_samples(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Get a copy of the collected performance samples."""
        samples_list = list(self._samples)
        if limit is not None:
            return samples_list[-limit:]
        return samples_list

    def _analyze_trend(self, values: list[float]) -> str:
        """Perform a simple trend analysis on a series of values."""
        if len(values) < self._trend_analysis_window:
            return "stable"

        first_half = values[: len(values) // 2]
        second_half = values[len(values) // 2 :]

        if not first_half or not second_half:
            return "stable"

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

    async def _check_alerts(self, current_sample: dict[str, Any]) -> None:
        """Check the current sample against configured alert thresholds."""
        if current_sample["outgoing_queue_size"] > self._stream.outgoing_high_water_mark * self._queue_size_threshold:
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

        if len(self._samples) >= self._trend_analysis_window:
            recent_send_times = [s["avg_send_time"] for s in self._samples]
            trend = self._analyze_trend(recent_send_times)
            if trend == "increasing":
                self._alerts.append(
                    {
                        "type": "increasing_send_time",
                        "message": f"Average send time is increasing (current: {current_sample['avg_send_time']:.3f}s)",
                        "timestamp": current_sample["timestamp"],
                    }
                )

    async def _monitor_loop(self) -> None:
        """The main loop for collecting stats and checking for alerts."""
        try:
            while True:
                await asyncio.sleep(self._interval)
                stats = self._stream.stats
                queue_stats = self._stream.get_queue_stats()

                sample = {
                    "timestamp": get_timestamp(),
                    "datagrams_sent": stats.get("datagrams_sent", 0),
                    "datagrams_received": stats.get("datagrams_received", 0),
                    "send_success_rate": stats.get("send_success_rate", 0.0),
                    "avg_send_time": stats.get("avg_send_time", 0.0),
                    "outgoing_queue_size": queue_stats.get("outgoing", {}).get("size", 0),
                }

                self._samples.append(sample)
                await self._check_alerts(sample)

        except asyncio.CancelledError:
            logger.info("Datagram monitor loop cancelled.")
        except Exception as e:
            logger.error(f"Monitor loop error: {e}", exc_info=e)
