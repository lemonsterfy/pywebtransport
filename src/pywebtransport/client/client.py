"""Primary entry point for client-side connections."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self

from pywebtransport.client._proxy import perform_proxy_handshake
from pywebtransport.client.utils import parse_webtransport_url, validate_url
from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ClientError, ConnectionError, TimeoutError
from pywebtransport.manager.connection import ConnectionManager
from pywebtransport.session import WebTransportSession
from pywebtransport.types import URL, ConnectionState, Headers
from pywebtransport.utils import Timer, format_duration, get_logger, get_timestamp

__all__: list[str] = ["ClientDiagnostics", "ClientStats", "WebTransportClient"]

logger = get_logger(name=__name__)


@dataclass(frozen=True, kw_only=True)
class ClientDiagnostics:
    """A structured, immutable snapshot of a client's health."""

    stats: ClientStats
    connection_states: dict[ConnectionState, int]

    @property
    def issues(self) -> list[str]:
        """Get a list of potential issues based on the current diagnostics."""
        issues: list[str] = []
        stats = self.stats.to_dict()

        connections_stats = stats.get("connections", {})
        success_rate = connections_stats.get("success_rate", 1.0)
        if connections_stats.get("attempted", 0) > 10 and success_rate < 0.9:
            issues.append(f"Low connection success rate: {success_rate:.2%}")

        performance_stats = stats.get("performance", {})
        avg_connect_time = performance_stats.get("avg_connect_time", 0.0)
        if avg_connect_time > 5.0:
            issues.append(f"Slow average connection time: {avg_connect_time:.2f}s")

        return issues


@dataclass(kw_only=True)
class ClientStats:
    """Stores client-wide connection statistics."""

    created_at: float = field(default_factory=get_timestamp)
    connections_attempted: int = 0
    connections_successful: int = 0
    connections_failed: int = 0
    total_connect_time: float = 0.0
    min_connect_time: float = float("inf")
    max_connect_time: float = 0.0

    @property
    def avg_connect_time(self) -> float:
        """Get the average connection time."""
        if self.connections_successful == 0:
            return 0.0

        return self.total_connect_time / self.connections_successful

    @property
    def success_rate(self) -> float:
        """Get the connection success rate."""
        if self.connections_attempted == 0:
            return 1.0

        return self.connections_successful / self.connections_attempted

    def to_dict(self) -> dict[str, Any]:
        """Convert statistics to a dictionary."""
        return {
            "created_at": self.created_at,
            "uptime": get_timestamp() - self.created_at,
            "connections": {
                "attempted": self.connections_attempted,
                "successful": self.connections_successful,
                "failed": self.connections_failed,
                "success_rate": self.success_rate,
            },
            "performance": {
                "avg_connect_time": self.avg_connect_time,
                "min_connect_time": (self.min_connect_time if self.min_connect_time != float("inf") else 0.0),
                "max_connect_time": self.max_connect_time,
            },
        }


