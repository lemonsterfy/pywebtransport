"""Generic base class for monitoring components."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable
from types import TracebackType
from typing import Any, Generic, Self, TypeVar

from pywebtransport.utils import get_logger

__all__: list[str] = []

logger = get_logger(name=__name__)

T = TypeVar("T")


class _BaseMonitor(ABC, Generic[T]):
    """Implement asynchronous monitoring component base class."""

    def __init__(
        self,
        target: T,
        *,
        monitoring_interval: float = 30.0,
        metrics_maxlen: int = 120,
        alerts_maxlen: int = 100,
    ) -> None:
        """Initialize the base monitor."""
        self._target = target
        self._interval = monitoring_interval
        self._monitor_task: asyncio.Task[None] | None = None
        self._metrics_history: deque[dict[str, Any]] = deque(maxlen=metrics_maxlen)
        self._alerts: deque[dict[str, Any]] = deque(maxlen=alerts_maxlen)

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
            logger.info("%s monitoring started.", self.__class__.__name__)
        except RuntimeError:
            logger.error("Failed to start %s: No running event loop.", self.__class__.__name__, exc_info=True)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
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
        logger.info("%s monitoring stopped.", self.__class__.__name__)

    def clear_history(self) -> None:
        """Clear all collected metrics and alerts history."""
        self._metrics_history.clear()
        self._alerts.clear()
        logger.info("Metrics and alerts history cleared for %s.", self.__class__.__name__)

    def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """Get a list of recently generated alerts."""
        return list(self._alerts)[-limit:]

    def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Get a list of recent metrics history."""
        return list(self._metrics_history)[-limit:]

    @abstractmethod
    def _check_for_alerts(self) -> None | Awaitable[None]:
        """Analyze metrics and generate alerts if thresholds are breached."""
        raise NotImplementedError

    @abstractmethod
    def _collect_metrics(self) -> None | Awaitable[None]:
        """Collect a snapshot of the target's current statistics."""
        raise NotImplementedError

    async def _monitor_loop(self) -> None:
        """Run the main loop for periodically collecting metrics and checking health."""
        try:
            await asyncio.sleep(0)
            while True:
                collection_result = self._collect_metrics()
                if asyncio.iscoroutine(collection_result):
                    await collection_result

                alert_check_result = self._check_for_alerts()
                if asyncio.iscoroutine(alert_check_result):
                    await alert_check_result

                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("%s loop has been cancelled.", self.__class__.__name__)
        except Exception as e:
            logger.error("%s loop encountered a critical error: %s", self.__class__.__name__, e, exc_info=True)
