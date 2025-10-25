"""Core server implementation for accepting WebTransport connections."""

from __future__ import annotations

import asyncio
import weakref
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.asyncio.server import QuicServer
from aioquic.asyncio.server import serve as quic_serve
from aioquic.quic.events import QuicEvent

from pywebtransport.config import ServerConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import ServerError
from pywebtransport.manager.connection import ConnectionManager
from pywebtransport.manager.session import SessionManager
from pywebtransport.types import Address, ConnectionState, EventType, SessionState
from pywebtransport.utils import create_quic_configuration, get_logger, get_timestamp

__all__: list[str] = ["ServerStats", "WebTransportServer", "WebTransportServerProtocol", "ServerDiagnostics"]

logger = get_logger(name=__name__)


@dataclass(frozen=True, kw_only=True)
class ServerDiagnostics:
    """Provide a structured, immutable snapshot of a server's health."""

    stats: ServerStats
    connection_states: dict[ConnectionState, int]
    session_states: dict[SessionState, int]
    is_serving: bool
    certfile_path: str
    keyfile_path: str
    max_connections: int

    @property
    def issues(self) -> list[str]:
        """Get a list of potential issues based on the current diagnostics."""
        issues: list[str] = []
        stats = self.stats

        if not self.is_serving:
            issues.append("Server is not currently serving.")

        total_conn_attempts = stats.connections_accepted + stats.connections_rejected
        if total_conn_attempts > 20 and (stats.connections_rejected / total_conn_attempts) > 0.1:
            issues.append(f"High connection rejection rate: {stats.connections_rejected}/{total_conn_attempts}")

        active_connections = self.connection_states.get(ConnectionState.CONNECTED, 0)
        if self.max_connections > 0 and (active_connections / self.max_connections) > 0.9:
            issues.append(f"High connection usage: {active_connections / self.max_connections:.1%}")

        try:
            if not Path(self.certfile_path).exists():
                issues.append(f"Certificate file not found: {self.certfile_path}")
            if not Path(self.keyfile_path).exists():
                issues.append(f"Key file not found: {self.keyfile_path}")
        except Exception:
            issues.append("Certificate configuration appears invalid.")

        return issues


