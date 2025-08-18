"""
WebTransport session core implementation.
"""

from __future__ import annotations

import asyncio
import weakref
from dataclasses import dataclass
from types import TracebackType
from typing import Any, AsyncIterator, Self, Type

from pywebtransport.config import ClientConfig
from pywebtransport.connection import WebTransportConnection
from pywebtransport.constants import WebTransportConstants
from pywebtransport.datagram import WebTransportDatagramDuplexStream
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import SessionError, StreamError, TimeoutError, session_not_ready
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.stream import StreamManager, WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.types import EventType, Headers, SessionId, SessionState, StreamDirection, StreamId
from pywebtransport.utils import format_duration, get_logger, get_timestamp

__all__ = ["SessionStats", "WebTransportSession"]

logger = get_logger("session.session")

StreamType = WebTransportStream | WebTransportReceiveStream | WebTransportSendStream


@dataclass
class SessionStats:
    """Represents statistics for a WebTransport session."""

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
    def uptime(self) -> float:
        """Get the session uptime in seconds."""
        if not self.ready_at:
            return 0.0

        end_time = self.closed_at or get_timestamp()
        return end_time - self.ready_at

    @property
    def active_streams(self) -> int:
        """Get the number of currently active streams."""
        return self.streams_created - self.streams_closed

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

    def __init__(
        self,
        *,
        connection: WebTransportConnection,
        session_id: SessionId,
        max_streams: int = WebTransportConstants.DEFAULT_MAX_STREAMS,
        max_incoming_streams: int = WebTransportConstants.DEFAULT_MAX_INCOMING_STREAMS,
        stream_cleanup_interval: float = WebTransportConstants.DEFAULT_STREAM_CLEANUP_INTERVAL,
    ):
        """Initialize the WebTransport session."""
        super().__init__()
        self._connection = weakref.ref(connection)
        self._session_id = session_id
        self._max_streams = max_streams
        self._cleanup_interval = stream_cleanup_interval
        self._config = connection.config
        self._control_stream_id: StreamId | None = None
        self._state: SessionState = SessionState.CONNECTING
        self._protocol_handler: WebTransportProtocolHandler | None = connection.protocol_handler
        self._path: str = ""
        self._headers: Headers = {}
        self._created_at = get_timestamp()
        self._ready_at: float | None = None
        self._closed_at: float | None = None
        self._max_incoming_streams = max_incoming_streams
        self.stream_manager: StreamManager | None = None
        self._incoming_streams: asyncio.Queue[StreamType | None] | None = None
        self._datagrams: WebTransportDatagramDuplexStream | None = None
        self._stats = SessionStats(self._session_id, self._created_at)
        self._ready_event: asyncio.Event | None = None
        self._closed_event: asyncio.Event | None = None
        self._is_initialized = False
        logger.debug(f"WebTransportSession.__init__ completed for session {session_id}")

    @property
    def state(self) -> SessionState:
        """Get the current session state."""
        return self._state

    @property
    def is_ready(self) -> bool:
        """Check if the session is ready for communication."""
        return self._state == SessionState.CONNECTED

    @property
    def is_closed(self) -> bool:
        """Check if the session is closed."""
        return self._state == SessionState.CLOSED

    @property
    def session_id(self) -> SessionId:
        """Get the unique session ID."""
        return self._session_id

    @property
    def path(self) -> str:
        """Get the path associated with the session."""
        return self._path

    @property
    def headers(self) -> Headers:
        """Get a copy of the initial headers for the session."""
        return self._headers.copy()

    @property
    def connection(self) -> WebTransportConnection | None:
        """Get the parent WebTransportConnection."""
        return self._connection()

    @property
    def protocol_handler(self) -> WebTransportProtocolHandler | None:
        """Get the underlying protocol handler."""
        return self._protocol_handler

    @property
    async def datagrams(self) -> WebTransportDatagramDuplexStream:
        """Access the datagram stream, creating and initializing it on first access."""
        if self.is_closed:
            raise SessionError(f"Session {self.session_id} is closed, cannot access datagrams.")

        if self._datagrams is None:
            logger.debug(f"Lazily creating datagram stream for session {self.session_id}")
            self._datagrams = WebTransportDatagramDuplexStream(session=self)
            await self._datagrams.initialize()
        return self._datagrams

    async def __aenter__(self) -> Self:
        """Enter async context, initializing and waiting for the session to be ready."""
        if not self._is_initialized:
            await self.initialize()

        await self.ready()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, closing the session."""
        await self.close()

    async def initialize(self) -> None:
        """Initialize asyncio resources for the session."""
        if self._is_initialized:
            return

        self.stream_manager = StreamManager.create(
            session=self,
            max_streams=self._max_streams,
            stream_cleanup_interval=self._cleanup_interval,
        )
        await self.stream_manager.__aenter__()
        self._incoming_streams = asyncio.Queue(maxsize=self._max_incoming_streams)
        self._ready_event = asyncio.Event()
        self._closed_event = asyncio.Event()

        self._setup_event_handlers()
        self._sync_protocol_state()

        self._is_initialized = True

    async def ready(self, *, timeout: float = 30.0) -> None:
        """Wait for the session to become connected."""
        if self.is_ready:
            return
        if not self._is_initialized or self._ready_event is None:
            raise SessionError(
                "WebTransportSession is not initialized."
                "Its factory should call 'await session.initialize()' before use."
            )

        logger.debug(f"Session {self._session_id} waiting for ready event (timeout: {timeout}s)")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            logger.debug(f"Session {self._session_id} ready event received")
        except asyncio.TimeoutError:
            logger.error(f"Session {self._session_id} ready timeout after {timeout}s")
            raise TimeoutError(f"Session ready timeout after {timeout}s") from None

    async def close(self, *, code: int = 0, reason: str = "", close_connection: bool = True) -> None:
        """Close the session and all associated streams."""
        if self._state in (SessionState.CLOSING, SessionState.CLOSED):
            return
        if (
            not self._is_initialized
            or self._incoming_streams is None
            or self._closed_event is None
            or self.stream_manager is None
        ):
            raise SessionError(
                "WebTransportSession is not initialized."
                "Its factory should call 'await session.initialize()' before use."
            )

        self._state = SessionState.CLOSING
        logger.debug(f"Closing session {self._session_id}...")
        try:
            await self.stream_manager.shutdown()
            if self._datagrams:
                await self._datagrams.close()
            if self._incoming_streams:
                await self._incoming_streams.put(None)
            if self._protocol_handler:
                self._protocol_handler.close_webtransport_session(self._session_id, code=code, reason=reason)

            if close_connection:
                if connection := self.connection:
                    if not connection.is_closed:
                        await connection.close()
        finally:
            self._teardown_event_handlers()
            self._state = SessionState.CLOSED
            self._closed_at = get_timestamp()
            if self._closed_event:
                self._closed_event.set()
            await self.emit(
                EventType.SESSION_CLOSED,
                data={"session_id": self._session_id, "code": code, "reason": reason},
            )
            logger.info(f"Session {self._session_id} is now fully closed.")

    async def wait_closed(self) -> None:
        """Wait for the session to be fully closed."""
        if not self._is_initialized or self._closed_event is None:
            raise SessionError(
                "WebTransportSession is not initialized."
                "Its factory should call 'await session.initialize()' before use."
            )

        await self._closed_event.wait()

    async def create_bidirectional_stream(self, *, timeout: float | None = None) -> WebTransportStream:
        """Create a new bidirectional stream."""
        if not self.is_ready:
            raise session_not_ready(session_id=self._session_id, current_state=self._state)
        connection = self.connection
        if not connection:
            raise SessionError(f"Session {self.session_id} has no active connection.")
        if self.stream_manager is None:
            raise SessionError("StreamManager is not available.")

        effective_timeout: float
        if timeout is not None:
            effective_timeout = timeout
        elif isinstance(self._config, ClientConfig):
            effective_timeout = self._config.stream_creation_timeout
        else:
            effective_timeout = WebTransportConstants.DEFAULT_STREAM_CREATION_TIMEOUT

        try:
            stream = await asyncio.wait_for(
                self.stream_manager.create_bidirectional_stream(), timeout=effective_timeout
            )
            await stream.initialize()
            return stream
        except asyncio.TimeoutError:
            self._stats.stream_errors += 1
            msg = f"Timed out creating bidirectional stream after {effective_timeout}s."
            raise StreamError(msg) from None

    async def create_unidirectional_stream(self, *, timeout: float | None = None) -> WebTransportSendStream:
        """Create a new unidirectional stream."""
        if not self.is_ready:
            raise session_not_ready(session_id=self._session_id, current_state=self._state)
        connection = self.connection
        if not connection:
            raise SessionError(f"Session {self.session_id} has no active connection.")
        if self.stream_manager is None:
            raise SessionError("StreamManager is not available.")

        effective_timeout: float
        if timeout is not None:
            effective_timeout = timeout
        elif isinstance(self._config, ClientConfig):
            effective_timeout = self._config.stream_creation_timeout
        else:
            effective_timeout = WebTransportConstants.DEFAULT_STREAM_CREATION_TIMEOUT

        try:
            stream = await asyncio.wait_for(
                self.stream_manager.create_unidirectional_stream(), timeout=effective_timeout
            )
            await stream.initialize()
            return stream
        except asyncio.TimeoutError:
            self._stats.stream_errors += 1
            msg = f"Timed out creating unidirectional stream after {effective_timeout}s."
            raise StreamError(msg) from None

    async def incoming_streams(self) -> AsyncIterator[StreamType]:
        """Iterate over all incoming streams (both uni- and bidirectional)."""
        if not self._is_initialized or self._incoming_streams is None:
            raise SessionError(
                "WebTransportSession is not initialized."
                "Its factory should call 'await session.initialize()' before use."
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

    async def get_session_stats(self) -> dict[str, Any]:
        """Get an up-to-date dictionary of current session statistics."""
        if self.stream_manager:
            manager_stats = await self.stream_manager.get_stats()
            self._stats.streams_created = manager_stats.get("total_created", 0)
            self._stats.streams_closed = manager_stats.get("total_closed", 0)

        datagram_stream = await self.datagrams
        if datagram_stream:
            datagram_stats = datagram_stream.stats
            self._stats.datagrams_sent = datagram_stats.get("datagrams_sent", 0)
            self._stats.datagrams_received = datagram_stats.get("datagrams_received", 0)
        return self._stats.to_dict()

    async def get_summary(self) -> dict[str, Any]:
        """Get a structured summary of a session for monitoring dashboards."""
        stats = await self.get_session_stats()

        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "path": self.path,
            "uptime": stats.get("uptime", 0),
            "streams": {
                "total_created": stats.get("streams_created", 0),
                "active": stats.get("active_streams", 0),
                "bidirectional": stats.get("bidirectional_streams", 0),
                "unidirectional": stats.get("unidirectional_streams", 0),
            },
            "data": {
                "bytes_sent": stats.get("bytes_sent", 0),
                "bytes_received": stats.get("bytes_received", 0),
                "datagrams_sent": stats.get("datagrams_sent", 0),
                "datagrams_received": stats.get("datagrams_received", 0),
            },
            "errors": {
                "stream_errors": stats.get("stream_errors", 0),
                "protocol_errors": stats.get("protocol_errors", 0),
            },
        }

    async def debug_state(self) -> dict[str, Any]:
        """Get a detailed, structured snapshot of the session state for debugging."""
        stats = await self.get_session_stats()
        streams = await self.stream_manager.get_all_streams() if self.stream_manager else []

        stream_info_list: list[dict[str, Any]] = []
        for stream in streams:
            info: dict[str, Any] = {
                "stream_id": stream.stream_id,
                "state": stream.state.value,
                "direction": stream.direction,
            }
            if hasattr(stream, "bytes_sent"):
                info["bytes_sent"] = stream.bytes_sent
            if hasattr(stream, "bytes_received"):
                info["bytes_received"] = stream.bytes_received
            stream_info_list.append(info)

        datagram_stats: dict[str, Any] = {"available": False}
        datagram_stream = await self.datagrams
        if datagram_stream:
            datagram_stats = {
                "available": True,
                "max_size": datagram_stream.max_datagram_size,
                "sent": datagram_stream.datagrams_sent,
                "received": datagram_stream.datagrams_received,
                "send_buffer": datagram_stream.get_send_buffer_size(),
                "receive_buffer": datagram_stream.get_receive_buffer_size(),
            }

        connection = self.connection
        return {
            "session": {
                "id": self.session_id,
                "state": self.state.value,
                "path": self.path,
                "headers": self.headers,
                "created_at": stats.get("created_at"),
                "ready_at": stats.get("ready_at"),
                "uptime": stats.get("uptime", 0),
            },
            "statistics": stats,
            "streams": stream_info_list,
            "datagrams": datagram_stats,
            "connection": {
                "id": connection.connection_id if connection else None,
                "state": connection.state.value if connection else "N/A",
            },
        }

    async def diagnose_issues(self) -> list[str]:
        """Diagnose and report potential issues with a session."""
        issues: list[str] = []
        stats = await self.get_session_stats()

        if not self.is_ready and not self.is_closed:
            issues.append(f"Session stuck in {self.state.value} state")

        total_operations = stats.get("streams_created", 0) + stats.get("datagrams_sent", 0)
        total_errors = stats.get("stream_errors", 0) + stats.get("protocol_errors", 0)
        if total_operations > 50 and (total_errors / total_operations) > 0.1:
            issues.append(f"High error rate: {total_errors}/{total_operations}")

        uptime = stats.get("uptime", 0)
        active_streams = stats.get("active_streams", 0)
        if uptime > 3600 and active_streams == 0:
            issues.append("Session appears stale (long uptime with no active streams)")

        connection = self.connection
        if not connection or not connection.is_connected:
            issues.append("Underlying connection not available or not connected")

        datagram_stream = await self.datagrams
        if datagram_stream:
            receive_buffer_size = datagram_stream.get_receive_buffer_size()
            if receive_buffer_size > 100:
                issues.append(f"Large datagram receive buffer ({receive_buffer_size}) indicates slow processing.")

        return issues

    async def monitor_health(self, *, check_interval: float = 60.0) -> None:
        """Monitor the health of a session continuously until it is closed."""
        logger.debug(f"Starting health monitoring for session {self.session_id}")
        try:
            while not self.is_closed:
                connection = self.connection
                if connection and hasattr(connection, "info") and connection.info.last_activity:
                    if (get_timestamp() - connection.info.last_activity) > 300:
                        logger.warning(f"Session {self.session_id} appears inactive (no connection activity)")
                await asyncio.sleep(check_interval)
        except asyncio.CancelledError:
            logger.debug(f"Health monitoring cancelled for session {self.session_id}")
        except Exception as e:
            logger.error(f"Session health monitoring error: {e}")

    def _sync_protocol_state(self) -> None:
        """Synchronize session state from the underlying protocol layer."""
        logger.debug(f"Syncing protocol state for session {self._session_id}")
        if not self._protocol_handler:
            return
        if not self._ready_event:
            logger.warning(f"Cannot sync state for session {self._session_id}, session not initialized.")
            return

        session_info = self._protocol_handler.get_session_info(self._session_id)
        if session_info and session_info.state == SessionState.CONNECTED:
            logger.info(f"Syncing ready state for session {self._session_id} (protocol already connected)")
            self._state = SessionState.CONNECTED
            self._ready_at = session_info.ready_at or get_timestamp()
            self._path = session_info.path
            self._headers = session_info.headers.copy() if session_info.headers else {}
            self._control_stream_id = session_info.stream_id
            self._ready_event.set()

    def _setup_event_handlers(self) -> None:
        """Subscribe to relevant events from the protocol handler."""
        logger.debug(f"Setting up event handlers for session {self._session_id}")
        if self.protocol_handler:
            self.protocol_handler.on(EventType.SESSION_READY, self._on_session_ready)
            self.protocol_handler.on(EventType.SESSION_CLOSED, self._on_session_closed)
            self.protocol_handler.on(EventType.STREAM_OPENED, self._on_stream_opened)
            self.protocol_handler.on(EventType.DATAGRAM_RECEIVED, self._on_datagram_received)
        else:
            logger.warning(f"No protocol handler available for session {self._session_id}")

        if connection := self.connection:
            if connection.is_closed:
                logger.warning(f"Session {self.session_id} created on an already closed connection.")
                asyncio.create_task(
                    self.close(reason="Connection already closed upon session creation", close_connection=False)
                )
            else:
                connection.once(EventType.CONNECTION_CLOSED, self._on_connection_closed)

    def _teardown_event_handlers(self) -> None:
        """Unsubscribe from all events to prevent memory leaks."""
        if self.protocol_handler:
            self.protocol_handler.off(EventType.SESSION_READY, self._on_session_ready)
            self.protocol_handler.off(EventType.SESSION_CLOSED, self._on_session_closed)
            self.protocol_handler.off(EventType.STREAM_OPENED, self._on_stream_opened)
            self.protocol_handler.off(EventType.DATAGRAM_RECEIVED, self._on_datagram_received)

        if connection := self.connection:
            connection.off(EventType.CONNECTION_CLOSED, self._on_connection_closed)

    async def _on_session_ready(self, event: Event) -> None:
        """Handle the event indicating the session is ready."""
        if not self._ready_event:
            return

        if isinstance(event.data, dict) and event.data.get("session_id") == self._session_id:
            logger.info(f"SESSION_READY event received for session {self._session_id}")
            self._state = SessionState.CONNECTED
            self._ready_at = get_timestamp()
            self._stats.ready_at = self._ready_at
            self._path = event.data.get("path", "/")
            self._headers = event.data.get("headers", {})
            self._control_stream_id = event.data.get("stream_id")
            self._ready_event.set()
            await self.emit(EventType.SESSION_READY, data={"session_id": self._session_id})
            logger.info(f"Session {self._session_id} is ready (path='{self._path}').")

    async def _on_session_closed(self, event: Event) -> None:
        """Handle the event indicating the session was closed remotely."""
        if isinstance(event.data, dict) and event.data.get("session_id") == self._session_id:
            if self._state not in (SessionState.CLOSING, SessionState.CLOSED):
                logger.warning(f"Session {self._session_id} closed remotely.")
                await self.close(code=event.data.get("code", 0), reason=event.data.get("reason", ""))

    async def _on_connection_closed(self, event: Event) -> None:
        """Handle the underlying connection being closed."""
        if self._state not in (SessionState.CLOSING, SessionState.CLOSED):
            logger.warning(f"Session {self._session_id} closing due to underlying connection loss.")
            asyncio.create_task(self.close(reason="Underlying connection closed", close_connection=False))

    async def _on_stream_opened(self, event: Event) -> None:
        """Handle an incoming stream initiated by the remote peer."""
        if not (isinstance(event.data, dict) and event.data.get("session_id") == self._session_id):
            return
        if not self._incoming_streams:
            return

        stream_id = event.data.get("stream_id")
        direction = event.data.get("direction")
        if stream_id is None or direction is None:
            logger.error(f"STREAM_OPENED event is missing required data for session {self.session_id}.")
            return

        try:
            stream: StreamType
            if direction == StreamDirection.BIDIRECTIONAL:
                stream = WebTransportStream(session=self, stream_id=stream_id)
            else:
                stream = WebTransportReceiveStream(session=self, stream_id=stream_id)

            await stream.initialize()
            initial_payload = event.data.get("initial_payload")
            if initial_payload:
                await stream._on_data_received(Event(type="", data=initial_payload))

            if self.stream_manager is None:
                raise SessionError("StreamManager is not available.")
            await self.stream_manager.add_stream(stream)
            await self._incoming_streams.put(stream)

            logger.debug(f"Accepted incoming {direction.value} stream {stream_id} for session {self.session_id}")

        except Exception as e:
            self._stats.stream_errors += 1
            logger.error(f"Error handling newly opened stream {stream_id}: {e}", exc_info=e)

    async def _on_datagram_received(self, event: Event) -> None:
        """Forward a datagram event to the session's datagram stream."""
        if not (isinstance(event.data, dict) and event.data.get("session_id") == self._session_id):
            return

        datagram_stream = await self.datagrams
        if hasattr(datagram_stream, "_on_datagram_received"):
            await datagram_stream._on_datagram_received(event)

    async def _create_stream_on_protocol(self, is_unidirectional: bool) -> StreamId:
        """Ask the protocol handler to create a new underlying stream."""
        if not self.protocol_handler:
            raise SessionError("Protocol handler is not available to create a stream.")

        try:
            return self.protocol_handler.create_webtransport_stream(
                self.session_id, is_unidirectional=is_unidirectional
            )
        except Exception as e:
            self._stats.stream_errors += 1
            raise StreamError(f"Protocol handler failed to create stream: {e}") from e

    def __str__(self) -> str:
        """Format session info for logging."""
        stats = self._stats
        uptime_str = format_duration(stats.uptime)

        return (
            f"Session({self.session_id[:12]}..., "
            f"state={self.state.value}, "
            f"path={self.path}, "
            f"uptime={uptime_str}, "
            f"streams={stats.active_streams}/{stats.streams_created}, "
            f"datagrams={stats.datagrams_sent}/{stats.datagrams_received})"
        )
