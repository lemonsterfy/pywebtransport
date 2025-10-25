"""Core object representing a single WebTransport connection."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent

from pywebtransport.config import ClientConfig, ServerConfig
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import ClientError, ConfigurationError, ConnectionError, HandshakeError
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.protocol.session_info import WebTransportSessionInfo
from pywebtransport.types import Address, ConnectionState, EventType, SessionId, SessionState
from pywebtransport.utils import Timer, create_quic_configuration, format_duration, get_logger, get_timestamp

__all__: list[str] = ["ConnectionInfo", "WebTransportConnection", "ConnectionDiagnostics"]

logger = get_logger(name=__name__)


@dataclass(frozen=True, kw_only=True)
class ConnectionDiagnostics:
    """Provide a structured, immutable snapshot of a connection's health."""

    stats: ConnectionInfo
    rtt: float
    cwnd: int
    packets_in_flight: int
    packet_loss_rate: float

    @property
    def issues(self) -> list[str]:
        """Get a list of potential issues based on the current diagnostics."""
        issues: list[str] = []
        info = self.stats

        if info.state != ConnectionState.CONNECTED:
            issues.append("Connection not established")
        if info.error_count > 10:
            issues.append(f"High error count: {info.error_count}")
        if info.last_activity and (asyncio.get_running_loop().time() - info.last_activity) > 300:
            issues.append("Connection appears stale (no activity in 5+ minutes)")
        if info.packets_sent > 1000 and info.packets_received == 0:
            issues.append("Data is being sent, but no packets are being received")
        if self.rtt > 1.0:
            issues.append(f"High latency (RTT): {self.rtt * 1000:.1f}ms")

        return issues


@dataclass(kw_only=True)
class ConnectionInfo:
    """Hold comprehensive information and statistics about a connection."""

    connection_id: str
    state: ConnectionState
    local_address: Address | None = None
    remote_address: Address | None = None
    established_at: float | None = None
    closed_at: float | None = None
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    error_count: int = 0
    last_activity: float | None = None

    @property
    def uptime(self) -> float:
        """Get the total uptime of the connection in seconds."""
        if not self.established_at:
            return 0.0
        return (self.closed_at or get_timestamp()) - self.established_at

    def to_dict(self) -> dict[str, Any]:
        """Convert the connection information to a dictionary."""
        return asdict(obj=self)


