"""Utility for monitoring session health."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from pywebtransport.monitor._base import _BaseMonitor
from pywebtransport.session.session import SessionDiagnostics
from pywebtransport.types import SessionState
from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.session.session import WebTransportSession


__all__: list[str] = ["SessionMonitor"]

logger = get_logger(name=__name__)


class SessionMonitor(_BaseMonitor["WebTransportSession"]):
    """Monitor session performance and health via an async context."""

    def __init__(self, session: WebTransportSession, *, monitoring_interval: float = 15.0) -> None:
        """Initialize the session monitor."""
        super().__init__(target=session, monitoring_interval=monitoring_interval)

    def get_current_metrics(self) -> dict[str, Any] | None:
        """Get the latest collected metrics."""
        return self._metrics_history[-1] if self._metrics_history else None

    def _check_for_alerts(self) -> None:
        """Analyze the latest metrics and generate alerts if thresholds are breached."""
        metrics: dict[str, Any] | None = self._metrics_history[-1] if self._metrics_history else None
        if not metrics:
            return

        state = metrics.get("state")
        if state not in (SessionState.CONNECTING.value, SessionState.CONNECTED.value, SessionState.DRAINING.value):
            self._create_alert(alert_type="session_not_healthy", message=f"Session state is unhealthy: {state}")

        pending_futures = metrics.get("pending_bidi_stream_futures")
        if pending_futures is not None and len(pending_futures) > 10:
            self._create_alert(
                alert_type="high_stream_contention",
                message=f"High bidirectional stream contention: {len(pending_futures)} pending",
            )

    async def _collect_metrics(self) -> None:
        """Collect a snapshot of the session's current statistics."""
        try:
            timestamp = get_timestamp()
            diagnostics_obj: SessionDiagnostics = await self._target.diagnostics()
            metrics = {"timestamp": timestamp, **asdict(diagnostics_obj)}
            self._metrics_history.append(metrics)
        except Exception as e:
            logger.error("Session metrics collection failed: %s", e, exc_info=True)

    def _create_alert(self, *, alert_type: str, message: str) -> None:
        """Create and store a new alert, avoiding duplicates."""
        if not self._alerts or self._alerts[-1].get("message") != message:
            alert = {"type": alert_type, "message": message, "timestamp": get_timestamp()}
            self._alerts.append(alert)
            logger.warning("Session Health Alert: %s", message)
