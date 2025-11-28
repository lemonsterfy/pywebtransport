"""Core server implementation for accepting WebTransport connections."""

from __future__ import annotations

import asyncio
from asyncio import BaseTransport, DatagramTransport
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

from aioquic.asyncio.server import QuicServer

from pywebtransport.config import ServerConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import ServerError
from pywebtransport.manager.connection import ConnectionManager
from pywebtransport.manager.session import SessionManager
from pywebtransport.server._adapter import WebTransportServerProtocol, create_server
from pywebtransport.types import Address, ConnectionState, EventType, SessionState
from pywebtransport.utils import get_logger, get_timestamp

__all__ = ["ServerDiagnostics", "ServerStats", "WebTransportServer"]

logger = get_logger(name=__name__)


@dataclass(frozen=True, kw_only=True)
class ServerDiagnostics:
    """A structured, immutable snapshot of a server's health."""

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
        stats_dict = self.stats.to_dict()

        if not self.is_serving:
            issues.append("Server is not currently serving.")

        total_attempts = stats_dict.get("total_connections_attempted", 0)
        success_rate = stats_dict.get("success_rate", 1.0)
        connections_rejected = stats_dict.get("connections_rejected", 0)

        if total_attempts > 20 and success_rate < 0.9:
            issues.append(f"High connection rejection rate: {connections_rejected}/{total_attempts}")

        active_connections = self.connection_states.get(ConnectionState.CONNECTED, 0)
        if self.max_connections > 0 and (active_connections / max(1, self.max_connections)) > 0.9:
            issues.append(f"High connection usage: {active_connections / self.max_connections:.1%}")

        try:
            cert_exists = Path(self.certfile_path).exists() if self.certfile_path else False
            key_exists = Path(self.keyfile_path).exists() if self.keyfile_path else False
            if not cert_exists:
                issues.append(f"Certificate file not found: {self.certfile_path}")
            if not key_exists:
                issues.append(f"Key file not found: {self.keyfile_path}")
        except Exception as e:
            issues.append(f"Certificate configuration check failed: {e}")

        return issues