@dataclass(kw_only=True)
class ServerStats:
    """Represent statistics for the server."""

    connections_accepted: int = 0
    connections_rejected: int = 0
    connection_errors: int = 0
    protocol_errors: int = 0
    uptime: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to a dictionary."""
        return asdict(obj=self)


class WebTransportServer(EventEmitter):
    """Manage the lifecycle and connections for the WebTransport server."""

    def __init__(self, *, config: ServerConfig | None = None) -> None:
        """Initialize the WebTransport server."""
        super().__init__()
        self._config = config or ServerConfig()
        self._config.validate()
        self._serving, self._closing = False, False
        self._server: QuicServer | None = None
        self._start_time: float | None = None
        self._connection_manager = ConnectionManager(
            max_connections=self._config.max_connections,
            connection_cleanup_interval=self._config.connection_cleanup_interval,
            connection_idle_check_interval=self._config.connection_idle_check_interval,
            connection_idle_timeout=self._config.connection_idle_timeout,
        )
        self._session_manager = SessionManager(
            max_sessions=self._config.max_sessions,
            session_cleanup_interval=self._config.session_cleanup_interval,
        )
        self._background_tasks: list[asyncio.Task[Any]] = []
        self._active_protocols: set[WebTransportServerProtocol] = set()
        self._stats = ServerStats()
        logger.info("WebTransport server initialized.")

    @property
    def config(self) -> ServerConfig:
        """Get the server's configuration object."""
        return self._config

    @property
    def connection_manager(self) -> ConnectionManager:
        """Get the server's connection manager instance."""
        return self._connection_manager

    @property
    def is_serving(self) -> bool:
        """Check if the server is currently serving."""
        return self._serving

    @property
    def local_address(self) -> Address | None:
        """Get the local address the server is bound to."""
        if self._server and hasattr(self._server, "_transport") and self._server._transport:
            return cast(Address | None, self._server._transport.get_extra_info("sockname"))
        return None

    @property
    def session_manager(self) -> SessionManager:
        """Get the server's session manager instance."""
        return self._session_manager

    async def __aenter__(self) -> Self:
        """Enter the async context for the server."""
        await self._connection_manager.__aenter__()
        await self._session_manager.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and close the server."""
        await self.close()

    async def close(self) -> None:
        """Gracefully shut down the server and its resources."""
        if not self._serving or self._closing:
            return

        logger.info("Closing WebTransport server...")
        self._closing = True
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._connection_manager.shutdown())
                tg.create_task(self._session_manager.shutdown())
        except* Exception as eg:
            logger.error("Errors occurred during manager shutdown: %s", eg.exceptions, exc_info=eg)

        if self._server:
            self._server.close()
            if hasattr(self._server, "wait_closed"):
                await self._server.wait_closed()
        self._serving, self._closing = False, False
        logger.info("WebTransport server closed.")

    async def listen(self, *, host: str | None = None, port: int | None = None) -> None:
        """Start the server and begin listening for connections."""
        if self._serving:
            raise ServerError(message="Server is already serving")

        bind_host, bind_port = host or self._config.bind_host, port or self._config.bind_port
        logger.info("Starting WebTransport server on %s:%s", bind_host, bind_port)
        try:
            quic_config = create_quic_configuration(
                is_client=False,
                alpn_protocols=self._config.alpn_protocols,
                congestion_control_algorithm=self._config.congestion_control_algorithm,
                max_datagram_size=self._config.max_datagram_size,
            )
            quic_config.load_cert_chain(certfile=Path(self._config.certfile), keyfile=Path(self._config.keyfile))
            if self._config.ca_certs:
                quic_config.load_verify_locations(cafile=self._config.ca_certs)
            quic_config.verify_mode = self._config.verify_mode
            self._server = await quic_serve(
                host=bind_host,
                port=bind_port,
                configuration=quic_config,
                create_protocol=lambda *a, **kw: WebTransportServerProtocol(self, *a, **kw),
            )
            self._serving, self._start_time = True, get_timestamp()
            logger.info("WebTransport server listening on %s", self.local_address)
        except Exception as e:
            logger.critical("Failed to start server: %s", e, exc_info=True)
            raise ServerError(message=f"Failed to start server: {e}") from e

    async def serve_forever(self) -> None:
        """Run the server indefinitely until interrupted."""
        if not self._serving or not self._server:
            raise ServerError(message="Server is not listening")

        logger.info("Server is running. Press Ctrl+C to stop.")
        try:
            if hasattr(self._server, "wait_closed"):
                await self._server.wait_closed()
            else:
                while self._serving:
                    await asyncio.sleep(3600)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Server stop signal received.")
        finally:
            await self.close()

    async def diagnostics(self) -> ServerDiagnostics:
        """Get a snapshot of the server's diagnostics and statistics."""
        if self._start_time:
            self._stats.uptime = get_timestamp() - self._start_time

        connections, sessions = await asyncio.gather(
            self._connection_manager.get_all_resources(),
            self._session_manager.get_all_resources(),
        )
        connection_states = Counter(conn.state for conn in connections)
        session_states = Counter(sess.state for sess in sessions)

        return ServerDiagnostics(
            stats=self._stats,
            connection_states=dict(connection_states),
            session_states=dict(session_states),
            is_serving=self.is_serving,
            certfile_path=self.config.certfile,
            keyfile_path=self.config.keyfile,
            max_connections=self.config.max_connections,
        )

    async def _handle_new_connection(
        self, *, transport: asyncio.BaseTransport, protocol: WebTransportServerProtocol
    ) -> None:
        """Handle a new incoming connection and set up the event forwarding chain."""
        connection: WebTransportConnection | None = None
        try:
            connection = WebTransportConnection(config=self._config)

            server_ref = weakref.ref(self)
            conn_ref = weakref.ref(connection)

            async def forward_session_request(event: Event) -> None:
                server = server_ref()
                conn = conn_ref()
                if server and conn and isinstance(event.data, dict):
                    event_data = event.data.copy()
                    if "connection" not in event_data:
                        event_data["connection"] = conn
                    logger.debug(
                        "Forwarding session request for path '%s' from connection %s to server.",
                        event_data.get("path"),
                        conn.connection_id,
                    )
                    await server.emit(event_type=EventType.SESSION_REQUEST, data=event_data)

            connection.on(event_type=EventType.SESSION_REQUEST, handler=forward_session_request)
            dgram_transport = cast(asyncio.DatagramTransport, transport)
            await connection.accept(transport=dgram_transport, protocol=protocol)
            await self._connection_manager.add_connection(connection=connection)
            self._stats.connections_accepted += 1
            logger.info("New connection accepted: %s", connection.connection_id)
        except Exception as e:
            self._stats.connections_rejected += 1
            self._stats.connection_errors += 1
            logger.error("Failed to handle new connection: %s", e, exc_info=True)
            if connection and not connection.is_closed:
                await connection.close()
            try:
                transport.close()
            except Exception:
                pass

    def __str__(self) -> str:
        """Format a concise summary of server information for logging."""
        status = "serving" if self.is_serving else "stopped"
        address = self.local_address or ("unknown", 0)
        conn_count = len(self._connection_manager)
        sess_count = len(self._session_manager)
        return (
            f"WebTransportServer(status={status}, "
            f"address={address[0]}:{address[1]}, "
            f"connections={conn_count}, "
            f"sessions={sess_count})"
        )


