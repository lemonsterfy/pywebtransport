"""Core WebTransport connection object representing a QUIC connection."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, TypeAlias, cast

from pywebtransport._protocol.events import (
    ConnectionClose,
    Effect,
    EmitConnectionEvent,
    EmitSessionEvent,
    EmitStreamEvent,
    UserConnectionGracefulClose,
    UserCreateSession,
    UserEvent,
    UserGetConnectionDiagnostics,
)
from pywebtransport._protocol.webtransport_engine import WebTransportEngine
from pywebtransport.constants import ErrorCodes
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ConnectionError, SessionError
from pywebtransport.session.session import WebTransportSession
from pywebtransport.stream.stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.types import (
    Address,
    ConnectionId,
    ConnectionState,
    EventType,
    Headers,
    SessionId,
    StreamDirection,
    StreamId,
)
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.client._adapter import WebTransportClientProtocol
    from pywebtransport.config import ClientConfig, ServerConfig
    from pywebtransport.server._adapter import WebTransportServerProtocol

    AdapterProtocol: TypeAlias = WebTransportServerProtocol | WebTransportClientProtocol
    StreamHandle: TypeAlias = WebTransportStream | WebTransportReceiveStream | WebTransportSendStream

__all__: list[str] = ["ConnectionDiagnostics", "WebTransportConnection"]

logger = get_logger(name=__name__)


@dataclass(kw_only=True)
class ConnectionDiagnostics:
    """A snapshot of connection diagnostics."""

    connection_id: ConnectionId
    state: ConnectionState
    is_client: bool
    connected_at: float | None
    closed_at: float | None
    max_datagram_size: int
    remote_max_datagram_frame_size: int
    session_count: int
    stream_count: int
    active_session_handles: int
    active_stream_handles: int


class WebTransportConnection:
    """A high-level handle for a WebTransport connection over QUIC."""

    def __init__(
        self,
        *,
        config: ClientConfig | ServerConfig,
        protocol: AdapterProtocol,
        transport: asyncio.DatagramTransport,
        is_client: bool,
    ) -> None:
        """Initialize the WebTransport connection."""
        self._config = config
        self._protocol = protocol
        self._transport = transport
        self._is_client = is_client
        self._connection_id: ConnectionId = str(uuid.uuid4())
        self.events = EventEmitter()

        self._engine = WebTransportEngine(
            connection_id=self._connection_id,
            config=config,
            is_client=is_client,
            protocol_handler=protocol,
            owner_notify_callback=self._notify_owner,
        )

        self._session_handles: dict[SessionId, WebTransportSession] = {}
        self._stream_handles: dict[StreamId, StreamHandle] = {}

        logger.debug("WebTransportConnection %s initialized.", self.connection_id)

    @property
    def config(self) -> ClientConfig | ServerConfig:
        """Get the configuration associated with this connection."""
        return self._config

    @property
    def connection_id(self) -> ConnectionId:
        """Get the unique identifier for this connection."""
        return self._connection_id

    @property
    def is_client(self) -> bool:
        """Return True if this is a client-side connection."""
        return self._is_client

    @property
    def is_closed(self) -> bool:
        """Return True if the connection is closed."""
        return self.state == ConnectionState.CLOSED

    @property
    def is_closing(self) -> bool:
        """Return True if the connection is closing."""
        return self.state == ConnectionState.CLOSING

    @property
    def is_connected(self) -> bool:
        """Return True if the connection is established."""
        return self.state == ConnectionState.CONNECTED

    @property
    def local_address(self) -> Address | None:
        """Get the local address of the connection."""
        if hasattr(self, "_transport") and self._transport:
            return cast(Address | None, self._transport.get_extra_info("sockname"))
        return None

    @property
    def remote_address(self) -> Address | None:
        """Get the remote address of the connection."""
        if hasattr(self, "_transport") and self._transport:
            return cast(Address | None, self._transport.get_extra_info("peername"))
        return None

    @property
    def state(self) -> ConnectionState:
        """Get the current state of the connection."""
        return self._get_engine_state()

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context manager."""
        await self.close()

    async def close(self, *, error_code: int = ErrorCodes.NO_ERROR, reason: str = "Closed by application") -> None:
        """Immediately close the WebTransport connection."""
        logger.info("Closing connection %s...", self.connection_id)

        fut = asyncio.get_running_loop().create_future()
        event = ConnectionClose(error_code=error_code, reason=reason, future=fut)

        await self._send_event_to_engine(event=event)

        try:
            async with asyncio.timeout(delay=5.0):
                await fut
        except asyncio.TimeoutError:
            fut.cancel()
        except Exception:
            pass

        if hasattr(self, "_engine"):
            await self._engine.stop_driver_loop()

        if self.is_client:
            if hasattr(self, "_transport") and self._transport and not self._transport.is_closing():
                logger.debug("Closing underlying transport for connection %s", self.connection_id)
                self._transport.close()

        self._session_handles.clear()
        self._stream_handles.clear()

        if hasattr(self, "_engine") and hasattr(self._engine, "_state"):
            self._engine._state.connection_state = ConnectionState.CLOSED
        logger.info("Connection %s close process finished.", self.connection_id)

    async def create_session(self, *, path: str, headers: Headers | None = None) -> WebTransportSession:
        """Create a new WebTransport session."""
        if not self.is_client:
            raise ConnectionError("Sessions can only be created by the client.")
        if not hasattr(self, "_engine"):
            raise ConnectionError("Engine not available for creating session.")

        fut = asyncio.get_running_loop().create_future()
        event = UserCreateSession(path=path, headers=headers or {}, future=fut)
        await self._send_event_to_engine(event=event)

        session_id: SessionId = await fut

        session_handle = self._session_handles.get(session_id)
        if not session_handle:
            logger.error("Internal error: Session handle %s missing after successful creation effect.", session_id)
            raise SessionError(f"Internal error creating session handle for {session_id}")

        return session_handle

    async def graceful_shutdown(self) -> None:
        """Gracefully shut down the connection."""
        logger.info("Initiating graceful shutdown for connection %s...", self.connection_id)
        fut = asyncio.get_running_loop().create_future()
        event = UserConnectionGracefulClose(future=fut)

        await self._send_event_to_engine(event=event)

        try:
            async with asyncio.timeout(delay=5.0):
                await fut
        except asyncio.TimeoutError:
            fut.cancel()
            logger.warning("Timeout waiting for graceful shutdown GOAWAY confirmation.")
        except Exception as e:
            logger.warning("Error during graceful shutdown: %s", e)

        await self.close(reason="Graceful shutdown complete")

    async def initialize(self) -> None:
        """Start the internal engine loop."""
        if hasattr(self, "_engine") and self._engine._driver_task is None:
            self._engine.start_driver_loop()
            if self._engine._event_queue is not None:
                self._protocol.set_engine_queue(engine_queue=self._engine._event_queue)
            else:
                logger.critical("Engine failed to create event queue during initialization for %s", self.connection_id)
                await self.close()
        elif not hasattr(self, "_engine"):
            logger.warning("Attempted to initialize connection %s without an engine.", self.connection_id)

    async def diagnostics(self) -> ConnectionDiagnostics:
        """Get diagnostic information about the connection."""
        if not hasattr(self, "_engine"):
            raise ConnectionError("Engine not available.")

        fut = asyncio.get_running_loop().create_future()
        event = UserGetConnectionDiagnostics(future=fut)
        await self._send_event_to_engine(event=event)

        diag_data: dict[str, Any] = await fut
        diag_data["active_session_handles"] = len(self._session_handles)
        diag_data["active_stream_handles"] = len(self._stream_handles)
        return ConnectionDiagnostics(**diag_data)

    def get_all_sessions(self) -> list[WebTransportSession]:
        """Get a list of all active session handles."""
        return list(self._session_handles.values())

    def _get_engine_state(self) -> ConnectionState:
        """Safely get the current engine state for internal logic."""
        if hasattr(self, "_engine") and hasattr(self._engine, "_state"):
            return self._engine._state.connection_state
        return ConnectionState.CLOSED

    def _notify_owner(self, effect: Effect) -> None:
        """Handle events emitted from the protocol engine."""
        try:
            match effect:
                case EmitConnectionEvent(event_type=et, data=d):
                    if "connection" not in d:
                        d["connection"] = self
                    self.events.emit_nowait(event_type=et, data=d)

                case EmitSessionEvent(session_id=sid, event_type=et, data=d):
                    create_handle_event = (not self.is_client and et == EventType.SESSION_REQUEST) or (
                        self.is_client and et == EventType.SESSION_READY
                    )

                    session_handle = self._session_handles.get(sid)

                    if not session_handle and create_handle_event:
                        if hasattr(self, "_engine") and hasattr(self._engine, "_state"):
                            session_data = self._engine._state.sessions.get(sid)
                            if session_data:
                                session = WebTransportSession(
                                    connection=self,
                                    session_id=sid,
                                    path=session_data.path,
                                    headers=session_data.headers,
                                    control_stream_id=session_data.control_stream_id,
                                )
                                self._session_handles[sid] = session
                                session_handle = session
                                logger.debug("Created session handle for %s", sid)
                            else:
                                logger.error("Engine state for session %s missing during handle creation.", sid)
                        else:
                            logger.error("Engine or state missing during session handle creation for %s.", sid)

                    if session_handle:
                        if "session" not in d:
                            d["session"] = session_handle

                        if et in (EventType.SESSION_DATA_BLOCKED, EventType.SESSION_STREAMS_BLOCKED):
                            if session_handle.events.listener_count(event_type=et) == 0:
                                logger.warning("Session %s received unhandled event '%s'.", sid, et.value)

                        session_handle.events.emit_nowait(event_type=et, data=d)

                        if et == EventType.SESSION_REQUEST:
                            self.events.emit_nowait(event_type=et, data=d)
                    elif not create_handle_event:
                        logger.warning("No session handle found for event %s on session %s", et, sid)

                    if et == EventType.SESSION_CLOSED:
                        removed = self._session_handles.pop(sid, None)
                        if removed:
                            logger.debug("Removed session handle for closed session %s", sid)
                            asyncio.create_task(coro=removed.events.close())

                case EmitStreamEvent(stream_id=stid, event_type=et, data=d):
                    stream_handle = self._stream_handles.get(stid)
                    stream_session_handle: WebTransportSession | None = None

                    if not stream_handle and et == EventType.STREAM_OPENED:
                        if hasattr(self, "_engine") and hasattr(self._engine, "_state"):
                            stream_data = self._engine._state.streams.get(stid)
                            stream_session_handle = (
                                self._session_handles.get(stream_data.session_id) if stream_data else None
                            )
                            if stream_data and stream_session_handle:
                                handle_class: type[StreamHandle]
                                match stream_data.direction:
                                    case StreamDirection.BIDIRECTIONAL:
                                        handle_class = WebTransportStream
                                    case StreamDirection.SEND_ONLY:
                                        handle_class = WebTransportSendStream
                                    case StreamDirection.RECEIVE_ONLY:
                                        handle_class = WebTransportReceiveStream

                                new_stream_handle = handle_class(session=stream_session_handle, stream_id=stid)
                                self._stream_handles[stid] = new_stream_handle
                                stream_handle = new_stream_handle
                                logger.debug("Created stream handle for %d (%s)", stid, stream_data.direction)
                            else:
                                logger.error(
                                    "Stream data (%s) or session handle (%s) missing for stream %d.",
                                    bool(stream_data),
                                    bool(stream_session_handle),
                                    stid,
                                )
                        else:
                            logger.error("Engine or state missing during stream handle creation for %d.", stid)

                    if stream_handle:
                        if "stream" not in d:
                            d["stream"] = stream_handle
                        stream_handle.events.emit_nowait(event_type=et, data=d)

                        if et == EventType.STREAM_OPENED:
                            if stream_session_handle is None:
                                stream_data = self._engine._state.streams.get(stid)
                                if stream_data:
                                    stream_session_handle = self._session_handles.get(stream_data.session_id)

                            if stream_session_handle:
                                stream_session_handle._add_stream_handle(stream=stream_handle, event_data=d)
                            else:
                                logger.error("No session handle found to propagate STREAM_OPENED for stream %d", stid)

                    elif et != EventType.STREAM_OPENED:
                        logger.warning("No stream handle found for event %s on stream %d", et, stid)

                    if et == EventType.STREAM_CLOSED:
                        removed_stream = self._stream_handles.pop(stid, None)
                        if removed_stream:
                            logger.debug("Removed stream handle for closed stream %d", stid)
                            asyncio.create_task(coro=removed_stream.events.close())

        except Exception as e:
            logger.error("Error during owner notification callback: %s", e, exc_info=True)

    async def _send_event_to_engine(self, *, event: UserEvent) -> None:
        """Send a UserEvent to the protocol engine."""
        if not hasattr(self, "_engine"):
            if not event.future.done():
                exc = ConnectionError(f"Connection {self.connection_id} engine is missing.")
                try:
                    event.future.set_exception(exc)
                except asyncio.InvalidStateError:
                    pass
            return

        await self._engine.put_event(event=event)

    def __repr__(self) -> str:
        """Provide a developer-friendly representation."""
        current_state = self._get_engine_state()
        return f"<WebTransportConnection id={self.connection_id} state={current_state} client={self.is_client}>"
