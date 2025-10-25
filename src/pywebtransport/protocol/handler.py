"""Core orchestrator for the WebTransport protocol logic."""

from __future__ import annotations

import weakref
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent, StreamReset

from pywebtransport.config import ClientConfig, ServerConfig
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import FlowControlError, ProtocolError
from pywebtransport.protocol._pending_event_manager import _PendingEventManager
from pywebtransport.protocol._session_tracker import _ProtocolSessionTracker
from pywebtransport.protocol._stream_tracker import _ProtocolStreamTracker
from pywebtransport.protocol.events import (
    CapsuleReceived,
    DatagramReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.protocol.h3_engine import WebTransportH3Engine
from pywebtransport.types import ConnectionState, EventType, Headers, SessionId, SessionState, StreamId, StreamState
from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.connection import WebTransportConnection


__all__: list[str] = ["WebTransportProtocolHandler"]

logger = get_logger(name=__name__)


class WebTransportProtocolHandler(EventEmitter):
    """Orchestrate WebTransport sessions and streams over a QUIC connection."""

    def __init__(
        self,
        *,
        quic_connection: QuicConnection,
        trigger_transmission: Callable[[], None],
        is_client: bool = True,
        connection: WebTransportConnection | None = None,
    ) -> None:
        """Initialize the WebTransport protocol handler."""
        super().__init__()
        self._quic = quic_connection
        self._is_client = is_client
        self._connection_ref = weakref.ref(connection) if connection else None
        self._trigger_transmission_callback = trigger_transmission
        self._config = connection.config if connection else (ClientConfig() if is_client else ServerConfig())
        self._h3: WebTransportH3Engine = WebTransportH3Engine(quic=self._quic, config=self._config)

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

        def _emit_wrapper(event_type: EventType, data: Any) -> Coroutine[Any, Any, None]:
            return self.emit(event_type=event_type, data=data)

        self._session_tracker = _ProtocolSessionTracker(
            config=self._config,
            is_client=self._is_client,
            quic=self._quic,
            h3=self._h3,
            stats=self._stats,
            emit_event=_emit_wrapper,
            trigger_transmission=self._trigger_transmission,
            cleanup_streams_for_session_by_id=self._cleanup_streams_for_session_by_id,
            abort_stream=self.abort_stream,
        )
        self._stream_tracker = _ProtocolStreamTracker(
            is_client=self._is_client,
            quic=self._quic,
            h3=self._h3,
            stats=self._stats,
            session_tracker=self._session_tracker,
            emit_event=_emit_wrapper,
            trigger_transmission=self._trigger_transmission,
        )
        self._pending_event_manager = _PendingEventManager(
            config=self._config,
            abort_stream=self.abort_stream,
            process_buffered_events=self._process_buffered_events,
        )

        self._h3.on(event_type=EventType.CAPSULE_RECEIVED, handler=self._on_capsule_received)

        self._connection_state: ConnectionState = ConnectionState.IDLE
        self._last_activity = get_timestamp()
        logger.debug("WebTransport protocol handler initialized (client=%s)", is_client)

    @property
    def quic_connection(self) -> QuicConnection:
        """Get the underlying aioquic QuicConnection object."""
        return self._quic

    async def close(self) -> None:
        """Close the protocol handler and clean up its resources."""
        if self._connection_state == ConnectionState.CLOSED:
            return

        await self._pending_event_manager.close()

        self._connection_state = ConnectionState.CLOSED
        self._teardown_event_handlers()
        await super().close()

    def connection_established(self) -> None:
        """Signal that the QUIC connection is established."""
        if self._connection_state in [ConnectionState.IDLE, ConnectionState.CONNECTING]:
            self._connection_state = ConnectionState.CONNECTED
            self._stats["connected_at"] = get_timestamp()
            self._pending_event_manager.start()
            logger.info("Connection established.")
            self._trigger_transmission()

    def abort_stream(self, *, stream_id: StreamId, error_code: int) -> None:
        """Abort a stream immediately."""
        self._stream_tracker.abort_stream(stream_id=stream_id, error_code=error_code)

    def accept_webtransport_session(self, *, stream_id: StreamId, session_id: SessionId) -> None:
        """Accept a pending WebTransport session (server-only)."""
        self._session_tracker.accept_webtransport_session(stream_id=stream_id, session_id=session_id)

    def close_webtransport_session(self, *, session_id: SessionId, code: int = 0, reason: str | None = None) -> None:
        """Close a specific WebTransport session."""
        self._session_tracker.close_webtransport_session(session_id=session_id, code=code, reason=reason)

    async def create_webtransport_session(
        self, *, path: str, headers: Headers | None = None
    ) -> tuple[SessionId, StreamId]:
        """Initiate a new WebTransport session (client-only)."""
        return await self._session_tracker.create_webtransport_session(path=path, headers=headers)

    def create_webtransport_stream(self, *, session_id: SessionId, is_unidirectional: bool = False) -> StreamId:
        """Create a new WebTransport data stream for a session."""
        return self._stream_tracker.create_webtransport_stream(
            session_id=session_id, is_unidirectional=is_unidirectional
        )

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

    def reject_session_request(self, *, stream_id: StreamId, status_code: int) -> None:
        """Reject an incoming WebTransport session request (server-only)."""
        self._h3.send_headers(stream_id=stream_id, headers={":status": str(status_code)}, end_stream=True)
        self._trigger_transmission()

    def send_webtransport_datagram(self, *, session_id: SessionId, data: bytes) -> None:
        """Send a WebTransport datagram for a session."""
        session_info = self._session_tracker.get_session_info(session_id=session_id)
        if not session_info or session_info.state != SessionState.CONNECTED:
            raise ProtocolError(message=f"Session {session_id} not found or not ready")

        self._h3.send_datagram(stream_id=session_info.control_stream_id, data=data)

        self._stats["bytes_sent"] += len(data)
        self._stats["datagrams_sent"] += 1
        self._trigger_transmission()

    def send_webtransport_stream_data(self, *, stream_id: StreamId, data: bytes, end_stream: bool = False) -> None:
        """Send data on a specific WebTransport stream."""
        stream_info = self._stream_tracker._streams.get(stream_id)
        if not stream_info or stream_info.state in (
            StreamState.HALF_CLOSED_LOCAL,
            StreamState.CLOSED,
        ):
            raise ProtocolError(message=f"Stream {stream_id} not found or not writable")

        session_info = self._session_tracker.get_session_info(session_id=stream_info.session_id)
        if not session_info:
            raise ProtocolError(message=f"No session found for stream {stream_id}")

        data_len = len(data)
        if session_info.local_data_sent + data_len > session_info.peer_max_data:
            self._session_tracker._send_blocked_capsule(session_info=session_info, is_data=True)
            raise FlowControlError(message="Session data limit reached.")

        session_info.local_data_sent += data_len
        self._h3.send_data(stream_id=stream_id, data=data, end_stream=end_stream)

        self._stats["bytes_sent"] += data_len
        stream_info.bytes_sent += data_len
        self._trigger_transmission()

        if end_stream:
            self._stream_tracker.update_stream_state_on_send_end(stream_id=stream_id)

    def _cleanup_streams_for_session_by_id(self, session_id: SessionId) -> None:
        """Delegate stream cleanup to the stream tracker."""
        self._stream_tracker.cleanup_streams_for_session_by_id(session_id)

    async def _handle_datagram_received(self, *, event: DatagramReceived) -> None:
        """Handle a datagram received from the H3 engine."""
        connection = self._connection_ref() if self._connection_ref else None
        if connection:
            if hasattr(connection, "record_activity"):
                connection.record_activity()
        self._last_activity = get_timestamp()

        session_id = self._session_tracker.get_session_by_control_stream(stream_id=event.stream_id)
        if session_id and self._session_tracker.get_session_info(session_id=session_id):
            self._stats["bytes_received"] += len(event.data)
            self._stats["datagrams_received"] += 1
            await self.emit(event_type=EventType.DATAGRAM_RECEIVED, data={"session_id": session_id, "data": event.data})
        else:
            self._pending_event_manager.buffer_event(session_stream_id=event.stream_id, event=event)

    async def _handle_h3_event(self, *, h3_event: H3Event) -> None:
        """Route H3 events to their specific handlers."""
        match h3_event:
            case HeadersReceived() as event:
                connection = self._connection_ref() if self._connection_ref else None
                session_id = await self._session_tracker.handle_headers_received(event=event, connection=connection)
                if session_id:
                    self._pending_event_manager.process_pending_events(connect_stream_id=event.stream_id)
            case WebTransportStreamDataReceived() as event:
                unhandled_event = await self._stream_tracker.handle_webtransport_stream_data(event=event)
                if unhandled_event:
                    self._pending_event_manager.buffer_event(session_stream_id=event.control_stream_id, event=event)
            case DatagramReceived() as event:
                await self._handle_datagram_received(event=event)
            case CapsuleReceived() as event:
                await self._session_tracker.handle_capsule_received(event=event)
            case _:
                logger.debug("Ignoring unhandled H3 event: %s", type(h3_event))

    async def _handle_stream_reset(self, *, event: StreamReset) -> None:
        """Handle a reset stream event."""
        if self._session_tracker.get_session_by_control_stream(stream_id=event.stream_id):
            await self._session_tracker.handle_stream_reset(stream_id=event.stream_id, error_code=event.error_code)
        else:
            self._stream_tracker.handle_stream_reset(stream_id=event.stream_id)

    async def _on_capsule_received(self, event: Event) -> None:
        """Handle a capsule received event."""
        if isinstance(event.data, CapsuleReceived):
            await self._session_tracker.handle_capsule_received(event=event.data)

    async def _process_buffered_events(self, events: list[tuple[float, H3Event]]) -> None:
        """Asynchronously process a list of buffered events."""
        for _, event in events:
            if isinstance(event, WebTransportStreamDataReceived):
                await self._stream_tracker.handle_webtransport_stream_data(event=event)
            elif isinstance(event, DatagramReceived):
                await self._handle_datagram_received(event=event)

    def _teardown_event_handlers(self) -> None:
        """Remove all event listeners to prevent memory leaks."""
        self._session_tracker.teardown()
        self._h3.off(event_type=EventType.CAPSULE_RECEIVED, handler=self._on_capsule_received)

    def _trigger_transmission(self) -> None:
        """Trigger the underlying QUIC connection to send pending data."""
        self._trigger_transmission_callback()