class WebTransportClient(EventEmitter):
    """A client for establishing WebTransport connections and sessions."""

    def __init__(
        self,
        *,
        config: ClientConfig | None = None,
        connection_factory: Callable[..., Awaitable[WebTransportConnection]] | None = None,
        session_factory: Callable[..., Awaitable[WebTransportSession]] | None = None,
    ) -> None:
        """Initialize the WebTransport client."""
        super().__init__()
        self._config = config or ClientConfig()
        self._connection_manager = ConnectionManager(
            max_connections=self._config.max_connections,
            connection_cleanup_interval=self._config.connection_cleanup_interval,
            connection_idle_check_interval=self._config.connection_idle_check_interval,
            connection_idle_timeout=self._config.connection_idle_timeout,
        )
        self._default_headers: Headers = {}
        self._closed = False
        self._stats = ClientStats()

        async def _default_connection_factory(**kwargs: Any) -> WebTransportConnection:
            return await WebTransportConnection.create_client(**kwargs)

        async def _default_session_factory(**kwargs: Any) -> WebTransportSession:
            session = WebTransportSession(**kwargs)
            await session.initialize()
            return session

        self._connection_factory = connection_factory or _default_connection_factory
        self._session_factory = session_factory or _default_session_factory

        logger.info("WebTransport client initialized")

    @property
    def config(self) -> ClientConfig:
        """Get the client's configuration object."""
        return self._config

    @property
    def is_closed(self) -> bool:
        """Check if the client is closed."""
        return self._closed

    async def __aenter__(self) -> Self:
        """Enter the async context for the client."""
        await self._connection_manager.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and close the client."""
        await self.close()

    async def close(self) -> None:
        """Close the client and all its underlying connections."""
        if self._closed:
            return

        logger.info("Closing WebTransport client...")
        self._closed = True

        await self._connection_manager.shutdown()

        logger.info("WebTransport client closed.")

    async def connect(
        self,
        *,
        url: URL,
        timeout: float | None = None,
        headers: Headers | None = None,
    ) -> WebTransportSession:
        """Connect to a WebTransport server and return a session."""
        if self._closed:
            raise ClientError(message="Client is closed")

        validate_url(url=url)
        host, port, path = parse_webtransport_url(url=url)
        connect_timeout = timeout or self._config.connect_timeout
        logger.info("Connecting to %s:%s%s", host, port, path)
        self._stats.connections_attempted += 1

        connection: WebTransportConnection | None = None
        session: WebTransportSession | None = None
        success = False
        try:
            with Timer() as timer:
                connection_headers = self._default_headers.copy()
                if headers:
                    connection_headers.update(headers)

                connection = await self._establish_connection(
                    host=host, port=port, path=path, headers=connection_headers
                )

                session = await self._wait_for_session_and_create(connection=connection, timeout=connect_timeout)

                self._update_success_stats(connect_time=timer.elapsed)
                logger.info("Session established to %s in %s", url, format_duration(seconds=timer.elapsed))
                success = True
                return session
        except (TimeoutError, ConnectionError) as e:
            raise e
        except Exception as e:
            if isinstance(e, asyncio.TimeoutError):
                raise TimeoutError(message=f"Connection timeout to {url} after {connect_timeout}s") from e
            raise ClientError(message=f"Failed to connect to {url}: {e}") from e
        finally:
            if not success:
                self._stats.connections_failed += 1
                if session and not session.is_closed:
                    await session.close()
                if connection and not connection.is_closed:
                    await connection.close()

    async def diagnostics(self) -> ClientDiagnostics:
        """Get a snapshot of the client's diagnostics and statistics."""
        connections = await self._connection_manager.get_all_resources()
        state_counts = Counter(conn.state for conn in connections)

        return ClientDiagnostics(stats=self._stats, connection_states=dict(state_counts))

    def set_default_headers(self, *, headers: Headers) -> None:
        """Set default headers for all subsequent connections."""
        self._default_headers = headers.copy()

    async def _establish_connection(
        self, *, host: str, port: int, path: str, headers: Headers
    ) -> WebTransportConnection:
        """Handle proxying and create a new WebTransport connection."""
        conn_config = self._config.update(headers=headers)
        proxy_addr = None
        if conn_config.proxy:
            proxy_addr = await perform_proxy_handshake(config=conn_config, target_host=host, target_port=port)

        connection = await self._connection_factory(
            config=conn_config, host=host, port=port, path=path, proxy_addr=proxy_addr
        )
        await self._connection_manager.add_connection(connection=connection)
        return connection

    def _update_success_stats(self, *, connect_time: float) -> None:
        """Update connection statistics on a successful connection."""
        self._stats.connections_successful += 1
        self._stats.total_connect_time += connect_time
        self._stats.min_connect_time = min(self._stats.min_connect_time, connect_time)
        self._stats.max_connect_time = max(self._stats.max_connect_time, connect_time)

    async def _wait_for_session_and_create(
        self, *, connection: WebTransportConnection, timeout: float
    ) -> WebTransportSession:
        """Wait for the underlying session to be ready and create the session object."""
        if not connection.protocol_handler:
            raise ConnectionError(message="Protocol handler not initialized after connection")

        try:
            session_id = await connection.wait_for_ready_session(timeout=timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError(message=f"Session ready timeout after {timeout}s") from e

        conn_config = connection.config
        if not isinstance(conn_config, ClientConfig):
            raise ClientError(
                message="Internal error: A connection managed by WebTransportClient has a non-ClientConfig."
            )

        session = await self._session_factory(
            connection=connection,
            session_id=session_id,
            max_streams=conn_config.max_streams,
            max_incoming_streams=conn_config.max_incoming_streams,
            stream_cleanup_interval=conn_config.stream_cleanup_interval,
        )
        return session
