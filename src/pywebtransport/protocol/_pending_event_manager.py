"""Manager for pending protocol events."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from pywebtransport.constants import ErrorCodes
from pywebtransport.protocol.events import H3Event, WebTransportStreamDataReceived
from pywebtransport.types import StreamId
from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.config import ClientConfig, ServerConfig


__all__: list[str] = []

logger = get_logger(name=__name__)


class _PendingEventManager:
    """Buffer and manage events for sessions that are not yet established."""

    def __init__(
        self,
        *,
        config: ClientConfig | ServerConfig,
        abort_stream: Callable[..., None],
        process_buffered_events: Callable[[list[tuple[float, H3Event]]], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize the pending event manager."""
        self._config = config
        self._abort_stream = abort_stream
        self._process_buffered_events = process_buffered_events

        self._pending_events: defaultdict[StreamId, list[tuple[float, H3Event]]] = defaultdict(list)
        self._pending_events_count: int = 0
        self._cleanup_pending_events_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        """Close the manager and clean up its resources."""
        if self._cleanup_pending_events_task:
            self._cleanup_pending_events_task.cancel()
            try:
                await self._cleanup_pending_events_task
            except asyncio.CancelledError:
                pass

    def start(self) -> None:
        """Start the background task for cleaning up stale events."""
        if self._config.pending_event_ttl > 0:
            self._cleanup_pending_events_task = asyncio.create_task(self._cleanup_pending_events_loop())

    def buffer_event(self, *, session_stream_id: StreamId, event: H3Event) -> bool:
        """Buffer an event if buffering is enabled and limits are not exceeded."""
        if self._config.pending_event_ttl <= 0:
            return False

        if self._pending_events_count >= self._config.max_total_pending_events:
            logger.warning("Global pending event buffer full (%d), rejecting event.", self._pending_events_count)
            if isinstance(event, WebTransportStreamDataReceived):
                self._abort_stream(stream_id=event.stream_id, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)
            return False

        if len(self._pending_events.get(session_stream_id, [])) >= self._config.max_pending_events_per_session:
            logger.warning(
                "Pending event buffer full for session stream %d, rejecting event.",
                session_stream_id,
            )
            if isinstance(event, WebTransportStreamDataReceived):
                self._abort_stream(stream_id=event.stream_id, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)
            return False

        logger.debug("Buffering event for unknown session stream %d", session_stream_id)
        self._pending_events[session_stream_id].append((get_timestamp(), event))
        self._pending_events_count += 1
        return True

    def process_pending_events(self, *, connect_stream_id: StreamId) -> None:
        """Check for and process any buffered events for a newly established session."""
        if events_to_process := self._pending_events.pop(connect_stream_id, None):
            self._pending_events_count -= len(events_to_process)
            logger.debug(
                "Processing %d buffered events for session stream %d", len(events_to_process), connect_stream_id
            )
            asyncio.create_task(self._process_buffered_events(events_to_process))

    async def _cleanup_pending_events_loop(self) -> None:
        """Periodically clean up stale pending events."""
        try:
            while True:
                now = get_timestamp()
                expired_keys = [
                    key
                    for key, events in self._pending_events.items()
                    if events and (now - events[0][0]) > self._config.pending_event_ttl
                ]

                for session_stream_id in expired_keys:
                    events_to_discard = self._pending_events.pop(session_stream_id, [])
                    self._pending_events_count -= len(events_to_discard)
                    logger.warning(
                        "Discarding %d expired pending events for unknown session stream %d",
                        len(events_to_discard),
                        session_stream_id,
                    )
                    for _, event in events_to_discard:
                        if isinstance(event, WebTransportStreamDataReceived):
                            self._abort_stream(
                                stream_id=event.stream_id, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED
                            )
                await asyncio.sleep(self._config.pending_event_ttl)
        except asyncio.CancelledError:
            pass
