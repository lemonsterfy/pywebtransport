"""
Core Type Definitions.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any, AsyncContextManager, Protocol, TypeAlias, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from pywebtransport.connection import WebTransportConnection
    from pywebtransport.events import Event
    from pywebtransport.session import WebTransportSession
    from pywebtransport.stream import WebTransportReceiveStream, WebTransportStream

__all__ = [
    "Address",
    "AsyncContextManager",
    "AsyncGenerator",
    "AsyncIterator",
    "BidirectionalStreamProtocol",
    "Buffer",
    "BufferSize",
    "CertificateData",
    "ClientConfigProtocol",
    "ConnectionId",
    "ConnectionInfoProtocol",
    "ConnectionLostHandler",
    "ConnectionState",
    "ConnectionStats",
    "Data",
    "DatagramHandler",
    "ErrorCode",
    "ErrorHandler",
    "EventData",
    "EventHandler",
    "EventEmitterProtocol",
    "EventType",
    "FlowControlWindow",
    "Headers",
    "MiddlewareProtocol",
    "Priority",
    "PrivateKeyData",
    "ReadableStreamProtocol",
    "ReasonPhrase",
    "RouteHandler",
    "RoutePattern",
    "Routes",
    "SSLContext",
    "ServerConfigProtocol",
    "SessionHandler",
    "SessionId",
    "SessionInfoProtocol",
    "SessionState",
    "SessionStats",
    "StreamDirection",
    "StreamHandler",
    "StreamId",
    "StreamInfoProtocol",
    "StreamState",
    "StreamStats",
    "Timestamp",
    "Timeout",
    "TimeoutDict",
    "URL",
    "URLParts",
    "WebTransportProtocol",
    "Weight",
    "WritableStreamProtocol",
]

T = TypeVar("T")
P = TypeVar("P")


class ConnectionState(StrEnum):
    """Enumeration of connection states."""

    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"
    DRAINING = "draining"


class EventType(StrEnum):
    """Enumeration of system event types."""

    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_CLOSED = "connection_closed"
    SESSION_REQUEST = "session_request"
    SESSION_READY = "session_ready"
    SESSION_CLOSED = "session_closed"
    SESSION_DRAINING = "session_draining"
    STREAM_OPENED = "stream_opened"
    STREAM_CLOSED = "stream_closed"
    STREAM_DATA_RECEIVED = "stream_data_received"
    STREAM_ERROR = "stream_error"
    DATAGRAM_RECEIVED = "datagram_received"
    DATAGRAM_SENT = "datagram_sent"
    DATAGRAM_ERROR = "datagram_error"
    PROTOCOL_ERROR = "protocol_error"
    TIMEOUT_ERROR = "timeout_error"


class SessionState(StrEnum):
    """Enumeration of WebTransport session states."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    DRAINING = "draining"
    CLOSED = "closed"


class StreamDirection(StrEnum):
    """Enumeration of stream directions."""

    BIDIRECTIONAL = "bidirectional"
    SEND_ONLY = "send_only"
    RECEIVE_ONLY = "receive_only"


class StreamState(StrEnum):
    """Enumeration of WebTransport stream states."""

    IDLE = "idle"
    OPEN = "open"
    HALF_CLOSED_LOCAL = "half_closed_local"
    HALF_CLOSED_REMOTE = "half_closed_remote"
    CLOSED = "closed"
    RESET_SENT = "reset_sent"
    RESET_RECEIVED = "reset_received"


Address: TypeAlias = tuple[str, int]
Buffer: TypeAlias = bytes | bytearray | memoryview
BufferSize: TypeAlias = int
CertificateData: TypeAlias = str | bytes
ConnectionId: TypeAlias = str
ConnectionStats: TypeAlias = dict[str, int | float | str | list["SessionStats"]]
Data: TypeAlias = bytes | str
ErrorCode: TypeAlias = int
EventData: TypeAlias = Any
FlowControlWindow: TypeAlias = int
Headers: TypeAlias = dict[str, str]
Priority: TypeAlias = int
PrivateKeyData: TypeAlias = str | bytes
ReasonPhrase: TypeAlias = str
RoutePattern: TypeAlias = str
SSLContext: TypeAlias = ssl.SSLContext
SessionId: TypeAlias = str
SessionStats: TypeAlias = dict[str, int | float | str | list["StreamStats"]]
StreamId: TypeAlias = int
StreamStats: TypeAlias = dict[str, int | float | str]
Timestamp: TypeAlias = float
Timeout: TypeAlias = float | None
TimeoutDict: TypeAlias = dict[str, float]
URL: TypeAlias = str
URLParts: TypeAlias = tuple[str, int, str]
Weight: TypeAlias = int


if TYPE_CHECKING:
    ConnectionLostHandler: TypeAlias = Callable[[WebTransportConnection, Exception | None], Awaitable[None]]
    EventHandler: TypeAlias = Callable[[Event], Awaitable[None]]
    RouteHandler: TypeAlias = Callable[[WebTransportSession], Awaitable[None]]
    SessionHandler: TypeAlias = Callable[[WebTransportSession], Awaitable[None]]
    StreamHandler: TypeAlias = Callable[[WebTransportStream | WebTransportReceiveStream], Awaitable[None]]
