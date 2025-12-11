"""Handle connection-level logic for the protocol engine."""

from __future__ import annotations

import http
from typing import TYPE_CHECKING

from pywebtransport import constants
from pywebtransport._protocol.events import (
    CleanupH3Stream,
    CloseQuicConnection,
    CompleteUserFuture,
    ConnectionClose,
    CreateH3Session,
    Effect,
    EmitConnectionEvent,
    EmitSessionEvent,
    FailUserFuture,
    GoawayReceived,
    HeadersReceived,
    InternalBindH3Session,
    InternalCleanupResources,
    InternalFailH3Session,
    SendH3Capsule,
    SendH3Goaway,
    SendH3Headers,
    TransportConnectionTerminated,
    TransportQuicParametersReceived,
    UserConnectionGracefulClose,
    UserCreateSession,
    UserGetConnectionDiagnostics,
)
from pywebtransport._protocol.state import ProtocolState, SessionInitData, SessionStateData
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import ConnectionError, ProtocolError, SessionError
from pywebtransport.types import ConnectionId, ConnectionState, EventType, SessionState, StreamState
from pywebtransport.utils import generate_session_id, get_header, get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.config import ClientConfig, ServerConfig


__all__: list[str] = []

logger = get_logger(name=__name__)


class ConnectionProcessor:
    """Process connection-level events and manage state transitions."""

    def __init__(self, *, is_client: bool, config: ClientConfig | ServerConfig, connection_id: ConnectionId) -> None:
        """Initialize the connection processor."""
        self._is_client = is_client
        self._config = config
        self._connection_id = connection_id

    def handle_cleanup_resources(self, *, event: InternalCleanupResources, state: ProtocolState) -> list[Effect]:
        """Handle the InternalCleanupResources event."""
        effects: list[Effect] = []

        closed_session_ids = {sid for sid, sdata in state.sessions.items() if sdata.state == SessionState.CLOSED}
        closed_stream_ids = {stid for stid, stdata in state.streams.items() if stdata.state == StreamState.CLOSED}

        for sid in closed_session_ids:
            logger.debug("Cleaning up closed session %s from state", sid)
            session_data = state.sessions.pop(sid, None)
            if session_data:
                control_stream_id = getattr(session_data, "control_stream_id", None)
                if control_stream_id is not None:
                    state.stream_to_session_map.pop(control_stream_id, None)
                    effects.append(CleanupH3Stream(stream_id=control_stream_id))

                for stid in session_data.active_streams:
                    if stid in state.streams:
                        state.streams.pop(stid, None)
                    state.stream_to_session_map.pop(stid, None)
                    effects.append(CleanupH3Stream(stream_id=stid))

        for stid in closed_stream_ids:
            if stid in state.streams:
                logger.debug("Cleaning up closed stream %d from state", stid)
                state.streams.pop(stid, None)
                state.stream_to_session_map.pop(stid, None)
                effects.append(CleanupH3Stream(stream_id=stid))

        return effects

    def handle_connection_close(self, *, event: ConnectionClose, state: ProtocolState) -> list[Effect]:
        """Handle the ConnectionClose event."""
        effects: list[Effect] = []
        if state.connection_state not in (ConnectionState.CLOSED, ConnectionState.CLOSING):
            state.connection_state = ConnectionState.CLOSING
            state.closed_at = get_timestamp()
            effects.append(CloseQuicConnection(error_code=event.error_code, reason=event.reason))
        effects.append(CompleteUserFuture(future=event.future))
        return effects

    def handle_connection_terminated(
        self, *, event: TransportConnectionTerminated, state: ProtocolState
    ) -> list[Effect]:
        """Handle the TransportConnectionTerminated event."""
        if state.connection_state == ConnectionState.CLOSED:
            return []

        state.connection_state = ConnectionState.CLOSED
        state.closed_at = get_timestamp()

        effects: list[Effect] = []
        error = ConnectionError(message=f"Connection terminated: {event.reason_phrase}", error_code=event.error_code)

        state.pending_session_configs.clear()

        pending_futures = state.pending_create_session_futures
        while pending_futures:
            _stream_id, fut = pending_futures.popitem()
            if not fut.done():
                effects.append(FailUserFuture(future=fut, exception=error))

        for stream_data in state.streams.values():
            while stream_data.pending_read_requests:
                read_fut = stream_data.pending_read_requests.popleft()
                if not read_fut.done():
                    effects.append(FailUserFuture(future=read_fut, exception=error))
            while stream_data.write_buffer:
                _data, write_fut, _end = stream_data.write_buffer.popleft()
                if not write_fut.done():
                    effects.append(FailUserFuture(future=write_fut, exception=error))

        effects.append(
            EmitConnectionEvent(
                event_type=EventType.CONNECTION_CLOSED,
                data={
                    "connection_id": self._connection_id,
                    "reason": event.reason_phrase,
                    "error_code": event.error_code,
                },
            )
        )

        return effects

    def handle_create_session(self, *, event: UserCreateSession, state: ProtocolState) -> list[Effect]:
        """Handle the UserCreateSession event (client-only)."""
        if not self._is_client:
            return [
                FailUserFuture(
                    future=event.future,
                    exception=ProtocolError(message="Server cannot create sessions using this method"),
                )
            ]

        if state.connection_state != ConnectionState.CONNECTED:
            return [
                FailUserFuture(
                    future=event.future,
                    exception=ConnectionError(
                        message=f"Cannot create session, connection state is {state.connection_state}"
                    ),
                )
            ]

        session_id = generate_session_id()

        state.pending_session_configs[session_id] = SessionInitData(
            path=event.path, headers=event.headers, created_at=get_timestamp()
        )

        return [
            CreateH3Session(session_id=session_id, path=event.path, headers=event.headers, create_future=event.future)
        ]

    def handle_get_connection_diagnostics(
        self, *, event: UserGetConnectionDiagnostics, state: ProtocolState
    ) -> list[Effect]:
        """Handle the UserGetConnectionDiagnostics event."""
        diagnostics_data = {
            "connection_id": self._connection_id,
            "state": state.connection_state,
            "is_client": state.is_client,
            "connected_at": state.connected_at,
            "closed_at": state.closed_at,
            "max_datagram_size": state.max_datagram_size,
            "remote_max_datagram_frame_size": state.remote_max_datagram_frame_size,
            "session_count": len(state.sessions),
            "stream_count": len(state.streams),
        }
        return [CompleteUserFuture(future=event.future, value=diagnostics_data)]

    def handle_goaway_received(self, *, event: GoawayReceived, state: ProtocolState) -> list[Effect]:
        """Handle the H3 GOAWAY signal by draining all active sessions."""
        effects: list[Effect] = []

        if state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
            state.connection_state = ConnectionState.CLOSING
            state.closed_at = get_timestamp()

        for session_id, session_data in state.sessions.items():
            if session_data.state == SessionState.CONNECTED:
                session_data.state = SessionState.DRAINING
                effects.append(
                    SendH3Capsule(
                        stream_id=session_data.control_stream_id,
                        capsule_type=constants.DRAIN_WEBTRANSPORT_SESSION_TYPE,
                        capsule_data=b"",
                    )
                )
                effects.append(
                    EmitSessionEvent(
                        session_id=session_id, event_type=EventType.SESSION_DRAINING, data={"session_id": session_id}
                    )
                )
        return effects

    def handle_graceful_close(self, *, event: UserConnectionGracefulClose, state: ProtocolState) -> list[Effect]:
        """Handle the user request for a graceful H3 GOAWAY shutdown."""
        effects: list[Effect] = []

        if not state.local_goaway_sent:
            state.local_goaway_sent = True
            effects.append(SendH3Goaway())

            if state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                state.connection_state = ConnectionState.CLOSING
                state.closed_at = get_timestamp()

        effects.append(CompleteUserFuture(future=event.future))
        return effects

    def handle_headers_received(self, *, event: HeadersReceived, state: ProtocolState) -> list[Effect]:
        """Handle the HeadersReceived event."""
        effects: list[Effect] = []
        now = get_timestamp()
        stream_id = event.stream_id

        if self._is_client:
            session_id = state.stream_to_session_map.get(stream_id)
            if not session_id:
                logger.warning("Received headers on unknown client stream %d", stream_id)
                return []

            session_data = state.sessions.get(session_id)
            if not session_data or session_data.state != SessionState.CONNECTING:
                logger.warning("Received headers for non-connecting session %s on stream %d", session_id, stream_id)
                return []

            pending_futures = state.pending_create_session_futures
            create_future = pending_futures.pop(stream_id, None)

            status = get_header(headers=event.headers, key=":status")
            if status == str(http.HTTPStatus.OK):
                session_data.state = SessionState.CONNECTED
                session_data.ready_at = now
                effects.append(
                    EmitSessionEvent(
                        session_id=session_id,
                        event_type=EventType.SESSION_READY,
                        data={
                            "session_id": session_id,
                            "ready_at": now,
                            "control_stream_id": session_data.control_stream_id,
                            "path": session_data.path,
                            "headers": session_data.headers,
                        },
                    )
                )
                if create_future and not create_future.done():
                    effects.append(CompleteUserFuture(future=create_future, value=session_id))
            else:
                status_val = status or "Unknown"
                reason = f"Session creation failed with status {status_val}"
                session_data.state = SessionState.CLOSED
                session_data.closed_at = now
                session_data.close_reason = reason
                effects.append(
                    EmitSessionEvent(
                        session_id=session_id,
                        event_type=EventType.SESSION_CLOSED,
                        data={"session_id": session_id, "error_code": ErrorCodes.H3_REQUEST_REJECTED, "reason": reason},
                    )
                )
                if create_future and not create_future.done():
                    error = ConnectionError(message=reason, error_code=ErrorCodes.H3_REQUEST_REJECTED)
                    effects.append(FailUserFuture(future=create_future, exception=error))
                state.sessions.pop(session_id, None)
                state.stream_to_session_map.pop(stream_id, None)

        else:
            if stream_id in state.stream_to_session_map:
                logger.debug("Received trailers on existing session stream %d, ignoring.", stream_id)
                return []

            if state.connection_state != ConnectionState.CONNECTED:
                logger.debug(
                    "Rejecting new session on stream %d: connection state is %s", stream_id, state.connection_state
                )
                effects.append(SendH3Headers(stream_id=stream_id, status=http.HTTPStatus.TOO_MANY_REQUESTS))
                return effects

            method = get_header(headers=event.headers, key=":method")
            protocol = get_header(headers=event.headers, key=":protocol")

            if method != "CONNECT" or protocol != "webtransport":
                logger.debug("Rejecting non-WebTransport request on stream %d", stream_id)
                effects.append(SendH3Headers(stream_id=stream_id, status=http.HTTPStatus.BAD_REQUEST))
                return effects

            max_sess = getattr(self._config, "max_sessions", 0)
            if max_sess > 0 and len(state.sessions) >= max_sess:
                logger.warning("Session limit (%d) reached, rejecting new session on stream %d", max_sess, stream_id)
                effects.append(SendH3Headers(stream_id=stream_id, status=http.HTTPStatus.TOO_MANY_REQUESTS))
                return effects

            session_id = generate_session_id()
            path = get_header(headers=event.headers, key=":path", default="/") or "/"

            session_data = SessionStateData(
                session_id=session_id,
                control_stream_id=stream_id,
                state=SessionState.CONNECTING,
                path=path,
                headers=event.headers,
                created_at=now,
                local_max_data=self._config.initial_max_data,
                peer_max_data=state.peer_initial_max_data,
                local_max_streams_bidi=self._config.initial_max_streams_bidi,
                peer_max_streams_bidi=state.peer_initial_max_streams_bidi,
                local_max_streams_uni=self._config.initial_max_streams_uni,
                peer_max_streams_uni=state.peer_initial_max_streams_uni,
            )
            state.sessions[session_id] = session_data
            state.stream_to_session_map[stream_id] = session_id

            effects.append(
                EmitSessionEvent(
                    session_id=session_id,
                    event_type=EventType.SESSION_REQUEST,
                    data={
                        "session_id": session_id,
                        "control_stream_id": stream_id,
                        "path": path,
                        "headers": event.headers,
                    },
                )
            )

        return effects

    def handle_internal_bind_h3_session(self, *, event: InternalBindH3Session, state: ProtocolState) -> list[Effect]:
        """Handle the InternalBindH3Session event."""
        session_id = event.session_id

        init_data = state.pending_session_configs.pop(session_id, None)
        if not init_data:
            return [
                FailUserFuture(
                    future=event.future, exception=SessionError(f"Session init data for {session_id} not found")
                )
            ]

        session_data = SessionStateData(
            session_id=session_id,
            control_stream_id=event.control_stream_id,
            state=SessionState.CONNECTING,
            path=init_data.path,
            headers=init_data.headers,
            created_at=init_data.created_at,
            local_max_data=self._config.initial_max_data,
            peer_max_data=state.peer_initial_max_data,
            local_max_streams_bidi=self._config.initial_max_streams_bidi,
            peer_max_streams_bidi=state.peer_initial_max_streams_bidi,
            local_max_streams_uni=self._config.initial_max_streams_uni,
            peer_max_streams_uni=state.peer_initial_max_streams_uni,
        )

        state.sessions[session_id] = session_data
        state.stream_to_session_map[event.control_stream_id] = session_id
        state.pending_create_session_futures[event.control_stream_id] = event.future

        return []

    def handle_internal_fail_h3_session(self, *, event: InternalFailH3Session, state: ProtocolState) -> list[Effect]:
        """Handle the InternalFailH3Session event."""
        logger.error("H3 Session creation failed for %s: %s", event.session_id, event.exception)

        state.pending_session_configs.pop(event.session_id, None)

        return [FailUserFuture(future=event.future, exception=event.exception)]

    def handle_transport_parameters_received(
        self, *, event: TransportQuicParametersReceived, state: ProtocolState
    ) -> list[Effect]:
        """Handle the TransportQuicParametersReceived event."""
        logger.debug(
            "Received transport parameters: remote_max_datagram_frame_size=%d", event.remote_max_datagram_frame_size
        )
        state.remote_max_datagram_frame_size = event.remote_max_datagram_frame_size
        return []