class WebTransportConnection(EventEmitter):
    """Manage the lifecycle of a WebTransport connection over QUIC."""

    def __init__(self, *, config: ClientConfig | ServerConfig) -> None:
        """Initialize the WebTransport connection."""
        super().__init__()
        self._config = config
        self._connection_id: str = f"conn_{uuid.uuid4()}"
        self._state = ConnectionState.IDLE
        self._info = ConnectionInfo(connection_id=self._connection_id, state=self._state)
        self.last_activity_time: float = 0.0

        self._quic_connection: QuicConnection | None = None
        self._protocol_handler: WebTransportProtocolHandler | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: QuicConnectionProtocol | None = None
        self._proxy_addr: Address | None = None

        self._closed_future: asyncio.Future[None] | None = None
        self._ping_uid_counter = 0
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._timer_handle: asyncio.TimerHandle | None = None

        if isinstance(config, ServerConfig):
            self.idle_timeout: float | None = config.connection_idle_timeout
        else:
            self.idle_timeout = None

    @classmethod
    async def create_client(
        cls, *, config: ClientConfig, host: str, port: int, path: str = "/", proxy_addr: Address | None = None
    ) -> Self:
        """Create a WebTransportConnection instance for client use."""
        connection = cls(config=config)
        connection._proxy_addr = proxy_addr

        try:
            with Timer(name="connection") as timer:
                await connection._establish_quic_connection(host=host, port=port)
                if connection._protocol is None:
                    raise ConnectionError(message="QUIC protocol was not initialized.")
                await connection._initialize_protocol_handler(is_client=True)
                connection._start_background_tasks()
                connection._protocol.transmit()
                await connection._initiate_webtransport_handshake(path=path)
                connection._set_state(new_state=ConnectionState.CONNECTED)
                connection._info.established_at = get_timestamp()
                logger.info("Connected to %s:%s in %s", host, port, format_duration(seconds=timer.elapsed))

            await connection.emit(
                event_type=EventType.CONNECTION_ESTABLISHED,
                data={"connection_id": connection.connection_id},
            )
        except Exception as e:
            await connection.close(reason=f"Connection failed: {e}")
            logger.error("Connection failed: %s", e, exc_info=True)
            raise ConnectionError(message=f"Failed to connect to {host}:{port}: {e}") from e

        return connection

    @classmethod
    async def create_server(cls, *, config: ServerConfig, transport: Any, protocol: Any) -> Self:
        """Create a WebTransportConnection instance for server use."""
        connection = cls(config=config)
        await connection.accept(transport=transport, protocol=protocol)
        return connection

    @property
    def config(self) -> ClientConfig | ServerConfig:
        """Get the configuration object for this connection."""
        return self._config

    @property
    def connection_id(self) -> str:
        """Get the unique ID of this connection."""
        return self._connection_id

    @property
    def diagnostics(self) -> ConnectionDiagnostics:
        """Get a snapshot of the connection's diagnostics and statistics."""
        info = ConnectionInfo(
            connection_id=self._connection_id,
            state=self._state,
            local_address=self.local_address,
            remote_address=self.remote_address,
            established_at=self._info.established_at,
            closed_at=self._info.closed_at,
        )
        rtt, cwnd, packets_in_flight, packet_loss_rate = 0.0, 0, 0, 0.0

        if self._protocol_handler:
            stats = self._protocol_handler._stats
            info.bytes_sent = stats.get("bytes_sent", 0)
            info.bytes_received = stats.get("bytes_received", 0)
            info.error_count = stats.get("errors", 0)
            info.last_activity = stats.get("last_activity")

        if self._quic_connection:
            info.packets_sent = getattr(self._quic_connection, "_packets_sent", 0)
            info.packets_received = getattr(self._quic_connection, "_packets_received", 0)
            if hasattr(self._quic_connection, "_rtt_smoother"):
                rtt = getattr(self._quic_connection._rtt_smoother, "latest_rtt", 0.0)
            if hasattr(self._quic_connection, "congestion_control"):
                cwnd = getattr(self._quic_connection.congestion_control, "congestion_window", 0)
            packets_in_flight = getattr(self._quic_connection, "_packets_in_flight", 0)
            lost_count = getattr(self._quic_connection, "_lost_packets_count", 0)
            total_sent = info.packets_sent + lost_count
            if total_sent > 0:
                packet_loss_rate = lost_count / total_sent

        return ConnectionDiagnostics(
            stats=info,
            rtt=rtt,
            cwnd=cwnd,
            packets_in_flight=packets_in_flight,
            packet_loss_rate=packet_loss_rate,
        )

    @property
    def is_closed(self) -> bool:
        """Check if the connection is fully closed."""
        return self._state == ConnectionState.CLOSED

    @property
    def is_closing(self) -> bool:
        """Check if the connection is in the process of closing."""
        return self._state == ConnectionState.CLOSING

    @property
    def is_connected(self) -> bool:
        """Check if the connection is established."""
        return self._state == ConnectionState.CONNECTED

    @property
    def local_address(self) -> Address | None:
        """Get the local address of the connection."""
        if self._transport:
            return cast(Address | None, self._transport.get_extra_info("sockname", None))
        return None

    @property
    def protocol_handler(self) -> WebTransportProtocolHandler | None:
        """Get the underlying protocol handler instance."""
        return self._protocol_handler

    @property
    def remote_address(self) -> Address | None:
        """Get the remote address of the connection."""
        if self._transport:
            return cast(Address | None, self._transport.get_extra_info("peername", None))
        return None

    @property
    def state(self) -> ConnectionState:
        """Get the current state of the connection."""
        return self._state

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context for the connection."""
        if self._closed_future is None:
            self._closed_future = asyncio.Future()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the asynchronous context, closing the connection."""
        await self.close()

    async def accept(self, *, transport: asyncio.DatagramTransport, protocol: QuicConnectionProtocol) -> None:
        """Accept an incoming server connection."""
        if self._state != ConnectionState.IDLE:
            raise ConnectionError(message=f"Connection already in state {self._state}")
        if not isinstance(self._config, ServerConfig):
            raise ConfigurationError(message="Server connection requires ServerConfig")

        if self._closed_future is None:
            self._closed_future = asyncio.Future()

        logger.info("Accepting incoming connection")
        self._set_state(new_state=ConnectionState.CONNECTING)

        try:
            self._transport, self._protocol, self._quic_connection = (
                transport,
                protocol,
                protocol._quic,
            )
            await self._initialize_protocol_handler(is_client=False)

            if hasattr(self._protocol, "set_connection"):
                self._protocol.set_connection(connection=self)

            self._start_background_tasks()
            self._protocol.transmit()
            self._set_state(new_state=ConnectionState.CONNECTED)
            self._info.established_at = get_timestamp()
            self.record_activity()
            await self.emit(
                event_type=EventType.CONNECTION_ESTABLISHED,
                data={"connection_id": self._connection_id},
            )
        except Exception as e:
            await self.close(reason=f"Accept failed: {e}")
            logger.error("Failed to accept connection: %s", e, exc_info=True)
            raise ConnectionError(message=f"Failed to accept connection: {e}") from e

    async def close(self, *, code: int = 0, reason: str = "") -> None:
        """Close the connection."""
        if self._state in [ConnectionState.CLOSING, ConnectionState.CLOSED]:
            return

        if self._closed_future is None:
            self._closed_future = asyncio.Future()

        logger.info("Closing connection %s...", self._connection_id)
        self._set_state(new_state=ConnectionState.CLOSING)
        self._info.closed_at = get_timestamp()
        tasks_to_cancel = [self._heartbeat_task]

        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in tasks_to_cancel if t], return_exceptions=True)

        if self._timer_handle:
            self._timer_handle.cancel()

        if self._protocol_handler:
            await self._protocol_handler.close()

        try:
            if self._quic_connection:
                self._quic_connection.close(error_code=code, reason_phrase=reason or "")
        except Exception as e:
            logger.error("Error during connection teardown: %s", e, exc_info=True)
        finally:
            self._set_state(new_state=ConnectionState.CLOSED)
            if self._closed_future and not self._closed_future.done():
                self._closed_future.set_result(None)
            await super().close()
            await self.emit(
                event_type=EventType.CONNECTION_CLOSED,
                data={"connection_id": self._connection_id},
            )
            logger.info("Connection %s closed.", self._connection_id)

    def get_all_sessions(self) -> list[WebTransportSessionInfo]:
        """Get a list of all current sessions."""
        if not self.protocol_handler:
            return []
        return self.protocol_handler._session_tracker.get_all_sessions()

    def get_ready_session_id(self) -> SessionId | None:
        """Get the ID of the first available ready session, if any."""
        for session_info in self.get_all_sessions():
            if session_info.state == SessionState.CONNECTED:
                return session_info.session_id
        return None

    def get_session_info(self, *, session_id: SessionId) -> WebTransportSessionInfo | None:
        """Get information about a specific session."""
        if not self.protocol_handler:
            return None
        return self.protocol_handler._session_tracker.get_session_info(session_id=session_id)

    async def monitor_health(self, *, check_interval: float = 30.0, rtt_timeout: float = 5.0) -> None:
        """Monitor the health of a connection with periodic RTT checks."""
        try:
            while self.is_connected:
                try:
                    rtt = await asyncio.wait_for(self._get_rtt(), timeout=rtt_timeout)
                    logger.debug("Connection %s health check: RTT=%.1fms", self.connection_id, rtt * 1000)
                except asyncio.TimeoutError:
                    logger.warning("Connection %s RTT check timeout", self.connection_id)
                    break
                except Exception as e:
                    logger.error("Connection %s health check failed: %s", self.connection_id, e, exc_info=True)
                    break
                await asyncio.sleep(check_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Heartbeat loop error: %s", e, exc_info=True)

    def record_activity(self) -> None:
        """Record activity on the connection by updating the timestamp."""
        self.last_activity_time = get_timestamp()

    async def wait_closed(self) -> None:
        """Wait until the connection is fully closed."""
        if self._state == ConnectionState.CLOSED:
            return
        if self._closed_future is None:
            return
        await self._closed_future

    async def wait_for_ready_session(self, *, timeout: float = 30.0) -> SessionId:
        """Wait for a session to become ready on this connection."""
        if not self.protocol_handler:
            raise ConnectionError(message="Protocol handler is not initialized.")

        logger.debug("Waiting for a ready session...")
        if ready_session_id := self.get_ready_session_id():
            logger.debug("Found existing ready session (fast path): %s", ready_session_id)
            return ready_session_id

        future: asyncio.Future[Event] = asyncio.get_running_loop().create_future()

        async def ready_handler(event: Event) -> None:
            if not future.done():
                future.set_result(event)

        async def closed_handler(event: Event) -> None:
            if not future.done():
                future.set_result(event)

        self.protocol_handler.on(event_type=EventType.SESSION_READY, handler=ready_handler)
        self.protocol_handler.on(event_type=EventType.SESSION_CLOSED, handler=closed_handler)

        try:
            event = await asyncio.wait_for(future, timeout=timeout)
            assert isinstance(event.data, dict)
            session_id = event.data.get("session_id")
            if not session_id:
                raise ConnectionError(message=f"Event {event.type} missing session_id.")

            if event.type == EventType.SESSION_READY:
                logger.debug("SESSION_READY event received, session_id: %s", session_id)
                return cast(SessionId, session_id)
            elif event.type == EventType.SESSION_CLOSED:
                reason = event.data.get("reason", "unknown reason")
                raise ClientError(message=f"Session closed before ready: {reason}")

        except asyncio.TimeoutError:
            raise ConnectionError(message=f"Session ready/closed timeout after {timeout}s.") from None
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ConnectionError(message=f"Failed to get a ready session: {e}") from e
        finally:
            self.protocol_handler.off(event_type=EventType.SESSION_READY, handler=ready_handler)
            self.protocol_handler.off(event_type=EventType.SESSION_CLOSED, handler=closed_handler)

        raise ConnectionError(message="wait_for_ready_session reached an unexpected state.")

    async def wait_ready(self, *, timeout: float = 30.0) -> None:
        """Wait for a connection to be established and ready."""
        if self.is_connected:
            return
        await self.wait_for(event_type=EventType.CONNECTION_ESTABLISHED, timeout=timeout)

    async def _establish_quic_connection(self, *, host: str, port: int) -> None:
        """Establish the underlying QUIC transport."""
        if not isinstance(self._config, ClientConfig):
            raise TypeError("ClientConfig needed")

        loop = asyncio.get_running_loop()
        config = self._config
        quic_config: QuicConfiguration = create_quic_configuration(
            is_client=True,
            alpn_protocols=config.alpn_protocols,
            congestion_control_algorithm=config.congestion_control_algorithm,
            max_datagram_size=config.max_datagram_size,
        )

        if config.certfile and config.keyfile:
            quic_config.load_cert_chain(Path(config.certfile), Path(config.keyfile))
        if config.ca_certs:
            quic_config.load_verify_locations(cafile=config.ca_certs)
        if config.verify_mode is not None:
            quic_config.verify_mode = config.verify_mode

        self._quic_connection = QuicConnection(configuration=quic_config)

        def protocol_factory() -> _WebTransportClientProtocol:
            return _WebTransportClientProtocol(self, self._quic_connection)

        remote_addr = self._proxy_addr or (host, port)

        try:
            self._transport, self._protocol = await loop.create_datagram_endpoint(
                protocol_factory, remote_addr=remote_addr
            )
        except Exception as e:
            raise ConnectionError(message=f"QUIC create_datagram_endpoint failed: {e}") from e

        self._quic_connection.connect(addr=(host, port), now=loop.time())

    async def _forward_session_request_from_handler(self, event: Event) -> None:
        """Forward a session request event from the handler to this connection."""
        logger.debug("Forwarding SESSION_REQUEST from handler to connection %s", self.connection_id)
        await self.emit(event_type=EventType.SESSION_REQUEST, data=event.data)

    async def _get_rtt(self) -> float:
        """Get the latest RTT from the underlying QUIC connection."""
        if self._quic_connection and hasattr(self._quic_connection, "_rtt_smoother"):
            smoother = self._quic_connection._rtt_smoother
            if hasattr(smoother, "latest_rtt"):
                return cast(float, smoother.latest_rtt)
        raise ConnectionError(message="Connection not active or RTT is not available.")

    async def _heartbeat_loop(self) -> None:
        """Periodically send PING frames to keep the connection alive."""
        interval = self._config.connection_keepalive_timeout
        try:
            while self.is_connected:
                await asyncio.sleep(interval)
                if self._quic_connection:
                    self._ping_uid_counter += 1
                    self._quic_connection.send_ping(uid=self._ping_uid_counter)
                if self._protocol:
                    self._protocol.transmit()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Heartbeat loop error: %s", e, exc_info=True)

    async def _initialize_protocol_handler(self, *, is_client: bool) -> None:
        """Create and configure the protocol handler."""
        if not self._quic_connection:
            raise ConnectionError(message="QUIC not established")
        if not self._protocol:
            raise ConnectionError(message="QUIC protocol not initialized")

        self._protocol_handler = WebTransportProtocolHandler(
            quic_connection=self._quic_connection,
            is_client=is_client,
            connection=self,
            trigger_transmission=self._protocol.transmit,
        )

        if not is_client:
            self._protocol_handler.on(
                event_type=EventType.SESSION_REQUEST,
                handler=self._forward_session_request_from_handler,
            )

    async def _initiate_webtransport_handshake(self, *, path: str) -> None:
        """Start the WebTransport CONNECT handshake."""
        if not self._protocol_handler or not isinstance(self._config, ClientConfig):
            raise HandshakeError(message="Protocol handler or config not ready for handshake.")
        try:
            session_id, _ = await self._protocol_handler.create_webtransport_session(
                path=path, headers=self._config.headers
            )
            logger.debug("Initiated WebTransport handshake, session_id: %s", session_id)
        except Exception as e:
            raise HandshakeError(message=f"WebTransport handshake failed: {e}") from e

    def _on_connection_lost(self, exc: Exception | None) -> None:
        """Handle an unexpected connection loss."""
        if self._state in [ConnectionState.CLOSING, ConnectionState.CLOSED]:
            return
        logger.warning("Connection %s lost: %s", self.connection_id, exc)
        asyncio.create_task(
            self.emit(
                event_type=EventType.CONNECTION_LOST, data={"connection_id": self.connection_id, "exception": exc}
            )
        )

    def _schedule_transmit(self) -> None:
        """Schedule the next transmission based on the QUIC timer."""
        if self._timer_handle:
            self._timer_handle.cancel()

        if self._state != ConnectionState.CLOSED and self._quic_connection and self._protocol:
            if timer_at := self._quic_connection.get_timer():
                self._timer_handle = asyncio.get_running_loop().call_at(when=timer_at, callback=self._protocol.transmit)

    def _set_state(self, *, new_state: ConnectionState) -> None:
        """Set a new state for the connection and log the change."""
        if self._state == new_state:
            return
        old_state = self._state
        self._state = new_state
        self._info.state = new_state
        logger.debug("Connection %s state: %s -> %s", self._connection_id, old_state, new_state)

    def _start_background_tasks(self) -> None:
        """Start any background tasks like keep-alives."""
        if self._config.keep_alive:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def __str__(self) -> str:
        """Format a concise, human-readable summary of a connection for logging."""
        info = self.diagnostics.stats
        addr_str = f"{info.remote_address[0]}:{info.remote_address[1]}" if info.remote_address else "unknown"
        uptime_str = format_duration(seconds=info.uptime) if info.uptime > 0 else "0s"
        return f"Connection({self.connection_id[:8]}..., state={info.state}, remote={addr_str}, uptime={uptime_str})"


class _WebTransportClientProtocol(QuicConnectionProtocol):
    """A specialized QUIC protocol for client-side WebTransport connections."""

    _owner: WebTransportConnection
    _event_queue: asyncio.Queue[QuicEvent] | None
    _event_processor_task: asyncio.Task[None] | None

    def __init__(self, owner: WebTransportConnection, *args: Any, **kwargs: Any) -> None:
        """Initialize the client protocol."""
        super().__init__(*args, **kwargs)
        self._owner = owner
        self._event_queue = None
        self._event_processor_task = None

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle a connection being lost."""
        super().connection_lost(exc)
        if self._event_processor_task and not self._event_processor_task.done():
            self._event_processor_task.cancel()
        self._owner._on_connection_lost(exc=exc)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Handle a new connection being made."""
        super().connection_made(transport)
        self._event_queue = asyncio.Queue()
        self._event_processor_task = asyncio.create_task(self._process_events_loop())

    def quic_event_received(self, event: QuicEvent) -> None:
        """Handle a QUIC event from the underlying transport."""
        if self._event_queue:
            self._event_queue.put_nowait(event)

    async def _process_events_loop(self) -> None:
        """Continuously process events from the QUIC connection."""
        if self._event_queue is None:
            return
        try:
            while True:
                event = await self._event_queue.get()
                if self._owner.protocol_handler:
                    try:
                        await self._owner.protocol_handler.handle_quic_event(event=event)
                    except Exception as e:
                        logger.error(
                            "Error handling QUIC event for %s: %s", self._owner.connection_id, e, exc_info=True
                        )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.critical("Fatal error in client event processing loop: %s", e, exc_info=True)
