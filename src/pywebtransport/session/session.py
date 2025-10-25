"""Core object representing a logical WebTransport session."""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

from pywebtransport.config import ClientConfig
from pywebtransport.connection import WebTransportConnection
from pywebtransport.constants import (
    DEFAULT_MAX_INCOMING_STREAMS,
    DEFAULT_MAX_STREAMS,
    DEFAULT_STREAM_CLEANUP_INTERVAL,
    DEFAULT_STREAM_CREATION_TIMEOUT,
)
from pywebtransport.datagram import WebTransportDatagramTransport
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import FlowControlError, SessionError, StreamError, TimeoutError, session_not_ready
from pywebtransport.manager.stream import StreamManager, StreamType
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.types import EventType, Headers, SessionId, SessionState, StreamDirection, StreamId
from pywebtransport.utils import format_duration, get_logger, get_timestamp

__all__: list[str] = ["SessionDiagnostics", "SessionStats", "WebTransportSession"]

logger = get_logger(name=__name__)


@dataclass(frozen=True, kw_only=True)
class SessionDiagnostics:
    """A structured, immutable snapshot of a session's health."""

    stats: SessionStats
    state: SessionState
    is_connection_active: bool
    datagram_receive_buffer_size: int
    send_credit_available: int
    receive_credit_available: int

    @property
    def issues(self) -> list[str]:
        """Get a list of potential issues based on the current diagnostics."""
        issues: list[str] = []
        stats = self.stats

        if self.state not in [SessionState.CONNECTED, SessionState.CLOSED]:
            issues.append(f"Session stuck in {self.state} state")

        total_operations = stats.streams_created + stats.datagrams_sent
        total_errors = stats.stream_errors + stats.protocol_errors
        if total_operations > 50 and (total_errors / total_operations) > 0.1:
            issues.append(f"High error rate: {total_errors}/{total_operations}")

        if stats.uptime > 3600 and stats.active_streams == 0:
            issues.append("Session appears stale (long uptime with no active streams)")

        if not self.is_connection_active:
            issues.append("Underlying connection not available or not connected")

        if self.datagram_receive_buffer_size > 100:
            issues.append(
                f"Large datagram receive buffer ({self.datagram_receive_buffer_size}) indicates slow processing."
            )

        return issues


