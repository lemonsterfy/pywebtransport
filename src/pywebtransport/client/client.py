"""WebTransport Client Implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from pywebtransport.config import ClientConfig
from pywebtransport.connection import ConnectionManager, WebTransportConnection
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ClientError, ConnectionError, TimeoutError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import URL, Headers
from pywebtransport.utils import Timer, format_duration, get_logger, get_timestamp, parse_webtransport_url, validate_url

if TYPE_CHECKING:
    from pywebtransport.client.reconnecting import ReconnectingClient


__all__ = ["ClientStats", "WebTransportClient"]

logger = get_logger(name="client")


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

    def __init__(self, *, config: ClientConfig | None = None) -> None:
        """Initialize the WebTransport client."""
        super().__init__()
        self._config = config or ClientConfig.create()
        self._connection_manager = ConnectionManager.create(
            max_connections=self._config.max_connections,
            connection_cleanup_interval=self._config.connection_cleanup_interval,
            connection_idle_check_interval=self._config.connection_idle_check_interval,
            connection_idle_timeout=self._config.connection_idle_timeout,
        )
        self._default_headers: Headers = {}
        self._closed = False
        self._stats = ClientStats()
        logger.info("WebTransport client initialized")

    @classmethod
    def create(cls, *, url: URL, config: ClientConfig | None = None) -> Self | ReconnectingClient:
        """Create a client, returning a ReconnectingClient if auto-reconnect is enabled."""
        from pywebtransport.client.reconnecting import ReconnectingClient

        final_config = config or ClientConfig.create()

        if final_config.auto_reconnect:
            logger.info("Auto-reconnect is enabled, creating a ReconnectingClient.")
            return ReconnectingClient.create(url=url, config=final_config)
        else:
            return cls(config=final_config)

    @property
    def is_closed(self) -> bool:
        """Check if the client is closed."""
        return self._closed

    @property
    def config(self) -> ClientConfig:
        """Get the client's configuration object."""
        return self._config

    @property
    def stats(self) -> dict[str, Any]:
        """Get a snapshot of the client's performance statistics."""
        return self._stats.to_dict()

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

        try:
            with Timer() as timer:
                connection_headers = self._default_headers.copy()
                if headers:
                    connection_headers.update(headers)

                conn_config = self._config.update(headers=connection_headers)
                connection = await WebTransportConnection.create_client(
                    config=conn_config, host=host, port=port, path=path
                )
                await self._connection_manager.add_connection(connection=connection)

                if not connection.protocol_handler:
                    raise ConnectionError(message="Protocol handler not initialized after connection")

                try:
                    session_id = await connection.wait_for_ready_session(timeout=connect_timeout)
                except asyncio.TimeoutError as e:
                    raise TimeoutError(message=f"Session ready timeout after {connect_timeout}s") from e

                session = WebTransportSession(
                    connection=connection,
                    session_id=session_id,
                    max_streams=conn_config.max_streams,
                    max_incoming_streams=conn_config.max_incoming_streams,
                    stream_cleanup_interval=conn_config.stream_cleanup_interval,
                )
                await session.initialize()

                connect_time = timer.elapsed
                self._stats.connections_successful += 1
                self._stats.total_connect_time += connect_time
                self._stats.min_connect_time = min(self._stats.min_connect_time, connect_time)
                self._stats.max_connect_time = max(self._stats.max_connect_time, connect_time)

                logger.info("Session established to %s in %s", url, format_duration(seconds=connect_time))
                return session
        except Exception as e:
            self._stats.connections_failed += 1
            if session and not session.is_closed:
                await session.close()
            if connection and not connection.is_closed:
                await connection.close()

            if isinstance(e, asyncio.TimeoutError):
                raise TimeoutError(message=f"Connection timeout to {url} after {connect_timeout}s") from e
            raise ClientError(message=f"Failed to connect to {url}: {e}") from e

    def debug_state(self) -> dict[str, Any]:
        """Get a detailed snapshot of the client's state for debugging."""
        return {
            "client": {
                "closed": self.is_closed,
                "default_headers": self._default_headers,
            },
            "config": self.config.to_dict(),
            "statistics": self.stats,
        }

    def diagnose_issues(self) -> list[str]:
        """Diagnose potential issues based on client connection statistics."""
        issues: list[str] = []
        stats = self.stats

        if self.is_closed:
            issues.append("Client is closed.")

        connections_stats = stats.get("connections", {})
        success_rate = connections_stats.get("success_rate", 1.0)
        if connections_stats.get("attempted", 0) > 10 and success_rate < 0.9:
            issues.append(f"Low connection success rate: {success_rate:.2%}")

        performance_stats = stats.get("performance", {})
        avg_connect_time = performance_stats.get("avg_connect_time", 0.0)
        if avg_connect_time > 5.0:
            issues.append(f"Slow average connection time: {avg_connect_time:.2f}s")

        return issues

    def set_default_headers(self, *, headers: Headers) -> None:
        """Set default headers for all subsequent connections."""
        self._default_headers = headers.copy()