else:
    ConnectionLostHandler: TypeAlias = Callable[[Any, Exception | None], Awaitable[None]]
    EventHandler: TypeAlias = Callable[[Any], Awaitable[None]]
    RouteHandler: TypeAlias = Callable[[Any], Awaitable[None]]
    SessionHandler: TypeAlias = Callable[[Any], Awaitable[None]]
    StreamHandler: TypeAlias = Callable[[Any], Awaitable[None]]

DatagramHandler: TypeAlias = Callable[[bytes], Awaitable[None]]
ErrorHandler: TypeAlias = Callable[[Exception], Awaitable[None]]
Routes: TypeAlias = dict[RoutePattern, RouteHandler]


@runtime_checkable
class ClientConfigProtocol(Protocol):
    """A protocol defining the structure of a client configuration object."""

    connect_timeout: float
    read_timeout: float | None
    write_timeout: float | None
    close_timeout: float
    max_streams: int
    stream_buffer_size: int
    verify_mode: ssl.VerifyMode | None
    ca_certs: str | None
    certfile: str | None
    keyfile: str | None
    check_hostname: bool
    alpn_protocols: list[str]
    http_version: str
    user_agent: str
    headers: Headers


@runtime_checkable
class ConnectionInfoProtocol(Protocol):
    """A protocol for retrieving connection information."""

    local_address: Address | None
    remote_address: Address | None
    state: ConnectionState
    established_at: float | None
    bytes_sent: int
    bytes_received: int
    streams_created: int
    datagrams_sent: int
    datagrams_received: int


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """A protocol for an event emitter."""

    async def emit(self, event_type: EventType, *, data: EventData | None = None) -> None:
        """Emit an event."""
        ...

    def off(self, event_type: EventType, *, handler: EventHandler | None = None) -> None:
        """Unregister an event handler."""
        ...

    def on(self, event_type: EventType, handler: EventHandler) -> None:
        """Register an event handler."""
        ...


@runtime_checkable
class MiddlewareProtocol(Protocol):
    """A protocol for a middleware object."""

    async def process_session(self, session: WebTransportSession) -> WebTransportSession:
        """Process a session through the middleware."""
        ...


@runtime_checkable
class ReadableStreamProtocol(Protocol):
    """A protocol for a readable stream."""

    def at_eof(self) -> bool:
        """Check if the end of the stream has been reached."""
        ...

    async def read(self, size: int = -1) -> bytes:
        """Read data from the stream."""
        ...

    async def readline(self, separator: bytes = b"\n") -> bytes:
        """Read a line from the stream."""
        ...

    async def readexactly(self, n: int) -> bytes:
        """Read exactly n bytes from the stream."""
        ...

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        """Read from the stream until a separator is found."""
        ...


@runtime_checkable
class WritableStreamProtocol(Protocol):
    """A protocol for a writable stream."""

    async def close(self, *, code: int | None = None, reason: str | None = None) -> None:
        """Close the stream."""
        ...

    async def flush(self) -> None:
        """Flush the stream's write buffer."""
        ...

    def is_closing(self) -> bool:
        """Check if the stream is in the process of closing."""
        ...

    async def write(self, data: Data) -> None:
        """Write data to the stream."""
        ...

    async def writelines(self, lines: list[Data]) -> None:
        """Write multiple lines to the stream."""
        ...


@runtime_checkable
class BidirectionalStreamProtocol(ReadableStreamProtocol, WritableStreamProtocol, Protocol):
    """A protocol for a bidirectional stream."""

    pass


@runtime_checkable
class ServerConfigProtocol(Protocol):
    """A protocol defining the structure of a server configuration object."""

    bind_host: str
    bind_port: int
    certfile: str
    keyfile: str
    ca_certs: str | None
    verify_mode: ssl.VerifyMode
    max_connections: int
    max_streams_per_connection: int
    connection_timeout: float
    read_timeout: float | None
    write_timeout: float | None
    alpn_protocols: list[str]
    http_version: str
    backlog: int
    reuse_port: bool
    keep_alive: bool


@runtime_checkable
class SessionInfoProtocol(Protocol):
    """A protocol for retrieving session information."""

    session_id: SessionId
    state: SessionState
    created_at: float
    ready_at: float | None
    closed_at: float | None
    streams_count: int
    bytes_sent: int
    bytes_received: int


@runtime_checkable
class StreamInfoProtocol(Protocol):
    """A protocol for retrieving stream information."""

    stream_id: StreamId
    direction: StreamDirection
    state: StreamState
    created_at: float
    closed_at: float | None
    bytes_sent: int
    bytes_received: int


@runtime_checkable
class WebTransportProtocol(Protocol):
    """A protocol for the underlying WebTransport transport layer."""

    def connection_made(self, transport: Any) -> None:
        """Called when a connection is established."""
        ...

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when a connection is lost."""
        ...

    def datagram_received(self, data: bytes, addr: Address) -> None:
        """Called when a datagram is received."""
        ...

    def error_received(self, exc: Exception) -> None:
        """Called when an error is received."""
        ...
