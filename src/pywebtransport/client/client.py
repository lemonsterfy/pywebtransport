"""
WebTransport Client Implementation.
"""

import asyncio
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Dict, List, Optional, Type

from pywebtransport.config import ClientConfig
from pywebtransport.connection import ConnectionManager, WebTransportConnection
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ClientError, TimeoutError
from pywebtransport.session import WebTransportSession
from pywebtransport.types import URL, Headers
from pywebtransport.utils import Timer, format_duration, get_logger, get_timestamp, parse_webtransport_url, validate_url

__all__ = ["ClientStats", "WebTransportClient"]

logger = get_logger("client")


@dataclass
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

    def to_dict(self) -> Dict[str, Any]:
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

    def __init__(self, *, config: Optional[ClientConfig] = None):
        """Initialize the WebTransport client."""
        super().__init__()
        self._config = config or ClientConfig.create()
        self._connection_manager = ConnectionManager.create(max_connections=100)
        self._default_headers: Headers = {}
        self._closed = False
        self._stats = ClientStats()
        logger.info("WebTransport client initialized")

    @classmethod
    def create(cls, *, config: Optional[ClientConfig] = None) -> "WebTransportClient":
        """Factory method to create a new WebTransport client instance."""
        return cls(config=config)

    @property
    def config(self) -> ClientConfig:
        """Get the client's configuration object."""
        return self._config

    @property
    def is_closed(self) -> bool:
        """Check if the client is closed."""
        return self._closed

    @property
    def stats(self) -> Dict[str, Any]:
        """Get a snapshot of the client's performance statistics."""
        return self._stats.to_dict()

    async def __aenter__(self) -> "WebTransportClient":
        """Enter the async context for the client."""
        await self._connection_manager.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
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
        url: URL,
        *,
        timeout: Optional[float] = None,
        headers: Optional[Headers] = None,
    ) -> WebTransportSession:
        """Connect to a WebTransport server and return a session."""
        if self._closed:
            raise ClientError("Client is closed")

        validate_url(url)
        host, port, path = parse_webtransport_url(url)
        connect_timeout = timeout or self._config.connect_timeout
        logger.info(f"Connecting to {host}:{port}{path}")
        self._stats.connections_attempted += 1

        connection: Optional[WebTransportConnection] = None
        try:
            with Timer() as timer:
                connection_headers = self._default_headers.copy()
                if headers:
                    connection_headers.update(headers)

                conn_config = self._config.update(headers=connection_headers)
                connection = WebTransportConnection(conn_config)

                await self._connection_manager.add_connection(connection)
                await connection.connect(host=host, port=port, path=path)

                if not connection.protocol_handler:
                    raise ConnectionError("Protocol handler not initialized after connection")

                try:
                    session_id = await connection.wait_for_ready_session(timeout=connect_timeout)
                except asyncio.TimeoutError as e:
                    raise TimeoutError(f"Session ready timeout after {connect_timeout}s") from e

                session = WebTransportSession(connection=connection, session_id=session_id)
                if not session.is_ready:
                    await session.ready(timeout=connect_timeout)

                connect_time = timer.elapsed
                self._stats.connections_successful += 1
                self._stats.total_connect_time += connect_time
                self._stats.min_connect_time = min(self._stats.min_connect_time, connect_time)
                self._stats.max_connect_time = max(self._stats.max_connect_time, connect_time)

                logger.info(f"Session established to {url} in {format_duration(connect_time)}")
                return session
        except Exception as e:
            self._stats.connections_failed += 1
            if connection and not connection.is_closed:
                await connection.close()

            if isinstance(e, asyncio.TimeoutError):
                raise TimeoutError(f"Connection timeout to {url} after {connect_timeout}s") from e
            raise ClientError(f"Failed to connect to {url}: {e}") from e

    def set_default_headers(self, headers: Headers) -> None:
        """Set default headers for all subsequent connections."""
        self._default_headers = headers.copy()

    def debug_state(self) -> Dict[str, Any]:
        """Get a detailed snapshot of the client's state for debugging."""
        return {
            "client": {"closed": self.is_closed, "default_headers": self._default_headers},
            "config": self.config.to_dict(),
            "statistics": self.stats,
        }

    def diagnose_issues(self) -> List[str]:
        """Diagnose potential issues based on client connection statistics."""
        issues: List[str] = []
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
