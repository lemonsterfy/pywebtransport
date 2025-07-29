"""
WebTransport connection core implementation.
"""

import asyncio
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Dict, List, Optional, Type, Union, cast

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent

from pywebtransport.config import ClientConfig, ServerConfig
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import ConfigurationError, ConnectionError, HandshakeError
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.protocol.utils import create_quic_configuration
from pywebtransport.types import Address, ConnectionState, EventType, SessionId, SessionState
from pywebtransport.utils import Timer, format_duration, get_logger, get_timestamp

__all__ = ["ConnectionInfo", "WebTransportConnection"]

logger = get_logger("connection")


@dataclass
class ConnectionInfo:
    """Holds comprehensive information and statistics about a connection."""

    connection_id: str
    state: ConnectionState
    local_address: Optional[Address] = None
    remote_address: Optional[Address] = None
    established_at: Optional[float] = None
    closed_at: Optional[float] = None
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    error_count: int = 0
    last_activity: Optional[float] = None

    @property
    def uptime(self) -> float:
        """Get the total uptime of the connection in seconds."""
        if not self.established_at:
            return 0.0
        return (self.closed_at or get_timestamp()) - self.established_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert the connection information to a dictionary."""
        return asdict(self)


class WebTransportConnection(EventEmitter):
    """Manages the lifecycle of a WebTransport connection over QUIC."""

    def __init__(self, config: Union[ClientConfig, ServerConfig]):
        """Initialize the WebTransport connection."""
        super().__init__()
        self._config = config
        self._connection_id: str = f"conn_{uuid.uuid4()}"
        self._quic_connection: Optional[QuicConnection] = None
        self._protocol_handler: Optional[WebTransportProtocolHandler] = None
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional[QuicConnectionProtocol] = None
        self._state = ConnectionState.IDLE
        self._info = ConnectionInfo(connection_id=self._connection_id, state=self._state)
        self._closed_future: asyncio.Future[None] = asyncio.Future()
        self._ping_uid_counter = 0
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        self._timer_handle: Optional[asyncio.TimerHandle] = None

    @classmethod
    async def create_client(
        cls, *, config: ClientConfig, host: str, port: int, path: str = "/"
    ) -> "WebTransportConnection":
        """Create a WebTransportConnection instance for client use."""
        connection = cls(config)
        await connection.connect(host=host, port=port, path=path)
        return connection

    @classmethod
    async def create_server(cls, *, config: ServerConfig, transport: Any, protocol: Any) -> "WebTransportConnection":
        """Create a WebTransportConnection instance for server use."""
        connection = cls(config)
        await connection.accept(transport=transport, protocol=protocol)
        return connection

    @property
    def state(self) -> ConnectionState:
        """Get the current state of the connection."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if the connection is established."""
        return self._state == ConnectionState.CONNECTED

    @property
    def is_closing(self) -> bool:
        """Check if the connection is in the process of closing."""
        return self._state == ConnectionState.CLOSING

    @property
    def is_closed(self) -> bool:
        """Check if the connection is fully closed."""
        return self._state == ConnectionState.CLOSED

    @property
    def config(self) -> Union[ClientConfig, ServerConfig]:
        """Get the configuration object for this connection."""
        return self._config

    @property
    def connection_id(self) -> str:
        """Get the unique ID of this connection."""
        return self._connection_id

    @property
    def local_address(self) -> Optional[Address]:
        """Get the local address of the connection."""
        if self._transport:
            return cast(Optional[Address], self._transport.get_extra_info("sockname", None))
        return None

    @property
    def remote_address(self) -> Optional[Address]:
        """Get the remote address of the connection."""
        if self._transport:
            return cast(Optional[Address], self._transport.get_extra_info("peername", None))
        return None

    @property
    def protocol_handler(self) -> Optional[WebTransportProtocolHandler]:
        """Get the underlying protocol handler instance."""
        return self._protocol_handler

    @property
    def info(self) -> ConnectionInfo:
        """Get an up-to-date object with connection information and stats."""
        self._info.local_address, self._info.remote_address = self.local_address, self.remote_address
        if self._protocol_handler:
            stats = self._protocol_handler.stats
            self._info.bytes_sent = stats.get("bytes_sent", 0)
            self._info.bytes_received = stats.get("bytes_received", 0)
            self._info.error_count = stats.get("errors", 0)
            self._info.last_activity = stats.get("last_activity")
        if self._quic_connection:
            self._info.packets_sent = getattr(self._quic_connection, "_packets_sent", 0)
            self._info.packets_received = getattr(self._quic_connection, "_packets_received", 0)
        return self._info

    async def __aenter__(self) -> "WebTransportConnection":
        """Enter the asynchronous context for the connection."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the asynchronous context, closing the connection."""
        await self.close()

    async def connect(self, host: str, port: int, path: str = "/") -> None:
        """Establish a client connection to a WebTransport endpoint."""
        if self._state != ConnectionState.IDLE:
            raise ConnectionError(f"Connection already in state {self._state}")
        if not isinstance(self._config, ClientConfig):
            raise ConfigurationError("Client connection requires ClientConfig")

        logger.info(f"Connecting to {host}:{port}{path}...")
        self._set_state(ConnectionState.CONNECTING)
        try:
            with Timer("connection") as timer:
                await self._establish_quic_connection(host, port)
                await self._initialize_protocol_handler(is_client=True)
                self._start_background_tasks()
                self._transmit()
                await self._initiate_webtransport_handshake(path)
                self._set_state(ConnectionState.CONNECTED)
                self._info.established_at = get_timestamp()
                logger.info(f"Connected to {host}:{port} in {format_duration(timer.elapsed)}")
            await self.emit(EventType.CONNECTION_ESTABLISHED, data={"connection_id": self._connection_id})
        except Exception as e:
            await self.close(reason=f"Connection failed: {e}")
            logger.error(f"Connection failed: {e}", exc_info=e)
            raise ConnectionError(f"Failed to connect to {host}:{port}: {e}") from e

    async def accept(self, transport: asyncio.DatagramTransport, protocol: QuicConnectionProtocol) -> None:
        """Accept an incoming server connection."""
        if self._state != ConnectionState.IDLE:
            raise ConnectionError(f"Connection already in state {self._state}")
        if not isinstance(self._config, ServerConfig):
            raise ConfigurationError("Server connection requires ServerConfig")

        logger.info("Accepting incoming connection")
        self._set_state(ConnectionState.CONNECTING)
        try:
            self._transport, self._protocol, self._quic_connection = transport, protocol, protocol._quic
            await self._initialize_protocol_handler(is_client=False)
            if hasattr(self._protocol, "set_connection"):
                self._protocol.set_connection(self)
            self._start_background_tasks()
            self._transmit()
            self._set_state(ConnectionState.CONNECTED)
            self._info.established_at = get_timestamp()
            logger.info(f"Accepted connection from {self.remote_address}")
            await self.emit(EventType.CONNECTION_ESTABLISHED, data={"connection_id": self._connection_id})
        except Exception as e:
            await self.close(reason=f"Accept failed: {e}")
            logger.error(f"Failed to accept connection: {e}", exc_info=e)
            raise ConnectionError(f"Failed to accept connection: {e}") from e

    async def close(self, *, code: int = 0, reason: str = "") -> None:
        """Close the connection."""
        if self._state in [ConnectionState.CLOSING, ConnectionState.CLOSED]:
            return
        logger.info(f"Closing connection {self._connection_id}...")
        self._set_state(ConnectionState.CLOSING)
        self._info.closed_at = get_timestamp()

        tasks_to_cancel = [self._heartbeat_task]
        for task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*[t for t in tasks_to_cancel if t], return_exceptions=True)

        if self._timer_handle:
            self._timer_handle.cancel()
        try:
            if self._quic_connection:
                self._quic_connection.close(error_code=code, reason_phrase=reason or "")
        except Exception as e:
            logger.error(f"Error during connection teardown: {e}")
        finally:
            self._set_state(ConnectionState.CLOSED)
            if not self._closed_future.done():
                self._closed_future.set_result(None)
            logger.info(f"Connection {self._connection_id} closed.")

    async def wait_closed(self) -> None:
        """Wait until the connection is fully closed."""
        if self._state == ConnectionState.CLOSED:
            return
        await self._closed_future

    async def wait_ready(self, *, timeout: float = 30.0) -> None:
        """Wait for a connection to be established and ready."""
        if self.is_connected:
            return
        await self.wait_for(EventType.CONNECTION_ESTABLISHED, timeout=timeout)

    async def wait_for_ready_session(self, *, timeout: float = 30.0) -> SessionId:
        """Wait for a session to become ready on this connection."""
        logger.debug("Waiting for a ready session...")
        if ready_session_id := self.get_ready_session_id():
            logger.debug(f"Found existing ready session (fast path): {ready_session_id}")
            return ready_session_id

        if not self.protocol_handler:
            raise ConnectionError("Protocol handler is not initialized.")

        def condition(event: Event) -> bool:
            return isinstance(event.data, dict) and event.data.get("session_id") is not None

        try:
            event = await self.protocol_handler.wait_for(EventType.SESSION_READY, timeout=timeout, condition=condition)
            assert isinstance(event.data, dict)
            session_id = event.data["session_id"]
            logger.debug(f"SESSION_READY event received, session_id: {session_id}")
            return cast(SessionId, session_id)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Session ready timeout after {timeout}s.") from None
        except Exception as e:
            raise ConnectionError(f"Failed to get a ready session: {e}") from e

    def get_ready_session_id(self) -> Optional[SessionId]:
        """Get the ID of the first available ready session, if any."""
        if not self.protocol_handler:
            return None
        for session_info in self.protocol_handler.get_all_sessions():
            if session_info.state == SessionState.CONNECTED:
                return session_info.session_id
        return None

    def get_summary(self) -> Dict[str, Any]:
        """Get a structured summary of a connection for monitoring."""
        info = self.info
        return {
            "id": self.connection_id,
            "state": info.state.value,
            "uptime": info.uptime,
            "remote_address": info.remote_address,
            "bytes_sent": info.bytes_sent,
            "bytes_received": info.bytes_received,
            "packets_sent": info.packets_sent,
            "packets_received": info.packets_received,
            "errors": info.error_count,
            "last_activity": info.last_activity,
        }

    async def monitor_health(self, *, check_interval: float = 30.0, rtt_timeout: float = 5.0) -> None:
        """Monitor the health of a connection with periodic RTT checks."""
        try:
            while self.is_connected:
                try:
                    rtt = await asyncio.wait_for(self._get_rtt(), timeout=rtt_timeout)
                    logger.debug(f"Connection {self.connection_id} health check: RTT={rtt*1000:.1f}ms")
                except asyncio.TimeoutError:
                    logger.warning(f"Connection {self.connection_id} RTT check timeout")
                    break
                except Exception as e:
                    logger.error(f"Connection {self.connection_id} health check failed: {e}")
                    break
                await asyncio.sleep(check_interval)
        except asyncio.CancelledError:
            pass

    async def diagnose_issues(self) -> Dict[str, Any]:
        """Diagnose and report a list of potential issues with a connection."""
        issues: List[str] = []
        recommendations: List[str] = []
        diagnosis: Dict[str, Any] = {
            "connection_id": self.connection_id,
            "state": self.state.value,
            "is_connected": self.is_connected,
            "issues": issues,
            "recommendations": recommendations,
        }
        info = self.info

        if not self.is_connected:
            issues.append("Connection not established")
            recommendations.append("Check network connectivity")
        if info.error_count > 10:
            issues.append(f"High error count: {info.error_count}")
            recommendations.append("Check for protocol errors or network issues")
        if info.last_activity and (asyncio.get_event_loop().time() - info.last_activity) > 300:
            issues.append("Connection appears stale (no activity in 5+ minutes)")
            recommendations.append("Consider reconnecting or enabling keep-alive")
        if info.packets_sent > 1000 and info.packets_received == 0:
            issues.append("Data is being sent, but no packets are being received")
            recommendations.append("Check firewall rules and remote endpoint status")
        if self.is_connected:
            try:
                rtt = await asyncio.wait_for(self._get_rtt(), timeout=5.0)
                diagnosis["ping_rtt"] = rtt
                if rtt > 1.0:
                    issues.append(f"High latency (RTT): {rtt*1000:.1f}ms")
                    recommendations.append("Check network quality")
            except asyncio.TimeoutError:
                issues.append("RTT check timed out")
                recommendations.append("Connection may be unresponsive")
            except Exception as e:
                issues.append(f"RTT check failed: {e}")
        return diagnosis

    async def _establish_quic_connection(self, host: str, port: int) -> None:
        """Internal helper to set up the QUIC transport and protocol."""
        loop = asyncio.get_running_loop()
        config = self._config
        if not isinstance(config, ClientConfig):
            raise TypeError("ClientConfig needed")

        quic_config = create_quic_configuration(is_client=True, **config.to_dict())
        quic_config.max_datagram_frame_size = 65536
        if config.certfile and config.keyfile:
            quic_config.load_cert_chain(Path(config.certfile), Path(config.keyfile))
        if config.ca_certs:
            quic_config.load_verify_locations(cafile=config.ca_certs)
        if config.verify_mode is not None:
            quic_config.verify_mode = config.verify_mode
        self._quic_connection = QuicConnection(configuration=quic_config)

        class _ClientProtocol(QuicConnectionProtocol):
            def __init__(self, owner: "WebTransportConnection", *args: Any, **kwargs: Any):
                super().__init__(*args, **kwargs)
                self._owner = owner

            def quic_event_received(self, event: QuicEvent) -> None:
                if self._owner._protocol_handler:
                    asyncio.create_task(self._owner._protocol_handler.handle_quic_event(event))

            def connection_lost(self, exc: Optional[Exception]) -> None:
                super().connection_lost(exc)
                self._owner._on_connection_lost(exc)

        protocol = _ClientProtocol(self, self._quic_connection)
        self._protocol = protocol
        remote_addr = (host, port)
        try:
            self._transport, _ = await loop.create_datagram_endpoint(lambda: protocol, remote_addr=remote_addr)
        except Exception as e:
            raise ConnectionError(f"QUIC create_datagram_endpoint failed: {e}") from e

        if self._quic_connection:
            self._quic_connection.connect(remote_addr, now=loop.time())

    async def _initialize_protocol_handler(self, is_client: bool) -> None:
        """Create and configure the protocol handler."""
        if not self._quic_connection:
            raise ConnectionError("QUIC not established")
        self._protocol_handler = WebTransportProtocolHandler(
            self._quic_connection, is_client=is_client, connection=self
        )
        if not is_client:
            self._protocol_handler.on(EventType.SESSION_REQUEST, self._forward_session_request_from_handler)

    async def _initiate_webtransport_handshake(self, path: str) -> None:
        """Internal helper to start the WebTransport CONNECT handshake."""
        if not self._protocol_handler or not isinstance(self._config, ClientConfig):
            raise HandshakeError("Protocol handler or config not ready for handshake.")
        try:
            session_id, _ = await self._protocol_handler.create_webtransport_session(
                path=path, headers=self._config.headers
            )
            logger.debug(f"Initiated WebTransport handshake, session_id: {session_id}")
        except Exception as e:
            raise HandshakeError(f"WebTransport handshake failed: {e}") from e

    async def _forward_session_request_from_handler(self, event: Event) -> None:
        """Forward a session request event from the handler to this connection."""
        logger.debug(f"Forwarding SESSION_REQUEST from handler to connection {self.connection_id}")
        await self.emit(EventType.SESSION_REQUEST, data=event.data)

    def _start_background_tasks(self) -> None:
        """Start any background tasks like keep-alives."""
        if isinstance(self._config, ClientConfig) and getattr(self._config, "keep_alive", False):
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Periodically send PING frames to keep the connection alive."""
        interval = getattr(self._config, "keep_alive_interval", 30.0)
        try:
            while self.is_connected:
                await asyncio.sleep(interval)
                if self._quic_connection:
                    self._ping_uid_counter += 1
                    self._quic_connection.send_ping(uid=self._ping_uid_counter)
                self._transmit()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat loop error: {e}", exc_info=e)

    def _on_connection_lost(self, exc: Optional[Exception]) -> None:
        """Handle an unexpected connection loss."""
        if self._state in [ConnectionState.CLOSING, ConnectionState.CLOSED]:
            return
        logger.warning(f"Connection lost: {exc}")
        asyncio.create_task(self.close(reason=f"Connection lost: {exc}"))

    def _set_state(self, new_state: ConnectionState) -> None:
        """Set a new state for the connection and log the change."""
        if self._state == new_state:
            return
        old_state = self._state
        self._state = new_state
        self._info.state = new_state
        logger.debug(f"Connection {self._connection_id} state: {old_state.value} -> {new_state.value}")

    def _transmit(self) -> None:
        """Send all pending datagrams from the QUIC connection."""
        if self._quic_connection and self._transport:
            for data, addr in self._quic_connection.datagrams_to_send(now=asyncio.get_event_loop().time()):
                try:
                    self._transport.sendto(data, addr)
                except Exception:
                    pass
        self._schedule_transmit()

    def _schedule_transmit(self) -> None:
        """Schedule the next transmission based on the QUIC timer."""
        if self._timer_handle:
            self._timer_handle.cancel()
        if self._state != ConnectionState.CLOSED and self._quic_connection:
            timer_at = self._quic_connection.get_timer()
            if timer_at is not None:
                self._timer_handle = asyncio.get_event_loop().call_at(timer_at, self._transmit)

    async def _get_rtt(self) -> float:
        """Helper to get the latest RTT from the underlying QUIC connection."""
        if self._quic_connection and hasattr(self._quic_connection, "_rtt_smoother"):
            smoother = self._quic_connection._rtt_smoother
            if hasattr(smoother, "latest_rtt"):
                return cast(float, smoother.latest_rtt)
        raise ConnectionError("Connection not active or RTT is not available.")

    def __str__(self) -> str:
        """Format a concise, human-readable summary of a connection for logging."""
        info = self.info
        addr_str = f"{info.remote_address[0]}:{info.remote_address[1]}" if info.remote_address else "unknown"
        uptime_str = format_duration(info.uptime) if info.uptime > 0 else "0s"
        return (
            f"Connection({self.connection_id[:8]}..., state={info.state.value}, "
            f"remote={addr_str}, uptime={uptime_str})"
        )