class WebTransportServerProtocol(QuicConnectionProtocol):
    """Implement the aioquic protocol for the WebTransport server."""

    _server_ref: weakref.ReferenceType[WebTransportServer]
    _connection_ref: weakref.ReferenceType[WebTransportConnection] | None
    _event_queue: asyncio.Queue[QuicEvent]
    _event_processor_task: asyncio.Task[None] | None

    def __init__(self, server: WebTransportServer, *args: Any, **kwargs: Any) -> None:
        """Initialize the server protocol."""
        super().__init__(*args, **kwargs)
        self._server_ref = weakref.ref(server)
        self._connection_ref = None
        self._event_queue = asyncio.Queue()
        self._event_processor_task = None

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle a connection being lost."""
        super().connection_lost(exc)
        if self._event_processor_task and not self._event_processor_task.done():
            self._event_processor_task.cancel()
        if self._connection_ref and (connection := self._connection_ref()):
            connection._on_connection_lost(exc=exc)
        if server := self._server_ref():
            server._active_protocols.discard(self)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Handle a new connection being made."""
        super().connection_made(transport)
        self._event_processor_task = asyncio.create_task(self._process_events_loop())
        if server := self._server_ref():
            server._active_protocols.add(self)
            asyncio.create_task(server._handle_new_connection(transport=transport, protocol=self))

    def quic_event_received(self, event: QuicEvent) -> None:
        """Handle a QUIC event from the underlying transport."""
        self._event_queue.put_nowait(event)

    def set_connection(self, *, connection: WebTransportConnection) -> None:
        """Set a weak reference to the managing WebTransportConnection."""
        self._connection_ref = weakref.ref(connection)

    def transmit(self) -> None:
        """Transmit any pending data."""
        if self._transport is not None and not self._transport.is_closing():
            super().transmit()

    async def _process_events_loop(self) -> None:
        """Continuously process events from the QUIC connection."""
        try:
            conn: WebTransportConnection | None = None
            while True:
                event = await self._event_queue.get()

                if conn is None:
                    if self._connection_ref and (conn := self._connection_ref()):
                        pass
                    else:
                        await self._event_queue.put(event)
                        await asyncio.sleep(0.01)
                        continue

                if conn.protocol_handler:
                    try:
                        await conn.protocol_handler.handle_quic_event(event=event)
                    except Exception as e:
                        logger.error("Error handling QUIC event for %s: %s", conn.connection_id, e, exc_info=True)
                else:
                    logger.warning(
                        "No handler available to process event for %s: %r",
                        conn.connection_id,
                        event,
                    )

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.critical("Fatal error in server event processing loop: %s", e, exc_info=True)
