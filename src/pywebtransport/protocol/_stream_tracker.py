"""Protocol stream tracker for WebTransport."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import FlowControlError, ProtocolError
from pywebtransport.protocol import utils as protocol_utils
from pywebtransport.protocol.events import H3Event, WebTransportStreamDataReceived
from pywebtransport.protocol.session_info import StreamInfo
from pywebtransport.types import EventType, SessionId, SessionState, StreamDirection, StreamId, StreamState
from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from aioquic.quic.connection import QuicConnection

    from pywebtransport.protocol._session_tracker import _ProtocolSessionTracker
    from pywebtransport.protocol.h3_engine import WebTransportH3Engine


__all__: list[str] = []

logger = get_logger(name=__name__)


class _ProtocolStreamTracker:
    """Track the state of WebTransport data streams."""

    def __init__(
        self,
        *,
        is_client: bool,
        quic: QuicConnection,
        h3: WebTransportH3Engine,
        stats: dict[str, Any],
        session_tracker: _ProtocolSessionTracker,
        emit_event: Callable[[EventType, Any], Coroutine[Any, Any, None]],
        trigger_transmission: Callable[[], None],
    ) -> None:
        """Initialize the protocol stream tracker."""
        self._is_client = is_client
        self._quic = quic
        self._h3 = h3
        self._stats = stats
        self._session_tracker = session_tracker
        self._emit_event = emit_event
        self._trigger_transmission = trigger_transmission

        self._streams: dict[StreamId, StreamInfo] = {}
        self._data_stream_to_session: dict[StreamId, SessionId] = {}
        self._session_owned_streams: dict[SessionId, set[StreamId]] = defaultdict(set)

    def abort_stream(self, *, stream_id: StreamId, error_code: int) -> None:
        """Abort a stream immediately."""
        if stream_id not in self._quic._streams:
            self._cleanup_stream(stream_id=stream_id)
            return

        stream = self._quic._streams[stream_id]
        logger.info("Aborting stream %d with error code 0x%x", stream_id, error_code)

        protocol_error_code = error_code
        if error_code < 2**32:
            try:
                protocol_error_code = protocol_utils.webtransport_code_to_http_code(app_error_code=error_code)
            except ValueError:
                protocol_error_code = ErrorCodes.INTERNAL_ERROR

        can_send = protocol_utils.can_send_data_on_stream(stream_id=stream_id, is_client=self._is_client)
        can_receive = protocol_utils.can_receive_data_on_stream(stream_id=stream_id, is_client=self._is_client)

        try:
            if can_send and stream.sender._reset_error_code is None:
                self._quic.reset_stream(stream_id=stream_id, error_code=protocol_error_code)
            if can_receive and not stream.receiver.is_finished:
                self._quic.stop_stream(stream_id=stream_id, error_code=protocol_error_code)
        except ValueError as e:
            logger.warning("Failed to abort stream %d at QUIC layer: %s", stream_id, e)

        self._trigger_transmission()
        self._cleanup_stream(stream_id=stream_id)

    def create_webtransport_stream(self, *, session_id: SessionId, is_unidirectional: bool = False) -> StreamId:
        """Create a new WebTransport data stream for a session."""
        session_info = self._session_tracker.get_session_info(session_id=session_id)
        if not session_info or session_info.state != SessionState.CONNECTED:
            raise ProtocolError(message=f"Session {session_id} not found or not ready")

        if is_unidirectional:
            if session_info.local_streams_uni_opened >= session_info.peer_max_streams_uni:
                self._session_tracker._send_blocked_capsule(session_info=session_info, is_unidirectional=True)
                raise FlowControlError(message="Unidirectional stream limit reached for session.")
            session_info.local_streams_uni_opened += 1
        else:
            if session_info.local_streams_bidi_opened >= session_info.peer_max_streams_bidi:
                self._session_tracker._send_blocked_capsule(session_info=session_info, is_unidirectional=False)
                raise FlowControlError(message="Bidirectional stream limit reached for session.")
            session_info.local_streams_bidi_opened += 1

        stream_id = self._h3.create_webtransport_stream(
            control_stream_id=session_info.control_stream_id, is_unidirectional=is_unidirectional
        )
        direction = StreamDirection.SEND_ONLY if is_unidirectional else StreamDirection.BIDIRECTIONAL
        self._register_stream(session_id=session_id, stream_id=stream_id, direction=direction)

        self._trigger_transmission()
        logger.debug("Created WebTransport stream %d (%s)", stream_id, direction)
        return stream_id

    def handle_stream_reset(self, *, stream_id: StreamId) -> None:
        """Handle a reset of a data stream."""
        if stream_id in self._streams:
            self._cleanup_stream(stream_id=stream_id)

    async def handle_webtransport_stream_data(self, *, event: WebTransportStreamDataReceived) -> H3Event | None:
        """Handle data received on a WebTransport data stream."""
        stream_id = event.stream_id
        control_stream_id = event.control_stream_id

        session_id = self._session_tracker.get_session_by_control_stream(stream_id=control_stream_id)
        if not session_id:
            return event

        session_info = self._session_tracker.get_session_info(session_id=session_id)
        if not session_info:
            return event

        session_info.peer_data_sent += len(event.data)

        if stream_id not in self._data_stream_to_session:
            direction = protocol_utils.get_stream_direction_from_id(stream_id=stream_id, is_client=self._is_client)
            self._register_stream(session_id=session_id, stream_id=stream_id, direction=direction)

            if protocol_utils._is_unidirectional_stream(stream_id=stream_id):
                session_info.peer_streams_uni_opened += 1
            else:
                session_info.peer_streams_bidi_opened += 1

            event_data = self._streams[stream_id].to_dict()
            event_data["initial_payload"] = {
                "data": event.data,
                "end_stream": event.stream_ended,
            }
            await self._emit_event(EventType.STREAM_OPENED, event_data)
        else:
            await self._emit_event(
                EventType.STREAM_DATA_RECEIVED,
                {"stream_id": stream_id, "data": event.data, "end_stream": event.stream_ended},
            )

        await self._session_tracker.update_local_flow_control(session_id=session_id)
        return None

    def update_stream_state_on_send_end(self, *, stream_id: StreamId) -> None:
        """Update stream state when its sending side is closed."""
        if not (stream_info := self._streams.get(stream_id)):
            return

        new_state = StreamState.HALF_CLOSED_LOCAL
        if stream_info.state == StreamState.HALF_CLOSED_REMOTE:
            new_state = StreamState.CLOSED
        stream_info.state = new_state
        if new_state == StreamState.CLOSED:
            self._cleanup_stream(stream_id=stream_id)

    def cleanup_streams_for_session_by_id(self, session_id: SessionId) -> None:
        """Clean up all streams owned by a specific session."""
        stream_ids_to_reset = list(self._session_owned_streams.pop(session_id, set()))
        for stream_id in stream_ids_to_reset:
            if stream_id in self._streams:
                self.abort_stream(stream_id=stream_id, error_code=ErrorCodes.WT_SESSION_GONE)

    def _cleanup_stream(self, *, stream_id: StreamId) -> None:
        """Remove a single stream from internal tracking."""
        if self._streams.pop(stream_id, None):
            session_id = self._data_stream_to_session.pop(stream_id, None)
            if session_id and session_id in self._session_owned_streams:
                self._session_owned_streams[session_id].discard(stream_id)
            asyncio.create_task(self._emit_event(EventType.STREAM_CLOSED, {"stream_id": stream_id}))

    def _register_stream(self, *, session_id: SessionId, stream_id: StreamId, direction: StreamDirection) -> StreamInfo:
        """Add a new stream to internal tracking."""
        stream_info = StreamInfo(
            stream_id=stream_id,
            session_id=session_id,
            direction=direction,
            state=StreamState.OPEN,
            created_at=get_timestamp(),
        )
        self._streams[stream_id] = stream_info
        self._data_stream_to_session[stream_id] = session_id
        self._session_owned_streams[session_id].add(stream_id)
        self._stats["streams_created"] += 1
        logger.debug("Registered %s stream %d for session %s", direction, stream_id, session_id)
        return stream_info