@dataclass(kw_only=True)
class ServerStats:
    """Represent statistics for the server."""

    start_time: float | None = None
    connections_accepted: int = 0
    connections_rejected: int = 0
    connection_errors: int = 0
    protocol_errors: int = 0

    @property
    def total_connections_attempted(self) -> int:
        """Get the total number of connections attempted."""
        return self.connections_accepted + self.connections_rejected

    @property
    def success_rate(self) -> float:
        """Get the connection success rate."""
        total = self.total_connections_attempted
        if total == 0:
            return 1.0
        return self.connections_accepted / total

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to a dictionary."""
        data = asdict(obj=self)
        data["total_connections_attempted"] = self.total_connections_attempted
        data["success_rate"] = self.success_rate
        data["uptime"] = (get_timestamp() - self.start_time) if self.start_time else 0.0
        return data


class WebTransportServer(EventEmitter):
    """Manage the lifecycle and connections for the WebTransport server."""

    def __init__(self, *, config: ServerConfig | None = None) -> None:
        """Initialize the WebTransport server."""
        super().__init__()
        self._config = config or ServerConfig()
        self._config.validate()
        self._serving, self._closing = False, False
        self._server: QuicServer | None = None
        self._connection_manager = ConnectionManager(max_connections=self._config.max_connections)
        self._session_manager = SessionManager(max_sessions=self._config.max_sessions)
        self._background_tasks: list[asyncio.Task[Any]] = []
        self._stats = ServerStats()
        self._shutdown_event: asyncio.Event | None = None
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
            try:
                return cast(Address | None, self._server._transport.get_extra_info("sockname"))
            except OSError:
                return None
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
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context and close the server."""
        await self.close()

    async def close(self) -> None:
        """Gracefully shut down the server and its resources."""
        if not self._serving:
            return

        logger.info("Closing WebTransport server...")
        self._serving = False
        self._closing = True

        if self._shutdown_event:
            self._shutdown_event.set()

        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(coro=self._connection_manager.shutdown())
                tg.create_task(coro=self._session_manager.shutdown())
        except* Exception as eg:
            logger.error("Errors occurred during manager shutdown: %s", eg.exceptions, exc_info=eg)

        if self._server:
            self._server.close()

        self._closing = False
        logger.info("WebTransport server closed.")

    async def diagnostics(self) -> ServerDiagnostics:
        """Get a snapshot of the server's diagnostics and statistics."""
        async with asyncio.TaskGroup() as tg:
            conn_task = tg.create_task(coro=self._connection_manager.get_all_resources())
            sess_task = tg.create_task(coro=self._session_manager.get_all_resources())

        connections = conn_task.result()
        sessions = sess_task.result()
        connection_states = Counter(conn.state for conn in connections)
        session_states = Counter(sess.state for sess in sessions)

        return ServerDiagnostics(
            stats=self._stats,
            connection_states=dict(connection_states),
            session_states=dict(session_states),
            is_serving=self.is_serving,
            certfile_path=self.config.certfile or "",
            keyfile_path=self.config.keyfile or "",
            max_connections=self.config.max_connections,
        )

    async def listen(self, *, host: str | None = None, port: int | None = None) -> None:
        """Start the server and begin listening for connections."""
        if self._serving:
            raise ServerError(message="Server is already serving")

        bind_host, bind_port = host or self._config.bind_host, port or self._config.bind_port
        logger.info("Starting WebTransport server on %s:%s", bind_host, bind_port)

        self._shutdown_event = asyncio.Event()

        try:
            self._server = await create_server(
                host=bind_host, port=bind_port, config=self._config, connection_creator=self._create_connection_callback
            )
            self._serving = True
            self._stats.start_time = get_timestamp()
            logger.info("WebTransport server listening on %s", self.local_address)
        except FileNotFoundError as e:
            logger.critical("Certificate/Key file error: %s", e)
            raise ServerError(message=f"Certificate/Key file error: {e}") from e
        except Exception as e:
            logger.critical("Failed to start server: %s", e, exc_info=True)
            raise ServerError(message=f"Failed to start server: {e}") from e

    async def serve_forever(self) -> None:
        """Run the server indefinitely until interrupted."""
        if not self._serving or not self._server:
            raise ServerError(message="Server is not listening")

        logger.info("Server is running. Press Ctrl+C to stop.")
        try:
            if self._shutdown_event:
                await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("serve_forever cancelled.")
        except Exception as e:
            logger.error("Error during serve_forever wait: %s", e)
        finally:
            logger.info("serve_forever loop finished.")

    def _create_connection_callback(
        self, protocol: WebTransportServerProtocol, transport: BaseTransport
    ) -> WebTransportConnection | None:
        """Create a new WebTransportConnection from the protocol."""
        logger.debug("Creating WebTransportConnection via callback.")

        if not hasattr(transport, "sendto"):
            logger.error("Received transport without 'sendto' method: %s", type(transport).__name__)
            if hasattr(transport, "close"):
                if not hasattr(transport, "is_closing") or not transport.is_closing():
                    transport.close()
            return None

        try:
            connection = WebTransportConnection(
                config=self._config, protocol=protocol, transport=cast(DatagramTransport, transport), is_client=False
            )
            asyncio.create_task(coro=self._initialize_and_register_connection(connection=connection))
            return connection
        except Exception as e:
            logger.error("Error creating WebTransportConnection in callback: %s", e, exc_info=True)
            if not transport.is_closing():
                transport.close()
            return None

    async def _initialize_and_register_connection(self, connection: WebTransportConnection) -> None:
        """Initialize connection engine and register with manager."""
        try:

            async def forward_session_request(event: Event) -> None:
                event_data = event.data.copy() if isinstance(event.data, dict) else {}
                event_data["connection"] = connection
                await self.emit(event_type=EventType.SESSION_REQUEST, data=event_data)

            connection.events.on(event_type=EventType.SESSION_REQUEST, handler=forward_session_request)

            await connection.initialize()

            await self._connection_manager.add_connection(connection=connection)
            self._stats.connections_accepted += 1
            logger.info("New connection registered: %s", connection.connection_id)
        except Exception as e:
            self._stats.connections_rejected += 1
            self._stats.connection_errors += 1
            logger.error("Failed to initialize/register new connection: %s", e, exc_info=True)
            if not connection.is_closed:
                await connection.close()

    def __str__(self) -> str:
        """Format a concise summary of server information for logging."""
        status = "serving" if self.is_serving else "stopped"
        address_info = self.local_address
        address_str = f"{address_info[0]}:{address_info[1]}" if address_info else "unknown"
        conn_count = len(self._connection_manager)
        sess_count = len(self._session_manager)
        return (
            f"WebTransportServer(status={status}, "
            f"address={address_str}, "
            f"connections={conn_count}, "
            f"sessions={sess_count})"
        )
