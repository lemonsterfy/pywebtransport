"""Handle stream-level logic for the protocol engine."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from aioquic._buffer import Buffer

from pywebtransport import constants
from pywebtransport._protocol.events import (
    CompleteUserFuture,
    Effect,
    EmitStreamEvent,
    FailUserFuture,
    ResetQuicStream,
    SendH3Capsule,
    SendQuicData,
    StopQuicStream,
    TransportStreamReset,
    UserGetStreamDiagnostics,
    UserResetStream,
    UserSendStreamData,
    UserStopStream,
    UserStreamRead,
    WebTransportStreamDataReceived,
)
from pywebtransport._protocol.state import ProtocolState, SessionStateData, StreamStateData
from pywebtransport._protocol.utils import (
    get_stream_direction_from_id,
    http_code_to_webtransport_code,
    webtransport_code_to_http_code,
)
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import StreamError
from pywebtransport.types import EventType, SessionState, StreamDirection, StreamState
from pywebtransport.utils import ensure_bytes, get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.config import ClientConfig, ServerConfig


__all__: list[str] = []

logger = get_logger(name=__name__)


class StreamProcessor:
    """Process stream-level events and manage state transitions."""

    def __init__(self, *, is_client: bool, config: ClientConfig | ServerConfig) -> None:
        """Initialize the stream processor."""
        self._is_client = is_client
        self._config = config

    def handle_get_stream_diagnostics(self, *, event: UserGetStreamDiagnostics, state: ProtocolState) -> list[Effect]:
        """Handle the UserGetStreamDiagnostics event."""
        stream_data = state.streams.get(event.stream_id)
        if not stream_data:
            return [
                FailUserFuture(
                    future=event.future,
                    exception=StreamError(
                        message=f"Stream {event.stream_id} not found for diagnostics", stream_id=event.stream_id
                    ),
                )
            ]
        # Create a snapshot dict and sanitize buffer data for diagnostics
        data_dict = dataclasses.asdict(stream_data)
        data_dict["read_buffer"] = bytes(0)
        data_dict["read_buffer_size"] = stream_data.read_buffer_size
        return [CompleteUserFuture(future=event.future, value=data_dict)]

    def handle_reset_stream(self, *, event: UserResetStream, state: ProtocolState) -> list[Effect]:
        """Handle the UserResetStream event to reset the sending side."""
        effects: list[Effect] = []
        stream_id = event.stream_id
        stream_data = state.streams.get(stream_id)

        if not stream_data:
            error = StreamError(message=f"Stream {stream_id} not found for reset", stream_id=stream_id)
            effects.append(FailUserFuture(future=event.future, exception=error))
            return effects

        if stream_data.state in (StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED, StreamState.RESET_SENT):
            effects.append(CompleteUserFuture(future=event.future))
            return effects

        original_state = stream_data.state

        stream_data.state = StreamState.RESET_SENT
        stream_data.closed_at = get_timestamp()
        stream_data.close_code = event.error_code

        http_error_code = webtransport_code_to_http_code(app_error_code=event.error_code)
        effects.append(ResetQuicStream(stream_id=stream_id, error_code=http_error_code))
        effects.append(CompleteUserFuture(future=event.future))

        while stream_data.write_buffer:
            _data_chunk, write_future, _end_stream = stream_data.write_buffer.popleft()
            if not write_future.done():
                error = StreamError(
                    message=f"Stream {stream_id} reset by application", stream_id=stream_id, error_code=event.error_code
                )
                effects.append(FailUserFuture(future=write_future, exception=error))

        match original_state:
            case StreamState.HALF_CLOSED_REMOTE | StreamState.RESET_RECEIVED:
                stream_data.state = StreamState.CLOSED
                effects.append(
                    EmitStreamEvent(
                        stream_id=stream_id, event_type=EventType.STREAM_CLOSED, data={"stream_id": stream_id}
                    )
                )

        logger.debug(
            "Stream %d reset locally with code %d (mapped to %x)", stream_id, event.error_code, http_error_code
        )
        return effects

    def handle_send_stream_data(self, *, event: UserSendStreamData, state: ProtocolState) -> list[Effect]:
        """Handle the UserSendStreamData event to send data."""
        effects: list[Effect] = []
        stream_id = event.stream_id
        stream_data = state.streams.get(stream_id)

        if not stream_data:
            error = StreamError(message=f"Stream {stream_id} not found for sending data", stream_id=stream_id)
            effects.append(FailUserFuture(future=event.future, exception=error))
            return effects

        if stream_data.state in (StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED, StreamState.RESET_SENT):
            error = StreamError(
                message=f"Stream {stream_id} is not writable (state: {stream_data.state})", stream_id=stream_id
            )
            effects.append(FailUserFuture(future=event.future, exception=error))
            return effects

        session_id = stream_data.session_id
        session_data = state.sessions.get(session_id)
        if not session_data:
            logger.error("Internal state error: Stream %d exists but session %s does not", stream_id, session_id)
            error = StreamError(message="Internal state error: Session not found", stream_id=stream_id)
            effects.append(FailUserFuture(future=event.future, exception=error))
            return effects

        try:
            data_bytes = ensure_bytes(data=event.data)
        except TypeError as exc:
            logger.warning("Stream %d received invalid data type: %s", stream_id, exc)
            return [FailUserFuture(future=event.future, exception=exc)]

        data_len = len(data_bytes)
        max_buffer_size = self._config.max_stream_write_buffer
        current_buffer_size = sum(len(item[0]) for item in stream_data.write_buffer)

        if current_buffer_size + data_len > max_buffer_size:
            error = StreamError(
                message=(
                    f"Stream {stream_id} write buffer full "
                    f"({current_buffer_size} + {data_len} > {max_buffer_size} bytes)"
                ),
                stream_id=stream_id,
            )
            return [FailUserFuture(future=event.future, exception=error)]

        if stream_data.write_buffer:
            logger.debug("Stream %d write added to existing write buffer", stream_id)
            stream_data.write_buffer.append((data_bytes, event.future, event.end_stream))
            return []

        available_credit = session_data.peer_max_data - session_data.local_data_sent

        if data_len <= available_credit:
            session_data.local_data_sent += data_len
            stream_data.bytes_sent += data_len
            effects.append(SendQuicData(stream_id=stream_id, data=data_bytes, end_stream=event.end_stream))
            effects.append(CompleteUserFuture(future=event.future))

            if event.end_stream:
                original_state = stream_data.state
                match original_state:
                    case StreamState.HALF_CLOSED_REMOTE | StreamState.RESET_RECEIVED:
                        stream_data.state = StreamState.CLOSED
                        effects.append(
                            EmitStreamEvent(
                                stream_id=stream_id, event_type=EventType.STREAM_CLOSED, data={"stream_id": stream_id}
                            )
                        )
                    case StreamState.OPEN:
                        stream_data.state = StreamState.HALF_CLOSED_LOCAL
                logger.debug("Stream %d send side closed", stream_id)

            return effects

        elif available_credit > 0:
            data_to_send_now = data_bytes[:available_credit]
            remaining_data = data_bytes[available_credit:]

            session_data.local_data_sent += available_credit
            stream_data.bytes_sent += available_credit
            effects.append(SendQuicData(stream_id=stream_id, data=data_to_send_now, end_stream=False))

            logger.debug(
                "Stream %d partial send: sent %d bytes, buffering %d bytes",
                stream_id,
                available_credit,
                len(remaining_data),
            )
            stream_data.write_buffer.append((remaining_data, event.future, event.end_stream))

            buf = Buffer(capacity=8)
            buf.push_uint_var(session_data.peer_max_data)
            effects.append(
                SendH3Capsule(
                    stream_id=session_data.control_stream_id,
                    capsule_type=constants.WT_DATA_BLOCKED_TYPE,
                    capsule_data=buf.data,
                )
            )
            return effects

        else:
            logger.debug(
                "Stream %d write blocked by session flow control (%d > %d)", stream_id, data_len, available_credit
            )
            stream_data.write_buffer.append((data_bytes, event.future, event.end_stream))

            buf = Buffer(capacity=8)
            buf.push_uint_var(session_data.peer_max_data)
            effects.append(
                SendH3Capsule(
                    stream_id=session_data.control_stream_id,
                    capsule_type=constants.WT_DATA_BLOCKED_TYPE,
                    capsule_data=buf.data,
                )
            )
            return effects

    def handle_stop_stream(self, *, event: UserStopStream, state: ProtocolState) -> list[Effect]:
        """Handle the UserStopStream event to stop the receiving side."""
        effects: list[Effect] = []
        stream_id = event.stream_id
        stream_data = state.streams.get(stream_id)

        if not stream_data:
            error = StreamError(message=f"Stream {stream_id} not found for stop", stream_id=stream_id)
            effects.append(FailUserFuture(future=event.future, exception=error))
            return effects

        if stream_data.state in (StreamState.HALF_CLOSED_REMOTE, StreamState.CLOSED, StreamState.RESET_RECEIVED):
            effects.append(CompleteUserFuture(future=event.future))
            return effects

        original_state = stream_data.state
        stream_data.state = StreamState.RESET_RECEIVED
        stream_data.closed_at = get_timestamp()
        stream_data.close_code = event.error_code

        http_error_code = webtransport_code_to_http_code(app_error_code=event.error_code)
        effects.append(StopQuicStream(stream_id=stream_id, error_code=http_error_code))
        effects.append(CompleteUserFuture(future=event.future))

        while stream_data.pending_read_requests:
            read_future = stream_data.pending_read_requests.popleft()
            if not read_future.done():
                error = StreamError(
                    message=f"Stream {stream_id} stopped by application",
                    stream_id=stream_id,
                    error_code=event.error_code,
                )
                effects.append(FailUserFuture(future=read_future, exception=error))

        match original_state:
            case StreamState.HALF_CLOSED_LOCAL | StreamState.RESET_SENT:
                stream_data.state = StreamState.CLOSED
                effects.append(
                    EmitStreamEvent(
                        stream_id=stream_id, event_type=EventType.STREAM_CLOSED, data={"stream_id": stream_id}
                    )
                )

        logger.debug(
            "Stream %d receive side stopped locally with code %d (mapped to %x)",
            stream_id,
            event.error_code,
            http_error_code,
        )
        return effects

    def handle_stream_read(self, *, event: UserStreamRead, state: ProtocolState) -> list[Effect]:
        """Handle the UserStreamRead event to read data."""
        effects: list[Effect] = []
        stream_id = event.stream_id
        stream_data = state.streams.get(stream_id)

        if not stream_data:
            error = StreamError(message=f"Stream {stream_id} not found for reading", stream_id=stream_id)
            effects.append(FailUserFuture(future=event.future, exception=error))
            return effects

        if stream_data.read_buffer_size > 0:
            target = event.max_bytes if event.max_bytes > 0 else stream_data.read_buffer_size
            data_to_return = self._read_from_buffer(stream_data=stream_data, max_bytes=target)
            effects.append(CompleteUserFuture(future=event.future, value=data_to_return))
            return effects

        if stream_data.state in (StreamState.RESET_RECEIVED, StreamState.CLOSED):
            error = StreamError(
                message=f"Stream {stream_id} receive side closed (state: {stream_data.state})", stream_id=stream_id
            )
            effects.append(FailUserFuture(future=event.future, exception=error))
            return effects

        if stream_data.state in (StreamState.HALF_CLOSED_REMOTE,):
            effects.append(CompleteUserFuture(future=event.future, value=b""))
            return effects

        stream_data.pending_read_requests.append(event.future)
        return effects

    def handle_transport_stream_reset(self, *, event: TransportStreamReset, state: ProtocolState) -> list[Effect]:
        """Handle a transport-level stream reset from the peer."""
        effects: list[Effect] = []
        stream_id = event.stream_id
        stream_data = state.streams.get(stream_id)

        if not stream_data or stream_data.state == StreamState.CLOSED:
            return []

        logger.debug("Stream %d reset by peer with code %d", stream_id, event.error_code)

        app_error_code = event.error_code
        if ErrorCodes.WT_APPLICATION_ERROR_FIRST <= event.error_code <= ErrorCodes.WT_APPLICATION_ERROR_LAST:
            try:
                app_error_code = http_code_to_webtransport_code(http_error_code=event.error_code)
            except ValueError:
                logger.warning(
                    "Received reserved H3 error code %x on stream %d, using as-is.", event.error_code, stream_id
                )

        stream_data.closed_at = get_timestamp()
        stream_data.close_code = app_error_code

        while stream_data.pending_read_requests:
            read_future = stream_data.pending_read_requests.popleft()
            if not read_future.done():
                error = StreamError(
                    message=f"Stream {stream_id} reset by peer", stream_id=stream_id, error_code=app_error_code
                )
                effects.append(FailUserFuture(future=read_future, exception=error))

        while stream_data.write_buffer:
            _data_chunk, write_future, _end_stream = stream_data.write_buffer.popleft()
            if not write_future.done():
                error = StreamError(
                    message=f"Stream {stream_id} reset by peer", stream_id=stream_id, error_code=app_error_code
                )
                effects.append(FailUserFuture(future=write_future, exception=error))

        stream_data.state = StreamState.CLOSED

        effects.append(
            EmitStreamEvent(stream_id=stream_id, event_type=EventType.STREAM_CLOSED, data={"stream_id": stream_id})
        )

        return effects

    def handle_webtransport_stream_data(
        self, *, event: WebTransportStreamDataReceived, state: ProtocolState
    ) -> list[Effect]:
        """Handle WebTransport data received on an established stream."""
        effects: list[Effect] = []
        stream_id = event.stream_id
        stream_data = state.streams.get(stream_id)
        session_data: SessionStateData | None = None

        if not stream_data:
            if self._is_client:
                logger.warning("Client received WT data for unknown stream %d, ignoring.", stream_id)
                return []

            session_id = state.stream_to_session_map.get(event.control_stream_id)
            if not session_id:
                control_stream_id = event.control_stream_id
                if state.early_event_count >= self._config.max_total_pending_events:
                    logger.warning(
                        "Global early event buffer full (%d), rejecting stream %d", state.early_event_count, stream_id
                    )
                    return [
                        ResetQuicStream(
                            stream_id=stream_id, error_code=constants.ErrorCodes.WT_BUFFERED_STREAM_REJECTED
                        )
                    ]

                session_buffer = state.early_event_buffer.get(control_stream_id, [])
                if len(session_buffer) >= self._config.max_pending_events_per_session:
                    logger.warning(
                        "Per-session early event buffer full (%d) for session %d, rejecting stream %d",
                        len(session_buffer),
                        control_stream_id,
                        stream_id,
                    )
                    return [
                        ResetQuicStream(
                            stream_id=stream_id, error_code=constants.ErrorCodes.WT_BUFFERED_STREAM_REJECTED
                        )
                    ]

                logger.debug("Buffering early event for stream %d on unknown session %d", stream_id, control_stream_id)
                state.early_event_buffer.setdefault(control_stream_id, []).append((get_timestamp(), event))
                state.early_event_count += 1
                return []

            session_data = state.sessions.get(session_id)
            if not session_data:
                logger.warning(
                    "Received WT data for stream %d with unknown session %s, ignoring.", stream_id, session_id
                )
                return effects

            if session_data.state not in (SessionState.CONNECTED, SessionState.DRAINING):
                logger.debug(
                    "Ignoring new stream %d for session %s in state %s", stream_id, session_id, session_data.state
                )
                return []

            direction = get_stream_direction_from_id(stream_id=stream_id, is_client=self._is_client)

            match direction:
                case StreamDirection.RECEIVE_ONLY:
                    if session_data.peer_streams_uni_opened >= session_data.local_max_streams_uni:
                        logger.warning(
                            "Session %s unidirectional stream limit (%d) reached, ignoring stream %d",
                            session_id,
                            session_data.local_max_streams_uni,
                            stream_id,
                        )
                        return []
                    session_data.peer_streams_uni_opened += 1

                    credit_effect = self._check_and_send_stream_credit(
                        session_data=session_data, is_unidirectional=True
                    )
                    if credit_effect:
                        effects.append(credit_effect)

                case StreamDirection.BIDIRECTIONAL:
                    if session_data.peer_streams_bidi_opened >= session_data.local_max_streams_bidi:
                        logger.warning(
                            "Session %s bidirectional stream limit (%d) reached, ignoring stream %d",
                            session_id,
                            session_data.local_max_streams_bidi,
                            stream_id,
                        )
                        return []
                    session_data.peer_streams_bidi_opened += 1

                    credit_effect = self._check_and_send_stream_credit(
                        session_data=session_data, is_unidirectional=False
                    )
                    if credit_effect:
                        effects.append(credit_effect)

                case StreamDirection.SEND_ONLY:
                    logger.warning(
                        "Received WT data on server for client-initiated send-only stream %d, ignoring.", stream_id
                    )
                    return []

            logger.debug("Creating new incoming stream %d for session %s", stream_id, session_id)
            stream_data = StreamStateData(
                stream_id=stream_id,
                session_id=session_id,
                direction=direction,
                state=StreamState.OPEN,
                created_at=get_timestamp(),
            )
            state.streams[stream_id] = stream_data
            state.stream_to_session_map[stream_id] = session_id

            effects.append(
                EmitStreamEvent(
                    stream_id=stream_id,
                    event_type=EventType.STREAM_OPENED,
                    data={"stream_id": stream_id, "session_id": session_id, "direction": direction},
                )
            )

        if stream_data.state in (StreamState.RESET_RECEIVED, StreamState.CLOSED):
            logger.debug("Ignoring WT data for already closed/reset stream %d", stream_id)
            return []

        if not session_data:
            session_data = state.sessions.get(stream_data.session_id)
            if not session_data:
                logger.error(
                    "Internal state error: Stream %d exists but session %s does not. Cannot process data.",
                    stream_id,
                    stream_data.session_id,
                )
                return effects

        if event.data:
            data_len = len(event.data)
            stream_data.bytes_received += data_len
            stream_data.read_buffer.append(event.data)
            stream_data.read_buffer_size += data_len

            if session_data:
                session_data.peer_data_sent += data_len
                credit_effect = self._check_and_send_data_credit(session_data=session_data)
                if credit_effect:
                    effects.append(credit_effect)

        while stream_data.pending_read_requests and stream_data.read_buffer_size > 0:
            read_future = stream_data.pending_read_requests.popleft()
            if not read_future.done():
                target = stream_data.read_buffer_size
                data_chunk = self._read_from_buffer(stream_data=stream_data, max_bytes=target)
                effects.append(CompleteUserFuture(future=read_future, value=data_chunk))

        if event.stream_ended:
            original_state = stream_data.state
            match original_state:
                case StreamState.HALF_CLOSED_LOCAL | StreamState.RESET_SENT:
                    if stream_data.read_buffer_size == 0:
                        stream_data.state = StreamState.CLOSED
                        stream_data.closed_at = get_timestamp()
                        effects.append(
                            EmitStreamEvent(
                                stream_id=stream_id, event_type=EventType.STREAM_CLOSED, data={"stream_id": stream_id}
                            )
                        )
                    else:
                        stream_data.state = StreamState.HALF_CLOSED_REMOTE
                        logger.debug("Stream %d rx closed, data pending read. Moving to HALF_CLOSED_REMOTE", stream_id)
                case StreamState.OPEN:
                    stream_data.state = StreamState.HALF_CLOSED_REMOTE
                    logger.debug("Stream %d receive side closed by peer (WT data)", stream_id)

            while stream_data.pending_read_requests:
                read_future = stream_data.pending_read_requests.popleft()
                if not read_future.done():
                    effects.append(CompleteUserFuture(future=read_future, value=b""))

        return effects

    def _check_and_send_data_credit(self, *, session_data: SessionStateData) -> Effect | None:
        """Check session data credit and send a MAX_DATA capsule if needed."""
        if not getattr(
            self._config, "flow_control_window_auto_scale", constants.DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
        ):
            return None

        target_window = getattr(self._config, "flow_control_window_size", constants.DEFAULT_FLOW_CONTROL_WINDOW_SIZE)
        if target_window <= 0:
            return None

        current_limit = session_data.local_max_data
        current_usage = session_data.peer_data_sent

        available_credit = current_limit - current_usage
        threshold = target_window // 2

        if available_credit <= threshold:
            new_limit = current_usage + target_window

            logger.debug(
                "Session %s data credit auto-increment: usage=%d available=%d limit=%d new_limit=%d",
                session_data.session_id,
                current_usage,
                available_credit,
                current_limit,
                new_limit,
            )

            session_data.local_max_data = new_limit

            buf = Buffer(capacity=8)
            buf.push_uint_var(new_limit)

            return SendH3Capsule(
                stream_id=session_data.control_stream_id, capsule_type=constants.WT_MAX_DATA_TYPE, capsule_data=buf.data
            )
        return None

    def _check_and_send_stream_credit(
        self, *, session_data: SessionStateData, is_unidirectional: bool
    ) -> Effect | None:
        """Check stream credit and send a MAX_STREAMS capsule if needed."""
        if not getattr(
            self._config, "flow_control_window_auto_scale", constants.DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
        ):
            return None

        if is_unidirectional:
            target_window = getattr(
                self._config, "stream_flow_control_increment_uni", constants.DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI
            )
            if target_window <= 0:
                return None

            current_limit = session_data.local_max_streams_uni
            current_usage = session_data.peer_streams_uni_opened
            capsule_type = constants.WT_MAX_STREAMS_UNI_TYPE
        else:
            target_window = getattr(
                self._config, "stream_flow_control_increment_bidi", constants.DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI
            )
            if target_window <= 0:
                return None

            current_limit = session_data.local_max_streams_bidi
            current_usage = session_data.peer_streams_bidi_opened
            capsule_type = constants.WT_MAX_STREAMS_BIDI_TYPE

        available_credit = current_limit - current_usage
        threshold = target_window // 2

        if available_credit <= threshold:
            new_limit = current_usage + target_window

            logger.debug(
                ("Session %s stream credit auto-increment: type=%s usage=%d " "available=%d limit=%d new_limit=%d"),
                session_data.session_id,
                "uni" if is_unidirectional else "bidi",
                current_usage,
                available_credit,
                current_limit,
                new_limit,
            )

            if is_unidirectional:
                session_data.local_max_streams_uni = new_limit
            else:
                session_data.local_max_streams_bidi = new_limit

            buf = Buffer(capacity=8)
            buf.push_uint_var(new_limit)

            return SendH3Capsule(
                stream_id=session_data.control_stream_id, capsule_type=capsule_type, capsule_data=buf.data
            )
        return None

    def _read_from_buffer(self, *, stream_data: StreamStateData, max_bytes: int) -> bytes:
        """Read up to max_bytes from the stream's read buffer."""
        chunks: list[bytes] = []
        bytes_collected = 0

        while stream_data.read_buffer and bytes_collected < max_bytes:
            chunk = stream_data.read_buffer.popleft()
            chunk_len = len(chunk)
            needed = max_bytes - bytes_collected

            if chunk_len <= needed:
                chunks.append(chunk)
                bytes_collected += chunk_len
                stream_data.read_buffer_size -= chunk_len
            else:
                part = chunk[:needed]
                remainder = chunk[needed:]
                chunks.append(part)
                bytes_collected += needed
                stream_data.read_buffer_size -= needed
                stream_data.read_buffer.appendleft(remainder)
                break

        return b"".join(chunks)