@dataclass(kw_only=True)
class SessionStats:
    """Statistics for a WebTransport session."""

    session_id: SessionId
    created_at: float
    ready_at: float | None = None
    closed_at: float | None = None
    streams_created: int = 0
    streams_closed: int = 0
    stream_errors: int = 0
    bidirectional_streams: int = 0
    unidirectional_streams: int = 0
    datagrams_sent: int = 0
    datagrams_received: int = 0
    protocol_errors: int = 0

    @property
    def active_streams(self) -> int:
        """Get the number of currently active streams."""
        return self.streams_created - self.streams_closed

    @property
    def uptime(self) -> float:
        """Get the session uptime in seconds."""
        if not self.ready_at:
            return 0.0

        end_time = self.closed_at or get_timestamp()
        return end_time - self.ready_at

    def to_dict(self) -> dict[str, Any]:
        """Convert session statistics to a dictionary."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "ready_at": self.ready_at,
            "closed_at": self.closed_at,
            "uptime": self.uptime,
            "streams_created": self.streams_created,
            "streams_closed": self.streams_closed,
            "active_streams": self.active_streams,
            "bidirectional_streams": self.bidirectional_streams,
            "unidirectional_streams": self.unidirectional_streams,
            "datagrams_sent": self.datagrams_sent,
            "datagrams_received": self.datagrams_received,
            "stream_errors": self.stream_errors,
            "protocol_errors": self.protocol_errors,
        }


class WebTransportSession(EventEmitter):
    """A long-lived logical connection for streams and datagrams."""

    _datagram_transport: WebTransportDatagramTransport
    path_params: tuple[str, ...] = ()

    def __init__(
        self,
        connection: WebTransportConnection,
        *,
        session_id: SessionId,
        max_streams: int = DEFAULT_MAX_STREAMS,
        max_incoming_streams: int = DEFAULT_MAX_INCOMING_STREAMS,
        stream_cleanup_interval: float = DEFAULT_STREAM_CLEANUP_INTERVAL,
        path: str | None = None,
        headers: Headers | None = None,
        control_stream_id: StreamId | None = None,
    ) -> None:
        """Initialize the WebTransport session."""
        super().__init__()
        self._connection = weakref.ref(connection)
        self._session_id = session_id
        self._state: SessionState = SessionState.CONNECTING
        self._config = connection.config
        self._protocol_handler: WebTransportProtocolHandler | None = connection.protocol_handler
        self.stream_manager: StreamManager | None = None

        self._path: str = path or ""
        self._headers: Headers = headers or {}
        self._control_stream_id: StreamId | None = control_stream_id
        self._created_at = get_timestamp()
        self._ready_at: float | None = None
        self._closed_at: float | None = None
        self._stats = SessionStats(session_id=self._session_id, created_at=self._created_at)

        self._max_streams = max_streams
        self._max_incoming_streams = max_incoming_streams
        self._cleanup_interval = stream_cleanup_interval
        self._incoming_streams: asyncio.Queue[StreamType | None] | None = None

        self._ready_event: asyncio.Event | None = None
        self._closed_event: asyncio.Event | None = None
        self._data_credit_event: asyncio.Event | None = None
        self._bidi_stream_credit_event: asyncio.Event | None = None
        self._uni_stream_credit_event: asyncio.Event | None = None

        self._is_initialized = False
        logger.debug("WebTransportSession.__init__ completed for session %s", session_id)

    @property
    def connection(self) -> WebTransportConnection | None:
        """Get the parent WebTransportConnection."""
        return self._connection()

    @property
    def headers(self) -> Headers:
        """Get a copy of the initial headers for the session."""
        return self._headers.copy()

    @property
    def is_closed(self) -> bool:
        """Check if the session is closed."""
        return self._state == SessionState.CLOSED

    @property
    def is_ready(self) -> bool:
        """Check if the session is ready for communication."""
        return self._state == SessionState.CONNECTED

    @property
    def path(self) -> str:
        """Get the path associated with the session."""
        return self._path

    @property
    def protocol_handler(self) -> WebTransportProtocolHandler | None:
        """Get the underlying protocol handler."""
        return self._protocol_handler

    @property
    def session_id(self) -> SessionId:
        """Get the unique session ID."""
        return self._session_id

    @property
    def state(self) -> SessionState:
        """Get the current session state."""
        return self._state

    async def __aenter__(self) -> Self:
        """Enter async context, initializing and waiting for the session to be ready."""
        if not self._is_initialized:
            await self.initialize()

        await self.ready()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, closing the session."""
        await self.close()

    async def close(self, *, code: int = 0, reason: str = "", close_connection: bool = True) -> None:
        """Close the session and all associated streams."""
        if self._state in (SessionState.CLOSING, SessionState.CLOSED):
            return
        if not self._is_initialized or self._incoming_streams is None or self._closed_event is None:
            raise SessionError(
                message=(
                    "WebTransportSession is not initialized."
                    "Its factory should call 'await session.initialize()' before use."
                )
            )

        self._state = SessionState.CLOSING
        logger.debug("Closing session %s...", self._session_id)
        first_exception: Exception | ExceptionGroup[Exception] | None = None

        try:
            async with asyncio.TaskGroup() as tg:
                if self.stream_manager:
                    tg.create_task(self.stream_manager.shutdown())
                if hasattr(self, "_datagram_transport"):
                    tg.create_task(self._datagram_transport.close())
        except* Exception as eg:
            first_exception = eg
            logger.error(
                "Errors during parallel resource cleanup for %s: %s", self.session_id, eg.exceptions, exc_info=eg
            )

        try:
            if self._incoming_streams:
                await self._incoming_streams.put(None)
            if self._protocol_handler:
                self._protocol_handler.close_webtransport_session(session_id=self._session_id, code=code, reason=reason)
            if close_connection:
                if connection := self.connection:
                    if not connection.is_closed:
                        await connection.close()
        except Exception as e:
            logger.error("Error during serial resource cleanup for %s: %s", self.session_id, e, exc_info=True)
            if first_exception is None:
                first_exception = e
            else:
                existing_exceptions = (
                    first_exception.exceptions if isinstance(first_exception, ExceptionGroup) else (first_exception,)
                )
                new_exceptions = e.exceptions if isinstance(e, ExceptionGroup) else (e,)
                first_exception = ExceptionGroup(
                    "Multiple errors during session close",
                    existing_exceptions + new_exceptions,
                )
        finally:
            self._teardown_event_handlers()
            self._state = SessionState.CLOSED
            self._closed_at = get_timestamp()
            if self._closed_event:
                self._closed_event.set()
            await self.emit(
                event_type=EventType.SESSION_CLOSED,
                data={"session_id": self._session_id, "code": code, "reason": reason},
            )
            logger.info("Session %s is now fully closed.", self._session_id)

        if first_exception:
            raise first_exception

    async def initialize(self) -> None:
        """Initialize asyncio resources for the session."""
        if self._is_initialized:
            return

        def stream_factory_adapter(is_unidirectional: bool) -> Awaitable[StreamId]:
            return self._create_stream_on_protocol(is_unidirectional=is_unidirectional)

        self.stream_manager = StreamManager(
            stream_factory=stream_factory_adapter,
            session_factory=lambda: self,
            max_streams=self._max_streams,
            stream_cleanup_interval=self._cleanup_interval,
        )
        await self.stream_manager.__aenter__()

        self._incoming_streams = asyncio.Queue(maxsize=self._max_incoming_streams)
        self._ready_event = asyncio.Event()
        self._closed_event = asyncio.Event()
        self._data_credit_event = asyncio.Event()
        self._bidi_stream_credit_event = asyncio.Event()
        self._uni_stream_credit_event = asyncio.Event()

        self._setup_event_handlers()
        self._sync_protocol_state()

        self._is_initialized = True

    async def ready(self, *, timeout: float = 30.0) -> None:
        """Wait for the session to become connected."""
        if self.is_ready:
            return
        if not self._is_initialized or self._ready_event is None:
            raise SessionError(
                message=(
                    "WebTransportSession is not initialized."
                    "Its factory should call 'await session.initialize()' before use."
                )
            )

        logger.debug("Session %s waiting for ready event (timeout: %s)", self._session_id, timeout)
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            logger.debug("Session %s ready event received", self._session_id)
        except asyncio.TimeoutError:
            logger.error("Session %s ready timeout after %ss", self._session_id, timeout)
            raise TimeoutError(message=f"Session ready timeout after {timeout}s") from None

    async def wait_closed(self) -> None:
        """Wait for the session to be fully closed."""
        if not self._is_initialized or self._closed_event is None:
            raise SessionError(
                message=(
                    "WebTransportSession is not initialized."
                    "Its factory should call 'await session.initialize()' before use."
                )
            )

        await self._closed_event.wait()

    async def create_bidirectional_stream(self, *, timeout: float | None = None) -> WebTransportStream:
        """Create a new bidirectional stream."""
        if not self.is_ready:
            raise session_not_ready(session_id=self._session_id, current_state=self._state)
        if not self.connection:
            raise SessionError(message=f"Session {self.session_id} has no active connection.")
        if self.stream_manager is None:
            raise SessionError(message="StreamManager is not available.")

        match (timeout, self._config):
            case (t, _) if t is not None:
                effective_timeout = t
            case (_, ClientConfig() as config):
                effective_timeout = config.stream_creation_timeout
            case _:
                effective_timeout = DEFAULT_STREAM_CREATION_TIMEOUT

        try:
            stream = await asyncio.wait_for(
                self.stream_manager.create_bidirectional_stream(),
                timeout=effective_timeout,
            )
            await stream.initialize()
            return stream
        except asyncio.TimeoutError:
            self._stats.stream_errors += 1
            msg = f"Timed out creating bidirectional stream after {effective_timeout}s."
            raise StreamError(message=msg) from None

    async def create_datagram_transport(self) -> WebTransportDatagramTransport:
        """Create a datagram transport for this session."""
        if hasattr(self, "_datagram_transport"):
            return self._datagram_transport

        if self.is_closed:
            raise SessionError(message=f"Session {self.session_id} is closed.")
        if not self.protocol_handler:
            raise SessionError(message="Protocol handler is not available.")

        def sender_callback(data: bytes) -> None:
            if self.protocol_handler:
                self.protocol_handler.send_webtransport_datagram(session_id=self.session_id, data=data)

        max_size = getattr(self.protocol_handler.quic_connection, "_max_datagram_size", 1200)

        transport = WebTransportDatagramTransport(
            session_id=self.session_id,
            datagram_sender=sender_callback,
            max_datagram_size=max_size,
        )
        await transport.initialize()
        self._datagram_transport = transport
        return transport

    async def create_unidirectional_stream(self, *, timeout: float | None = None) -> WebTransportSendStream:
        """Create a new unidirectional stream."""
        if not self.is_ready:
            raise session_not_ready(session_id=self._session_id, current_state=self._state)
        if not self.connection:
            raise SessionError(message=f"Session {self.session_id} has no active connection.")
        if self.stream_manager is None:
            raise SessionError(message="StreamManager is not available.")

        match (timeout, self._config):
            case (t, _) if t is not None:
                effective_timeout = t
            case (_, ClientConfig() as config):
                effective_timeout = config.stream_creation_timeout
            case _:
                effective_timeout = DEFAULT_STREAM_CREATION_TIMEOUT

        try:
            stream = await asyncio.wait_for(
                self.stream_manager.create_unidirectional_stream(),
                timeout=effective_timeout,
            )
            await stream.initialize()
            return stream
        except asyncio.TimeoutError:
            self._stats.stream_errors += 1
            msg = f"Timed out creating unidirectional stream after {effective_timeout}s."
            raise StreamError(message=msg) from None

    async def incoming_streams(self) -> AsyncIterator[StreamType]:
        """Iterate over all incoming streams (both uni- and bidirectional)."""
        if not self._is_initialized or self._incoming_streams is None:
            raise SessionError(
                message=(
                    "WebTransportSession is not initialized."
                    "Its factory should call 'await session.initialize()' before use."
                )
            )

        while self._state not in (SessionState.CLOSING, SessionState.CLOSED):
            try:
                stream = await asyncio.wait_for(self._incoming_streams.get(), timeout=1.0)
                if stream is None:
                    break
                await stream.initialize()
                yield stream
            except asyncio.TimeoutError:
                continue

    async def diagnostics(self) -> SessionDiagnostics:
        """Get a snapshot of the session's diagnostics and statistics."""
        if self.stream_manager:
            manager_stats = await self.stream_manager.get_stats()
            self._stats.streams_created = manager_stats.get("total_created", 0)
            self._stats.streams_closed = manager_stats.get("total_closed", 0)

        if hasattr(self, "_datagram_transport"):
            datagram_diagnostics = self._datagram_transport.diagnostics
            self._stats.datagrams_sent = datagram_diagnostics.stats.datagrams_sent
            self._stats.datagrams_received = datagram_diagnostics.stats.datagrams_received

        datagram_buffer_size = 0
        if hasattr(self, "_datagram_transport"):
            datagram_buffer_size = self._datagram_transport.get_receive_buffer_size()

        connection = self.connection
        is_conn_active = bool(connection and connection.is_connected)

        send_credit, receive_credit = 0, 0
        if connection and connection.protocol_handler:
            if session_info := connection.get_session_info(session_id=self._session_id):
                send_credit = session_info.peer_max_data - session_info.local_data_sent
                receive_credit = session_info.local_max_data - session_info.peer_data_sent

        return SessionDiagnostics(
            stats=self._stats,
            state=self._state,
            is_connection_active=is_conn_active,
            datagram_receive_buffer_size=datagram_buffer_size,
            send_credit_available=send_credit,
            receive_credit_available=receive_credit,
        )

    async def monitor_health(self, *, check_interval: float = 60.0) -> None:
        """Monitor the health of a session continuously until it is closed."""
        logger.debug("Starting health monitoring for session %s", self.session_id)
        try:
            while not self.is_closed:
                if (connection := self.connection) and hasattr(connection, "diagnostics"):
                    last_activity = connection.diagnostics.stats.last_activity
                    if last_activity and (get_timestamp() - last_activity) > 300:
                        logger.warning(
                            "Session %s appears inactive (no connection activity)",
                            self.session_id,
                        )
                await asyncio.sleep(check_interval)
        except asyncio.CancelledError:
            logger.debug("Health monitoring cancelled for session %s", self.session_id)
        except Exception as e:
            logger.error("Session health monitoring error: %s", e, exc_info=True)

    async def _create_stream_on_protocol(self, *, is_unidirectional: bool) -> StreamId:
        """Ask the protocol handler to create a new underlying stream."""
        if not self.protocol_handler:
            raise SessionError(message="Protocol handler is not available to create a stream.")

        while True:
            try:
                return self.protocol_handler.create_webtransport_stream(
                    session_id=self.session_id, is_unidirectional=is_unidirectional
                )
            except FlowControlError:
                if is_unidirectional:
                    if self._uni_stream_credit_event is None:
                        raise
                    self._uni_stream_credit_event.clear()
                    await self._uni_stream_credit_event.wait()
                else:
                    if self._bidi_stream_credit_event is None:
                        raise
                    self._bidi_stream_credit_event.clear()
                    await self._bidi_stream_credit_event.wait()
            except Exception as e:
                self._stats.stream_errors += 1
                raise StreamError(message=f"Protocol handler failed to create stream: {e}") from e

    async def _on_connection_closed(self, event: Event) -> None:
        """Handle the underlying connection being closed."""
        if self._state not in (SessionState.CLOSING, SessionState.CLOSED):
            logger.warning(
                "Session %s closing due to underlying connection loss.",
                self._session_id,
            )
            asyncio.create_task(self.close(reason="Underlying connection closed", close_connection=False))

    async def _on_datagram_received(self, event: Event) -> None:
        """Forward a datagram event to the session's datagram transport."""
        if not (isinstance(event.data, dict) and event.data.get("session_id") == self._session_id):
            return

        if hasattr(self, "_datagram_transport"):
            await self._datagram_transport.receive_from_protocol(data=event.data["data"])

    async def _on_max_data_updated(self, event: Event) -> None:
        """Handle session max data update event."""
        if not self._data_credit_event:
            return
        if isinstance(event.data, dict) and event.data.get("session_id") == self._session_id:
            self._data_credit_event.set()

    async def _on_max_streams_bidi_updated(self, event: Event) -> None:
        """Handle session max bidi streams update event."""
        if not self._bidi_stream_credit_event:
            return
        if isinstance(event.data, dict) and event.data.get("session_id") == self._session_id:
            self._bidi_stream_credit_event.set()

    async def _on_max_streams_uni_updated(self, event: Event) -> None:
        """Handle session max uni streams update event."""
        if not self._uni_stream_credit_event:
            return
        if isinstance(event.data, dict) and event.data.get("session_id") == self._session_id:
            self._uni_stream_credit_event.set()

    async def _on_session_closed(self, event: Event) -> None:
        """Handle the event indicating the session was closed remotely."""
        if isinstance(event.data, dict) and event.data.get("session_id") == self._session_id:
            if self._state not in (SessionState.CLOSING, SessionState.CLOSED):
                logger.warning("Session %s closed remotely.", self._session_id)
                await self.close(
                    code=event.data.get("code", 0),
                    reason=event.data.get("reason", ""),
                )

    async def _on_session_ready(self, event: Event) -> None:
        """Handle the event indicating the session is ready."""
        if not self._ready_event:
            return

        if isinstance(event.data, dict) and event.data.get("session_id") == self._session_id:
            logger.info("SESSION_READY event received for session %s", self._session_id)
            self._state = SessionState.CONNECTED
            self._ready_at = get_timestamp()
            self._stats.ready_at = self._ready_at
            if "path" in event.data:
                self._path = event.data["path"]
            if "headers" in event.data:
                self._headers = event.data["headers"]
            if "control_stream_id" in event.data:
                self._control_stream_id = event.data["control_stream_id"]
            self._ready_event.set()
            await self.emit(
                event_type=EventType.SESSION_READY,
                data={"session_id": self._session_id},
            )
            logger.info("Session %s is ready (path='%s').", self._session_id, self._path)

    async def _on_stream_opened(self, event: Event) -> None:
        """Handle an incoming stream initiated by the remote peer."""
        if not (isinstance(event.data, dict) and event.data.get("session_id") == self._session_id):
            return
        if not self._incoming_streams:
            return

        stream_id = event.data.get("stream_id")
        direction = event.data.get("direction")
        if stream_id is None or direction is None:
            logger.error("STREAM_OPENED event is missing required data for session %s.", self.session_id)
            return

        try:
            stream: StreamType
            match direction:
                case StreamDirection.BIDIRECTIONAL:
                    stream = WebTransportStream(session=self, stream_id=stream_id)
                case _:
                    stream = WebTransportReceiveStream(session=self, stream_id=stream_id)

            await stream.initialize()
            if initial_payload := event.data.get("initial_payload"):
                payload_event = Event(
                    type=EventType.STREAM_DATA_RECEIVED, data={**initial_payload, "stream_id": stream_id}
                )
                await stream._on_data_received(event=payload_event)

            if self.stream_manager is None:
                raise SessionError(message="StreamManager is not available.")
            await self.stream_manager.add_stream(stream=stream)
            await self._incoming_streams.put(stream)

            logger.debug("Accepted incoming %s stream %d for session %s", direction, stream_id, self.session_id)
        except Exception as e:
            self._stats.stream_errors += 1
            logger.error("Error handling newly opened stream %d: %s", stream_id, e, exc_info=True)

    def _setup_event_handlers(self) -> None:
        """Set up event handlers for the session."""
        logger.debug("Setting up event handlers for session %s", self._session_id)
        if self.protocol_handler:
            self.protocol_handler.on(event_type=EventType.SESSION_READY, handler=self._on_session_ready)
            self.protocol_handler.on(event_type=EventType.SESSION_CLOSED, handler=self._on_session_closed)
            self.protocol_handler.on(event_type=EventType.STREAM_OPENED, handler=self._on_stream_opened)
            self.protocol_handler.on(
                event_type=EventType.DATAGRAM_RECEIVED,
                handler=self._on_datagram_received,
            )
            self.protocol_handler.on(event_type=EventType.SESSION_MAX_DATA_UPDATED, handler=self._on_max_data_updated)
            self.protocol_handler.on(
                event_type=EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                handler=self._on_max_streams_bidi_updated,
            )
            self.protocol_handler.on(
                event_type=EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                handler=self._on_max_streams_uni_updated,
            )
        else:
            logger.warning("No protocol handler available for session %s", self._session_id)

        if connection := self.connection:
            if connection.is_closed:
                logger.warning("Session %s created on an already closed connection.", self.session_id)
                asyncio.create_task(
                    self.close(
                        reason="Connection already closed upon session creation",
                        close_connection=False,
                    )
                )
            else:
                connection.once(
                    event_type=EventType.CONNECTION_CLOSED,
                    handler=self._on_connection_closed,
                )

    def _sync_protocol_state(self) -> None:
        """Synchronize session state from the underlying protocol layer."""
        logger.debug("Syncing protocol state for session %s", self._session_id)
        if not (connection := self.connection):
            return
        if not self._ready_event:
            logger.warning(
                "Cannot sync state for session %s, session not initialized.",
                self._session_id,
            )
            return

        if session_info := connection.get_session_info(session_id=self._session_id):
            if session_info.state == SessionState.CONNECTED:
                logger.info("Syncing ready state for session %s (protocol already connected)", self._session_id)
                self._state = SessionState.CONNECTED
                self._ready_at = session_info.ready_at or get_timestamp()
                if not self._path:
                    self._path = session_info.path
                if not self._headers:
                    self._headers = session_info.headers.copy() if session_info.headers else {}
                if self._control_stream_id is None:
                    self._control_stream_id = session_info.control_stream_id
                self._ready_event.set()

    def _teardown_event_handlers(self) -> None:
        """Unsubscribe from all events to prevent memory leaks."""
        if self.protocol_handler:
            self.protocol_handler.off(event_type=EventType.SESSION_READY, handler=self._on_session_ready)
            self.protocol_handler.off(event_type=EventType.SESSION_CLOSED, handler=self._on_session_closed)
            self.protocol_handler.off(event_type=EventType.STREAM_OPENED, handler=self._on_stream_opened)
            self.protocol_handler.off(
                event_type=EventType.DATAGRAM_RECEIVED,
                handler=self._on_datagram_received,
            )
            self.protocol_handler.off(event_type=EventType.SESSION_MAX_DATA_UPDATED, handler=self._on_max_data_updated)
            self.protocol_handler.off(
                event_type=EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                handler=self._on_max_streams_bidi_updated,
            )
            self.protocol_handler.off(
                event_type=EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                handler=self._on_max_streams_uni_updated,
            )

        if connection := self.connection:
            connection.off(
                event_type=EventType.CONNECTION_CLOSED,
                handler=self._on_connection_closed,
            )

    def __str__(self) -> str:
        """Format a concise string representation of the session."""
        stats = self._stats
        uptime_str = format_duration(seconds=stats.uptime)

        return (
            f"Session({self.session_id[:12]}..., "
            f"state={self.state}, "
            f"path={self.path}, "
            f"uptime={uptime_str}, "
            f"streams={stats.active_streams}/{stats.streams_created}, "
            f"datagrams={stats.datagrams_sent}/{stats.datagrams_received})"
        )
