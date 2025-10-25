"""Protocol session tracker for WebTransport."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from aioquic._buffer import Buffer, BufferReadError
from aioquic.buffer import encode_uint_var

from pywebtransport import constants
from pywebtransport.config import ServerConfig
from pywebtransport.constants import ErrorCodes
from pywebtransport.events import Event
from pywebtransport.exceptions import ConnectionError, ProtocolError
from pywebtransport.protocol.events import CapsuleReceived, HeadersReceived
from pywebtransport.protocol.session_info import WebTransportSessionInfo
from pywebtransport.types import EventType, Headers, SessionId, SessionState, StreamId
from pywebtransport.utils import generate_session_id, get_logger, get_timestamp

if TYPE_CHECKING:
    from aioquic.quic.connection import QuicConnection

    from pywebtransport.config import ClientConfig
    from pywebtransport.protocol.h3_engine import WebTransportH3Engine


__all__: list[str] = []

logger = get_logger(name=__name__)


class _ProtocolSessionTracker:
    """Track the state and lifecycle of WebTransport sessions."""

    def __init__(
        self,
        *,
        config: ClientConfig | ServerConfig,
        is_client: bool,
        quic: QuicConnection,
        h3: WebTransportH3Engine,
        stats: dict[str, Any],
        emit_event: Callable[[EventType, Any], Coroutine[Any, Any, None]],
        trigger_transmission: Callable[[], None],
        cleanup_streams_for_session_by_id: Callable[[SessionId], None],
        abort_stream: Callable[..., None],
    ) -> None:
        """Initialize the protocol session tracker."""
        self._config = config
        self._is_client = is_client
        self._quic = quic
        self._h3 = h3
        self._stats = stats
        self._emit_event = emit_event
        self._trigger_transmission = trigger_transmission
        self._cleanup_streams_for_session_by_id = cleanup_streams_for_session_by_id
        self._abort_stream = abort_stream

        self._sessions: dict[SessionId, WebTransportSessionInfo] = {}
        self._session_control_streams: dict[StreamId, SessionId] = {}

        self._peer_max_sessions: int | None = None
        self._peer_initial_max_data: int = 0
        self._peer_initial_max_streams_bidi: int = 0
        self._peer_initial_max_streams_uni: int = 0

        self._h3.on(event_type=EventType.SETTINGS_RECEIVED, handler=self._on_settings_received)

    def close_webtransport_session(self, *, session_id: SessionId, code: int = 0, reason: str | None = None) -> None:
        """Close a specific WebTransport session."""
        session_info = self._sessions.get(session_id)
        if not session_info or session_info.state == SessionState.CLOSED:
            return

        logger.info("Closing WebTransport session: %s (code=%d)", session_id, code)

        buf = Buffer(capacity=1024)
        buf.push_uint32(code)
        buf.push_bytes((reason or "").encode("utf-8"))
        payload = buf.data
        capsule_header = encode_uint_var(constants.CLOSE_WEBTRANSPORT_SESSION_TYPE) + encode_uint_var(len(payload))

        self._h3.send_capsule(
            stream_id=session_info.control_stream_id,
            capsule_data=capsule_header + payload,
        )
        self._quic.send_stream_data(stream_id=session_info.control_stream_id, data=b"", end_stream=True)
        self._trigger_transmission()
        self._cleanup_session(session_id=session_id)

        asyncio.create_task(
            self._emit_event(
                EventType.SESSION_CLOSED,
                {"session_id": session_id, "code": code, "reason": reason},
            )
        )

    def teardown(self) -> None:
        """Remove event listeners to prevent memory leaks."""
        self._h3.off(event_type=EventType.SETTINGS_RECEIVED, handler=self._on_settings_received)

    def accept_webtransport_session(self, *, stream_id: StreamId, session_id: SessionId) -> None:
        """Accept a pending WebTransport session (server-only)."""
        if self._is_client:
            raise ProtocolError(message="Only servers can accept WebTransport sessions")

        session_info = self._sessions.get(session_id)
        if not session_info or session_info.control_stream_id != stream_id:
            raise ProtocolError(message=f"No pending session found for stream {stream_id} and id {session_id}")

        self._h3.send_headers(stream_id=stream_id, headers={":status": "200"})
        session_info.state = SessionState.CONNECTED
        session_info.ready_at = get_timestamp()
        self._trigger_transmission()

        asyncio.create_task(self._emit_event(EventType.SESSION_READY, session_info.to_dict()))
        logger.info("Accepted WebTransport session: %s", session_id)

    async def create_webtransport_session(
        self, *, path: str, headers: Headers | None = None
    ) -> tuple[SessionId, StreamId]:
        """Initiate a new WebTransport session (client-only)."""
        if not self._is_client:
            raise ProtocolError(message="Only clients can create WebTransport sessions")

        if self._peer_max_sessions is not None and len(self._sessions) >= self._peer_max_sessions:
            raise ConnectionError(
                message=f"Cannot create new session: server's session limit ({self._peer_max_sessions}) reached."
            )

        session_id = generate_session_id()
        headers_dict = headers or {}
        server_name = self._h3.get_server_name()
        authority = headers_dict.get("host") or server_name or "localhost"
        connect_headers: Headers = {
            ":method": "CONNECT",
            ":protocol": "webtransport",
            ":scheme": "https",
            ":path": path,
            ":authority": authority,
            **headers_dict,
        }
        stream_id = self._h3.get_next_available_stream_id(is_unidirectional=False)
        self._h3.send_headers(stream_id=stream_id, headers=connect_headers, end_stream=False)

        session_info = WebTransportSessionInfo(
            session_id=session_id,
            control_stream_id=stream_id,
            state=SessionState.CONNECTING,
            created_at=get_timestamp(),
            path=path,
            headers=headers_dict,
        )
        self._register_session(session_id=session_id, session_info=session_info)
        self._trigger_transmission()

        logger.info("Initiated WebTransport session: %s on control stream %d", session_id, stream_id)
        return session_id, stream_id

    async def handle_capsule_received(self, *, event: CapsuleReceived) -> None:
        """Handle a CAPSULE_RECEIVED event from the H3 engine."""
        session_id = self._session_control_streams.get(event.stream_id)
        if not (session_id and (session_info := self._sessions.get(session_id))):
            return

        try:
            raw_data = event.capsule_data
            buf = Buffer(data=raw_data)

            match event.capsule_type:
                case constants.WT_MAX_DATA_TYPE:
                    new_limit = buf.pull_uint_var()
                    if new_limit > session_info.peer_max_data:
                        session_info.peer_max_data = new_limit
                        await self._emit_event(
                            EventType.SESSION_MAX_DATA_UPDATED,
                            {"session_id": session_id, "max_data": new_limit},
                        )
                    elif new_limit < session_info.peer_max_data:
                        raise ProtocolError(message="Flow control limit decreased for MAX_DATA")
                case constants.WT_MAX_STREAMS_BIDI_TYPE:
                    new_limit = buf.pull_uint_var()
                    if new_limit > session_info.peer_max_streams_bidi:
                        session_info.peer_max_streams_bidi = new_limit
                        await self._emit_event(
                            EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                            {"session_id": session_id, "max_streams_bidi": new_limit},
                        )
                    elif new_limit < session_info.peer_max_streams_bidi:
                        raise ProtocolError(message="Flow control limit decreased for MAX_STREAMS_BIDI")
                case constants.WT_MAX_STREAMS_UNI_TYPE:
                    new_limit = buf.pull_uint_var()
                    if new_limit > session_info.peer_max_streams_uni:
                        session_info.peer_max_streams_uni = new_limit
                        await self._emit_event(
                            EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                            {"session_id": session_id, "max_streams_uni": new_limit},
                        )
                    elif new_limit < session_info.peer_max_streams_uni:
                        raise ProtocolError(message="Flow control limit decreased for MAX_STREAMS_UNI")
                case constants.CLOSE_WEBTRANSPORT_SESSION_TYPE:
                    app_code = buf.pull_uint32()
                    reason_bytes = buf.pull_bytes(len(raw_data) - buf.tell())
                    try:
                        reason = reason_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.warning(
                            "Received CLOSE_SESSION capsule for session %s with invalid UTF-8 reason string.",
                            session_id,
                        )
                        reason = reason_bytes.decode("utf-8", errors="replace")
                    logger.info("Received CLOSE_SESSION capsule: code=%d reason=%s", app_code, reason)
                    await self._emit_event(
                        EventType.SESSION_CLOSED,
                        {"session_id": session_id, "code": app_code, "reason": reason},
                    )
                    self._cleanup_session(session_id=session_id)

                case constants.DRAIN_WEBTRANSPORT_SESSION_TYPE:
                    logger.info("Received DRAIN_SESSION capsule for session %s", session_id)
                    await self._emit_event(
                        EventType.SESSION_DRAINING,
                        {"session_id": session_id},
                    )

        except BufferReadError:
            logger.warning("Could not parse flow control capsule for session %s", session_id)

    async def handle_headers_received(self, *, event: HeadersReceived, connection: Any) -> SessionId | None:
        """Handle HEADERS frames for session negotiation."""
        headers_dict = event.headers
        logger.debug("H3 headers received on stream %d: %s", event.stream_id, headers_dict)

        match (self._is_client, headers_dict.get(":method"), headers_dict.get(":protocol")):
            case (True, _, _):
                if session_id := self._session_control_streams.get(event.stream_id):
                    if session_id in self._sessions and headers_dict.get(":status") == "200":
                        session = self._sessions[session_id]
                        session.state = SessionState.CONNECTED
                        session.ready_at = get_timestamp()
                        logger.info("Client session %s is ready.", session_id)
                        await self._emit_event(EventType.SESSION_READY, session.to_dict())
                        return session_id
                    elif session_id:
                        status = headers_dict.get(":status", "unknown")
                        logger.error("Session %s creation failed with status %s", session_id, status)
                        await self._emit_event(
                            EventType.SESSION_CLOSED,
                            {
                                "session_id": session_id,
                                "code": 1,
                                "reason": f"HTTP status {status}",
                            },
                        )
                        self._cleanup_session(session_id=session_id)
            case (False, "CONNECT", "webtransport"):
                my_limit = 1
                if isinstance(self._config, ServerConfig):
                    my_limit = self._config.max_sessions

                if len(self._sessions) >= my_limit:
                    logger.warning(
                        "Session limit (%d) exceeded. Rejecting new session on stream %d",
                        my_limit,
                        event.stream_id,
                    )
                    self._quic.reset_stream(stream_id=event.stream_id, error_code=ErrorCodes.H3_REQUEST_REJECTED)
                    self._trigger_transmission()
                    return None

                session_id = generate_session_id()
                app_headers = headers_dict
                session_info = WebTransportSessionInfo(
                    session_id=session_id,
                    control_stream_id=event.stream_id,
                    state=SessionState.CONNECTING,
                    created_at=get_timestamp(),
                    path=app_headers.get(":path", "/"),
                    headers=app_headers,
                )
                self._register_session(session_id=session_id, session_info=session_info)
                event_data = session_info.to_dict()
                if connection:
                    event_data["connection"] = connection
                logger.info("Received WebTransport session request: %s for path '%s'", session_id, session_info.path)
                await self._emit_event(EventType.SESSION_REQUEST, event_data)
                return session_id
            case (False, method, _):
                logger.warning(
                    "Rejecting unsupported H3 request (method=%s, path=%s) on stream %d. "
                    "This server only accepts WebTransport CONNECT requests.",
                    method,
                    headers_dict.get(":path"),
                    event.stream_id,
                )
                try:
                    self._h3.send_headers(
                        stream_id=event.stream_id,
                        headers={":status": "404"},
                        end_stream=True,
                    )
                    self._trigger_transmission()
                except Exception as e:
                    logger.debug("Failed to send 404 rejection, aborting stream: %s", e)
                    self._abort_stream(stream_id=event.stream_id, error_code=ErrorCodes.H3_REQUEST_REJECTED)

        return None

    async def handle_stream_reset(self, *, stream_id: StreamId, error_code: int) -> None:
        """Handle a reset of a session control stream."""
        if session_id := self._session_control_streams.get(stream_id):
            logger.info("Session %s closed due to control stream %d reset.", session_id, stream_id)
            await self._emit_event(
                EventType.SESSION_CLOSED,
                {
                    "session_id": session_id,
                    "code": error_code,
                    "reason": "Control stream reset",
                },
            )
            self._cleanup_session(session_id=session_id)

    async def update_local_flow_control(self, *, session_id: SessionId) -> None:
        """Check and send flow control updates for the local peer."""
        session_info = self._sessions.get(session_id)
        if not session_info:
            return

        if self._config.flow_control_window_size > 0:
            remaining_credit = session_info.local_max_data - session_info.peer_data_sent
            if remaining_credit < (self._config.flow_control_window_size / 2):
                if self._config.flow_control_window_auto_scale:
                    new_limit = session_info.local_max_data * 2
                else:
                    new_limit = session_info.peer_data_sent + self._config.flow_control_window_size
                if new_limit > session_info.local_max_data:
                    session_info.local_max_data = new_limit
                    self._send_max_capsule(
                        session_info=session_info,
                        capsule_type=constants.WT_MAX_DATA_TYPE,
                        value=new_limit,
                    )
                    self._trigger_transmission()

        if session_info.peer_streams_bidi_opened >= session_info.local_max_streams_bidi:
            new_limit = session_info.local_max_streams_bidi + self._config.stream_flow_control_increment_bidi
            session_info.local_max_streams_bidi = new_limit
            self._send_max_capsule(
                session_info=session_info,
                capsule_type=constants.WT_MAX_STREAMS_BIDI_TYPE,
                value=new_limit,
            )
            self._trigger_transmission()

        if session_info.peer_streams_uni_opened >= session_info.local_max_streams_uni:
            new_limit = session_info.local_max_streams_uni + self._config.stream_flow_control_increment_uni
            session_info.local_max_streams_uni = new_limit
            self._send_max_capsule(
                session_info=session_info,
                capsule_type=constants.WT_MAX_STREAMS_UNI_TYPE,
                value=new_limit,
            )
            self._trigger_transmission()

    def get_all_sessions(self) -> list[WebTransportSessionInfo]:
        """Get a list of all current sessions."""
        return list(self._sessions.values())

    def get_session_by_control_stream(self, *, stream_id: StreamId) -> SessionId | None:
        """Get a session ID by its control stream ID."""
        return self._session_control_streams.get(stream_id)

    def get_session_info(self, *, session_id: SessionId) -> WebTransportSessionInfo | None:
        """Get information about a specific session."""
        return self._sessions.get(session_id)

    def _cleanup_session(self, *, session_id: SessionId) -> None:
        """Remove a session and notify to clean up its associated streams."""
        if session_info := self._sessions.pop(session_id, None):
            self._session_control_streams.pop(session_info.control_stream_id, None)
            self._cleanup_streams_for_session_by_id(session_id)
            logger.info("Cleaned up session %s and its associated streams.", session_id)

    async def _on_settings_received(self, event: Event) -> None:
        """Handle the SETTINGS_RECEIVED event from the H3 engine."""
        if isinstance(event.data, dict) and (settings := event.data.get("settings")):
            self._peer_max_sessions = settings.get(constants.SETTINGS_WT_MAX_SESSIONS)
            self._peer_initial_max_data = settings.get(constants.SETTINGS_WT_INITIAL_MAX_DATA, 0)
            self._peer_initial_max_streams_bidi = settings.get(constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI, 0)
            self._peer_initial_max_streams_uni = settings.get(constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI, 0)

            for session in self._sessions.values():
                session.peer_max_data = self._peer_initial_max_data
                session.peer_max_streams_bidi = self._peer_initial_max_streams_bidi
                session.peer_max_streams_uni = self._peer_initial_max_streams_uni

    def _register_session(self, *, session_id: SessionId, session_info: WebTransportSessionInfo) -> None:
        """Add a new session to internal tracking."""
        self._sessions[session_id] = session_info
        self._session_control_streams[session_info.control_stream_id] = session_id
        session_info.local_max_data = self._config.initial_max_data
        session_info.local_max_streams_bidi = self._config.initial_max_streams_bidi
        session_info.local_max_streams_uni = self._config.initial_max_streams_uni
        session_info.peer_max_data = self._peer_initial_max_data
        session_info.peer_max_streams_bidi = self._peer_initial_max_streams_bidi
        session_info.peer_max_streams_uni = self._peer_initial_max_streams_uni
        self._stats["sessions_created"] += 1

    def _send_blocked_capsule(
        self,
        *,
        session_info: WebTransportSessionInfo,
        is_data: bool = False,
        is_unidirectional: bool = False,
    ) -> None:
        """Send a WT_DATA_BLOCKED or WT_STREAMS_BLOCKED capsule."""
        if is_data:
            capsule_type = constants.WT_DATA_BLOCKED_TYPE
            limit = session_info.peer_max_data
        elif is_unidirectional:
            capsule_type = constants.WT_STREAMS_BLOCKED_UNI_TYPE
            limit = session_info.peer_max_streams_uni
        else:
            capsule_type = constants.WT_STREAMS_BLOCKED_BIDI_TYPE
            limit = session_info.peer_max_streams_bidi

        payload = encode_uint_var(limit)
        capsule_header = encode_uint_var(capsule_type) + encode_uint_var(len(payload))
        self._h3.send_capsule(
            stream_id=session_info.control_stream_id,
            capsule_data=capsule_header + payload,
        )

    def _send_max_capsule(self, *, session_info: WebTransportSessionInfo, capsule_type: int, value: int) -> None:
        """Send a WT_MAX_DATA or WT_MAX_STREAMS capsule."""
        payload = encode_uint_var(value)
        capsule_header = encode_uint_var(capsule_type) + encode_uint_var(len(payload))
        self._h3.send_capsule(
            stream_id=session_info.control_stream_id,
            capsule_data=capsule_header + payload,
        )
