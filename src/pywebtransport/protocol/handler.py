"""WebTransport Protocol Handler."""

from __future__ import annotations

import asyncio
import weakref
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Self

from aioquic.buffer import Buffer, BufferReadError, encode_uint_var
from aioquic.quic.connection import QuicConnection, QuicConnectionState
from aioquic.quic.events import QuicEvent, StreamReset

from pywebtransport import constants
from pywebtransport.config import ClientConfig, ServerConfig
from pywebtransport.constants import ErrorCodes
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import ConnectionError, FlowControlError, ProtocolError, TimeoutError
from pywebtransport.protocol import utils as protocol_utils
from pywebtransport.protocol.events import (
    CapsuleReceived,
    DatagramReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.protocol.h3_engine import WebTransportH3Engine
from pywebtransport.protocol.session_info import StreamInfo, WebTransportSessionInfo
from pywebtransport.types import (
    ConnectionState,
    EventHandler,
    EventType,
    Headers,
    SessionId,
    SessionState,
    StreamDirection,
    StreamId,
    StreamState,
)
from pywebtransport.utils import Timer, generate_session_id, get_logger, get_timestamp, validate_session_id

if TYPE_CHECKING:
    from pywebtransport.connection import WebTransportConnection


__all__ = ["WebTransportProtocolHandler"]

logger = get_logger(name="protocol.handler")


class WebTransportProtocolHandler(EventEmitter):
    """Orchestrates WebTransport sessions and streams over a QUIC connection."""

    def __init__(
        self,
        *,
        quic_connection: QuicConnection,
        is_client: bool = True,
        connection: WebTransportConnection | None = None,
    ) -> None:
        """Initialize the WebTransport protocol handler."""
        super().__init__()
        self._quic = quic_connection
        self._is_client = is_client
        self._connection_ref = weakref.ref(connection) if connection else None
        self._config = (
            connection.config if connection else (ClientConfig.create() if is_client else ServerConfig.create())
        )

        self._h3: WebTransportH3Engine = WebTransportH3Engine(quic=self._quic, config=self._config)
        self._h3.on(event_type=EventType.SETTINGS_RECEIVED, handler=self._on_settings_received)

        self._capsule_received_handler: EventHandler = self._create_capsule_received_handler()
        self._h3.on(event_type=EventType.CAPSULE_RECEIVED, handler=self._capsule_received_handler)

        self._sessions: dict[SessionId, WebTransportSessionInfo] = {}
        self._streams: dict[StreamId, StreamInfo] = {}
        self._session_control_streams: dict[StreamId, SessionId] = {}
        self._data_stream_to_session: dict[StreamId, SessionId] = {}
        self._session_owned_streams: dict[SessionId, set[StreamId]] = defaultdict(set)
        self._connection_state: ConnectionState = ConnectionState.IDLE
        self._last_activity = get_timestamp()
        self._peer_max_sessions: int | None = None
        self._peer_initial_max_data: int = 0
        self._peer_initial_max_streams_bidi: int = 0
        self._peer_initial_max_streams_uni: int = 0
        self._stats: dict[str, Any] = {
            "bytes_sent": 0,
            "bytes_received": 0,
            "sessions_created": 0,
            "streams_created": 0,
            "datagrams_sent": 0,
            "datagrams_received": 0,
            "errors": 0,
            "connected_at": None,
        }
        self._pending_events: defaultdict[StreamId, list[tuple[float, H3Event]]] = defaultdict(list)
        self._pending_events_count: int = 0
        self._cleanup_pending_events_task: asyncio.Task[None] | None = None
        logger.debug("WebTransport protocol handler initialized (client=%s)", is_client)

    @classmethod
    def create(
        cls,
        *,
        quic_connection: QuicConnection,
        is_client: bool = True,
        connection: WebTransportConnection | None = None,
    ) -> Self:
        """Factory method to create a new WebTransport protocol handler instance."""
        return cls(quic_connection=quic_connection, is_client=is_client, connection=connection)

    @property
    def is_connected(self) -> bool:
        """Check if the underlying connection is established."""
        return self._connection_state == ConnectionState.CONNECTED

    @property
    def connection(self) -> WebTransportConnection | None:
        """Get the parent WebTransportConnection via a weak reference."""
        return self._connection_ref() if self._connection_ref else None

    @property
    def connection_state(self) -> ConnectionState:
        """Get the current state of the underlying connection."""
        return self._connection_state

    @property
    def quic_connection(self) -> QuicConnection:
        """Get the underlying aioquic QuicConnection object."""
        return self._quic

    @property
    def stats(self) -> dict[str, Any]:
        """Get a copy of the protocol handler's statistics."""
        return self._stats.copy()

    async def close(self) -> None:
        """Close the protocol handler and clean up its resources."""
        if self._connection_state == ConnectionState.CLOSED:
            return

        if self._cleanup_pending_events_task:
            self._cleanup_pending_events_task.cancel()
            try:
                await self._cleanup_pending_events_task
            except asyncio.CancelledError:
                pass

        self._connection_state = ConnectionState.CLOSED
        self._teardown_event_handlers()
        await super().close()

    def connection_established(self) -> None:
        """Signal that the QUIC connection is established."""
        if self._connection_state in [ConnectionState.IDLE, ConnectionState.CONNECTING]:
            self._connection_state = ConnectionState.CONNECTED
            self._stats["connected_at"] = get_timestamp()
            if self._config.pending_event_ttl > 0:
                self._cleanup_pending_events_task = asyncio.create_task(self._cleanup_pending_events_loop())
            logger.info("Connection established.")
            self._trigger_transmission()

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

    def accept_webtransport_session(self, *, stream_id: StreamId, session_id: SessionId) -> None:
        """Accept a pending WebTransport session (server-only)."""
        if self._is_client:
            raise ProtocolError(message="Only servers can accept WebTransport sessions")

        session_info = self._sessions.get(session_id)
        if not session_info or session_info.stream_id != stream_id:
            raise ProtocolError(message=f"No pending session found for stream {stream_id} and id {session_id}")

        self._h3.send_headers(stream_id=stream_id, headers={":status": "200"})
        session_info.state = SessionState.CONNECTED
        session_info.ready_at = get_timestamp()
        self._trigger_transmission()

        asyncio.create_task(self.emit(event_type=EventType.SESSION_READY, data=session_info.to_dict()))
        logger.info("Accepted WebTransport session: %s", session_id)

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
            stream_id=session_info.stream_id,
            capsule_data=capsule_header + payload,
        )
        self._quic.send_stream_data(stream_id=session_info.stream_id, data=b"", end_stream=True)
        self._trigger_transmission()
        self._cleanup_session(session_id=session_id)

        asyncio.create_task(
            self.emit(
                event_type=EventType.SESSION_CLOSED,
                data={"session_id": session_id, "code": code, "reason": reason},
            )
        )

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
        server_name = self._quic.configuration.server_name
        authority = headers_dict.get("host") or server_name or "localhost"
        connect_headers: Headers = {
            ":method": "CONNECT",
            ":protocol": "webtransport",
            ":scheme": "https",
            ":path": path,
            ":authority": authority,
            **headers_dict,
        }
        stream_id = self._quic.get_next_available_stream_id(is_unidirectional=False)
        self._h3.send_headers(stream_id=stream_id, headers=connect_headers, end_stream=False)

        session_info = WebTransportSessionInfo(
            session_id=session_id,
            stream_id=stream_id,
            state=SessionState.CONNECTING,
            created_at=get_timestamp(),
            path=path,
            headers=headers_dict,
        )
        self._register_session(session_id=session_id, session_info=session_info)
        self._trigger_transmission()
        logger.info(
            "Initiated WebTransport session: %s on control stream %d",
            session_id,
            stream_id,
        )
        return session_id, stream_id

    def create_webtransport_stream(self, *, session_id: SessionId, is_unidirectional: bool = False) -> StreamId:
        """Create a new WebTransport data stream for a session."""
        session_info = self._sessions.get(session_id)
        if not session_info or session_info.state != SessionState.CONNECTED:
            raise ProtocolError(message=f"Session {session_id} not found or not ready")

        if is_unidirectional:
            if session_info.local_streams_uni_opened >= session_info.peer_max_streams_uni:
                self._send_blocked_capsule(session_info=session_info, is_unidirectional=True)
                raise FlowControlError(message="Unidirectional stream limit reached for session.")
            session_info.local_streams_uni_opened += 1
        else:
            if session_info.local_streams_bidi_opened >= session_info.peer_max_streams_bidi:
                self._send_blocked_capsule(session_info=session_info, is_unidirectional=False)
                raise FlowControlError(message="Bidirectional stream limit reached for session.")
            session_info.local_streams_bidi_opened += 1

        stream_id = self._h3.create_webtransport_stream(
            session_id=session_info.stream_id, is_unidirectional=is_unidirectional
        )
        direction = StreamDirection.SEND_ONLY if is_unidirectional else StreamDirection.BIDIRECTIONAL
        self._register_stream(session_id=session_id, stream_id=stream_id, direction=direction)
        self._trigger_transmission()
        logger.debug("Created WebTransport stream %d (%s)", stream_id, direction)
        return stream_id

    async def establish_session(
        self, *, path: str, headers: Headers | None = None, timeout: float = 30.0
    ) -> tuple[SessionId, StreamId]:
        """Establish a WebTransport session with a specified timeout."""
        if not self.is_connected:
            raise ConnectionError(message="Protocol not connected")

        with Timer(name="establish_session") as timer:
            session_id, stream_id = await asyncio.wait_for(
                self.create_webtransport_session(path=path, headers=headers),
                timeout=timeout,
            )

            def session_ready_condition(event: Event) -> bool:
                return isinstance(event.data, dict) and event.data.get("session_id") == session_id

            await self.wait_for(
                event_type=EventType.SESSION_READY,
                timeout=timeout,
                condition=session_ready_condition,
            )
            logger.info(
                "WebTransport session established in %.2fs: %s",
                timer.elapsed,
                session_id,
            )
            return session_id, stream_id

    async def handle_quic_event(self, *, event: QuicEvent) -> None:
        """Process a QUIC event through the H3 engine and handle results."""
        if self._connection_state == ConnectionState.CLOSED:
            return

        if isinstance(event, StreamReset):
            await self._handle_stream_reset(event=event)

        h3_events = await self._h3.handle_event(event=event)
        for h3_event in h3_events:
            await self._handle_h3_event(h3_event=h3_event)

        self._trigger_transmission()

    async def read_stream_complete(self, *, stream_id: StreamId, timeout: float = 30.0) -> bytes:
        """Receive all data from a stream until it is ended."""
        chunks: list[bytes] = []
        future = asyncio.get_running_loop().create_future()

        async def data_handler(event: Event) -> None:
            if future.done():
                return
            if event.data:
                chunks.append(event.data.get("data", b""))
                if event.data.get("end_stream"):
                    future.set_result(None)

        event_name = f"stream_data_received:{stream_id}"
        self.on(event_type=event_name, handler=data_handler)
        try:
            await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(message=f"Timeout waiting for stream {stream_id} to end") from None
        finally:
            self.off(event_type=event_name, handler=data_handler)
        return b"".join(chunks)

    def send_webtransport_datagram(self, *, session_id: SessionId, data: bytes) -> None:
        """Send a WebTransport datagram for a session."""
        session_info = self._sessions.get(session_id)
        if not session_info or session_info.state != SessionState.CONNECTED:
            raise ProtocolError(message=f"Session {session_id} not found or not ready")

        self._h3.send_datagram(stream_id=session_info.stream_id, data=data)
        self._stats["bytes_sent"] += len(data)
        self._stats["datagrams_sent"] += 1
        self._trigger_transmission()

    def send_webtransport_stream_data(self, *, stream_id: StreamId, data: bytes, end_stream: bool = False) -> None:
        """Send data on a specific WebTransport stream."""
        stream_info = self._streams.get(stream_id)
        if not stream_info or stream_info.state in (
            StreamState.HALF_CLOSED_LOCAL,
            StreamState.CLOSED,
        ):
            raise ProtocolError(message=f"Stream {stream_id} not found or not writable")

        session_info = self._sessions.get(stream_info.session_id)
        if not session_info:
            raise ProtocolError(message=f"No session found for stream {stream_id}")

        data_len = len(data)
        if session_info.local_data_sent + data_len > session_info.peer_max_data:
            self._send_blocked_capsule(session_info=session_info, is_data=True)
            raise FlowControlError(message="Session data limit reached.")
        session_info.local_data_sent += data_len

        self._h3.send_data(stream_id=stream_id, data=data, end_stream=end_stream)
        self._stats["bytes_sent"] += data_len
        stream_info.bytes_sent += data_len
        self._trigger_transmission()

        if end_stream:
            self._update_stream_state_on_send_end(stream_id=stream_id)

    def get_all_sessions(self) -> list[WebTransportSessionInfo]:
        """Get a list of all current sessions."""
        return list(self._sessions.values())

    def get_health_status(self) -> dict[str, Any]:
        """Get the overall health status of the protocol handler."""
        stats = self.stats
        sessions = self.get_all_sessions()
        streams = list(self._streams.values())
        active_sessions = sum(1 for s in sessions if s.state == SessionState.CONNECTED)
        active_streams = sum(1 for s in streams if s.state == StreamState.OPEN)
        error_rate = stats.get("errors", 0) / max(1, stats.get("sessions_created", 1))

        health_status = "healthy"
        if error_rate > 0.1:
            health_status = "degraded"
        elif not self.is_connected:
            health_status = "unhealthy"

        return {
            "status": health_status,
            "connection_state": self.connection_state,
            "active_sessions": active_sessions,
            "active_streams": active_streams,
            "total_sessions": len(sessions),
            "total_streams": len(streams),
            "error_rate": error_rate,
            "last_activity": stats.get("last_activity"),
            "uptime": (get_timestamp() - stats["connected_at"]) if stats.get("connected_at") else 0.0,
        }

    def get_session_info(self, *, session_id: SessionId) -> WebTransportSessionInfo | None:
        """Get information about a specific session."""
        return self._sessions.get(session_id)

    async def recover_session(self, *, session_id: SessionId, max_retries: int = 3) -> bool:
        """Attempt to recover a failed session by creating a new one."""
        validate_session_id(session_id=session_id)
        session_info = self.get_session_info(session_id=session_id)
        if not session_info:
            return False

        for attempt in range(max_retries):
            try:
                new_session_id, _ = await self.create_webtransport_session(
                    path=session_info.path, headers=session_info.headers
                )
                logger.info(
                    "Recovered session %s as new session %s (attempt %d)",
                    session_id,
                    new_session_id,
                    attempt + 1,
                )
                return True
            except Exception as e:
                logger.warning(
                    "Session recovery attempt %d failed: %s",
                    attempt + 1,
                    e,
                    exc_info=True,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
        return False

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
                            self.abort_stream(
                                stream_id=event.stream_id, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED
                            )
                await asyncio.sleep(self._config.pending_event_ttl)
        except asyncio.CancelledError:
            pass

    def _cleanup_session(self, *, session_id: SessionId) -> None:
        """Remove a session and all its associated streams."""
        if session_info := self._sessions.pop(session_id, None):
            self._session_control_streams.pop(session_info.stream_id, None)
            stream_ids_to_reset = list(self._session_owned_streams.pop(session_id, set()))
            for stream_id in stream_ids_to_reset:
                if stream_id in self._streams:
                    self.abort_stream(stream_id=stream_id, error_code=ErrorCodes.WT_SESSION_GONE)
            logger.info("Cleaned up session %s and its associated streams.", session_id)

    def _cleanup_stream(self, *, stream_id: StreamId) -> None:
        """Remove a single stream from internal tracking."""
        if self._streams.pop(stream_id, None):
            session_id = self._data_stream_to_session.pop(stream_id, None)
            if session_id and session_id in self._session_owned_streams:
                self._session_owned_streams[session_id].discard(stream_id)
            asyncio.create_task(self.emit(event_type=f"stream_closed:{stream_id}"))

    def _create_capsule_received_handler(self) -> EventHandler:
        """Create a handler for capsule received events."""

        async def capsule_handler(event: Event) -> None:
            if isinstance(event, CapsuleReceived):
                await self._on_capsule_received(event)

        return capsule_handler

    async def _handle_datagram_received(self, *, event: DatagramReceived) -> None:
        """Handle a datagram received from the H3 engine."""
        if connection := self.connection:
            if hasattr(connection, "record_activity"):
                connection.record_activity()
        self._last_activity = get_timestamp()

        session_id = self._session_control_streams.get(event.stream_id)
        if session_id and self._sessions.get(session_id):
            self._stats["bytes_received"] += len(event.data)
            self._stats["datagrams_received"] += 1
            await self.emit(
                event_type=EventType.DATAGRAM_RECEIVED,
                data={"session_id": session_id, "data": event.data},
            )
        elif self._config.pending_event_ttl > 0:
            if self._pending_events_count >= self._config.max_total_pending_events:
                logger.warning("Global pending event buffer full (%d), dropping datagram.", self._pending_events_count)
                return
            if len(self._pending_events.get(event.stream_id, [])) >= self._config.max_pending_events_per_session:
                logger.warning("Pending event buffer full for session stream %d, dropping datagram.", event.stream_id)
                return

            logger.debug("Buffering datagram for unknown session stream %d", event.stream_id)
            self._pending_events[event.stream_id].append((get_timestamp(), event))
            self._pending_events_count += 1

    async def _handle_h3_event(self, *, h3_event: H3Event) -> None:
        """Route H3 events to their specific handlers."""
        match h3_event:
            case HeadersReceived():
                await self._handle_session_headers(event=h3_event)
            case WebTransportStreamDataReceived():
                await self._handle_webtransport_stream_data(event=h3_event)
            case DatagramReceived():
                await self._handle_datagram_received(event=h3_event)
            case CapsuleReceived() as capsule_event:
                await self._on_capsule_received(capsule_event)
            case _:
                logger.debug("Ignoring unhandled H3 event: %s", type(h3_event))

    async def _handle_session_headers(self, *, event: HeadersReceived) -> None:
        """Handle HEADERS frames for session negotiation."""
        if connection := self.connection:
            if hasattr(connection, "record_activity"):
                connection.record_activity()
        self._last_activity = get_timestamp()
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
                        await self.emit(event_type=EventType.SESSION_READY, data=session.to_dict())
                        self._process_pending_events(connect_stream_id=event.stream_id)
                    elif session_id:
                        status = headers_dict.get(":status", "unknown")
                        logger.error("Session %s creation failed with status %s", session_id, status)
                        await self.emit(
                            event_type=EventType.SESSION_CLOSED,
                            data={
                                "session_id": session_id,
                                "code": 1,
                                "reason": f"HTTP status {status}",
                            },
                        )
                        self._cleanup_session(session_id=session_id)
            case (False, "CONNECT", "webtransport"):
                my_limit = 1
                if (connection := self.connection) and isinstance(connection.config, ServerConfig):
                    my_limit = connection.config.max_sessions

                if len(self._sessions) >= my_limit:
                    logger.warning(
                        "Session limit (%d) exceeded. Rejecting new session on stream %d",
                        my_limit,
                        event.stream_id,
                    )
                    self._quic.reset_stream(stream_id=event.stream_id, error_code=ErrorCodes.H3_REQUEST_REJECTED)
                    self._trigger_transmission()
                    return

                session_id = generate_session_id()
                app_headers = headers_dict
                session_info = WebTransportSessionInfo(
                    session_id=session_id,
                    stream_id=event.stream_id,
                    state=SessionState.CONNECTING,
                    created_at=get_timestamp(),
                    path=app_headers.get(":path", "/"),
                    headers=app_headers,
                )
                self._register_session(session_id=session_id, session_info=session_info)
                self._process_pending_events(connect_stream_id=event.stream_id)
                event_data = session_info.to_dict()
                if connection := self.connection:
                    event_data["connection"] = connection
                logger.info(
                    "Received WebTransport session request: %s for path '%s'",
                    session_id,
                    session_info.path,
                )
                await self.emit(event_type=EventType.SESSION_REQUEST, data=event_data)
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
                    self.abort_stream(stream_id=event.stream_id, error_code=ErrorCodes.H3_REQUEST_REJECTED)

    async def _handle_stream_reset(self, *, event: StreamReset) -> None:
        """Handle a reset stream event."""
        if session_id := self._session_control_streams.get(event.stream_id):
            logger.info(
                "Session %s closed due to control stream %d reset.",
                session_id,
                event.stream_id,
            )
            await self.emit(
                event_type=EventType.SESSION_CLOSED,
                data={
                    "session_id": session_id,
                    "code": event.error_code,
                    "reason": "Control stream reset",
                },
            )
            self._cleanup_session(session_id=session_id)
        else:
            self._cleanup_stream(stream_id=event.stream_id)

    async def _handle_webtransport_stream_data(self, *, event: WebTransportStreamDataReceived) -> None:
        """Handle data received on a WebTransport data stream."""
        if connection := self.connection:
            if hasattr(connection, "record_activity"):
                connection.record_activity()
        stream_id = event.stream_id
        session_stream_id = event.session_id

        session_id = self._session_control_streams.get(session_stream_id)
        if not session_id:
            if self._config.pending_event_ttl > 0:
                if self._pending_events_count >= self._config.max_total_pending_events:
                    logger.warning(
                        "Global pending event buffer full (%d), rejecting stream %d.",
                        self._pending_events_count,
                        stream_id,
                    )
                    self.abort_stream(stream_id=stream_id, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)
                    return
                if len(self._pending_events.get(session_stream_id, [])) >= self._config.max_pending_events_per_session:
                    logger.warning(
                        "Pending event buffer full for session stream %d, rejecting stream %d.",
                        session_stream_id,
                        stream_id,
                    )
                    self.abort_stream(stream_id=stream_id, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)
                    return

                logger.debug("Buffering stream data for unknown session stream %d", session_stream_id)
                self._pending_events[session_stream_id].append((get_timestamp(), event))
                self._pending_events_count += 1
            elif self._quic._state not in (
                QuicConnectionState.CLOSING,
                QuicConnectionState.DRAINING,
            ):
                logger.error(
                    "No session mapping found for session_stream_id %d on new stream %d.",
                    session_stream_id,
                    stream_id,
                )
            return

        session_info = self._sessions[session_id]
        session_info.peer_data_sent += len(event.data)

        if stream_id not in self._data_stream_to_session:
            direction = protocol_utils.get_stream_direction_from_id(stream_id=stream_id, is_client=self._is_client)
            self._register_stream(session_id=session_id, stream_id=stream_id, direction=direction)

            if protocol_utils.is_unidirectional_stream(stream_id=stream_id):
                session_info.peer_streams_uni_opened += 1
            else:
                session_info.peer_streams_bidi_opened += 1

            event_data = self._streams[stream_id].to_dict()
            event_data["initial_payload"] = {
                "data": event.data,
                "end_stream": event.stream_ended,
            }
            await self.emit(event_type=EventType.STREAM_OPENED, data=event_data)
        else:
            await self.emit(
                event_type=f"stream_data_received:{stream_id}",
                data={"data": event.data, "end_stream": event.stream_ended},
            )

        await self._update_local_flow_control(session_id=session_id)

    async def _on_capsule_received(self, event: CapsuleReceived) -> None:
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
                        await self.emit(
                            event_type=EventType.SESSION_MAX_DATA_UPDATED,
                            data={"session_id": session_id, "max_data": new_limit},
                        )
                    elif new_limit < session_info.peer_max_data:
                        raise ProtocolError(message="Flow control limit decreased for MAX_DATA")
                case constants.WT_MAX_STREAMS_BIDI_TYPE:
                    new_limit = buf.pull_uint_var()
                    if new_limit > session_info.peer_max_streams_bidi:
                        session_info.peer_max_streams_bidi = new_limit
                        await self.emit(
                            event_type=EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                            data={
                                "session_id": session_id,
                                "max_streams_bidi": new_limit,
                            },
                        )
                    elif new_limit < session_info.peer_max_streams_bidi:
                        raise ProtocolError(message="Flow control limit decreased for MAX_STREAMS_BIDI")
                case constants.WT_MAX_STREAMS_UNI_TYPE:
                    new_limit = buf.pull_uint_var()
                    if new_limit > session_info.peer_max_streams_uni:
                        session_info.peer_max_streams_uni = new_limit
                        await self.emit(
                            event_type=EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                            data={
                                "session_id": session_id,
                                "max_streams_uni": new_limit,
                            },
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
                    logger.info(
                        "Received CLOSE_SESSION capsule: code=%d reason=%s",
                        app_code,
                        reason,
                    )
                    await self.emit(
                        event_type=EventType.SESSION_CLOSED,
                        data={
                            "session_id": session_id,
                            "code": app_code,
                            "reason": reason,
                        },
                    )
                    self._cleanup_session(session_id=session_id)

                case constants.DRAIN_WEBTRANSPORT_SESSION_TYPE:
                    logger.info("Received DRAIN_SESSION capsule for session %s", session_id)
                    await self.emit(
                        event_type=EventType.SESSION_DRAINING,
                        data={"session_id": session_id},
                    )

        except BufferReadError:
            logger.warning("Could not parse flow control capsule for session %s", session_id)

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

    async def _process_buffered_events(self, events: list[tuple[float, H3Event]]) -> None:
        """Asynchronously process a list of buffered events."""
        for _, event in events:
            if isinstance(event, WebTransportStreamDataReceived):
                await self._handle_webtransport_stream_data(event=event)
            elif isinstance(event, DatagramReceived):
                await self._handle_datagram_received(event=event)

    def _process_pending_events(self, *, connect_stream_id: StreamId) -> None:
        """Check for and process any buffered events for a newly established session."""
        if events_to_process := self._pending_events.pop(connect_stream_id, None):
            self._pending_events_count -= len(events_to_process)
            logger.debug(
                "Processing %d buffered events for session stream %d", len(events_to_process), connect_stream_id
            )
            asyncio.create_task(self._process_buffered_events(events_to_process))

    def _register_session(self, *, session_id: SessionId, session_info: WebTransportSessionInfo) -> None:
        """Add a new session to internal tracking."""
        self._sessions[session_id] = session_info
        self._session_control_streams[session_info.stream_id] = session_id
        session_info.local_max_data = self._config.initial_max_data
        session_info.local_max_streams_bidi = self._config.initial_max_streams_bidi
        session_info.local_max_streams_uni = self._config.initial_max_streams_uni
        session_info.peer_max_data = self._peer_initial_max_data
        session_info.peer_max_streams_bidi = self._peer_initial_max_streams_bidi
        session_info.peer_max_streams_uni = self._peer_initial_max_streams_uni
        self._stats["sessions_created"] += 1

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
            stream_id=session_info.stream_id,
            capsule_data=capsule_header + payload,
        )

    def _send_max_capsule(self, *, session_info: WebTransportSessionInfo, capsule_type: int, value: int) -> None:
        """Send a WT_MAX_DATA or WT_MAX_STREAMS capsule."""
        payload = encode_uint_var(value)
        capsule_header = encode_uint_var(capsule_type) + encode_uint_var(len(payload))
        self._h3.send_capsule(
            stream_id=session_info.stream_id,
            capsule_data=capsule_header + payload,
        )

    def _teardown_event_handlers(self) -> None:
        """Remove all event listeners to prevent memory leaks."""
        if self._h3:
            self._h3.off(event_type=EventType.SETTINGS_RECEIVED, handler=self._on_settings_received)
            self._h3.off(event_type=EventType.CAPSULE_RECEIVED, handler=self._capsule_received_handler)

    def _trigger_transmission(self) -> None:
        """Trigger the underlying QUIC connection to send pending data."""
        if connection := self.connection:
            if hasattr(connection, "_transmit"):
                connection._transmit()

    async def _update_local_flow_control(self, *, session_id: SessionId) -> None:
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

    def _update_stream_state_on_receive_end(self, *, stream_id: StreamId) -> None:
        """Update stream state when its receiving side is closed."""
        if not (stream_info := self._streams.get(stream_id)):
            return

        new_state = StreamState.HALF_CLOSED_REMOTE
        if stream_info.state == StreamState.HALF_CLOSED_LOCAL:
            new_state = StreamState.CLOSED
        stream_info.state = new_state
        if new_state == StreamState.CLOSED:
            self._cleanup_stream(stream_id=stream_id)

    def _update_stream_state_on_send_end(self, *, stream_id: StreamId) -> None:
        """Update stream state when its sending side is closed."""
        if not (stream_info := self._streams.get(stream_id)):
            return

        new_state = StreamState.HALF_CLOSED_LOCAL
        if stream_info.state == StreamState.HALF_CLOSED_REMOTE:
            new_state = StreamState.CLOSED
        stream_info.state = new_state
        if new_state == StreamState.CLOSED:
            self._cleanup_stream(stream_id=stream_id)
