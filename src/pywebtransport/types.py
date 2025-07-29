"""
Core Type Definitions.
"""

import ssl
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    TypeVar,
    Union,
    runtime_checkable,
)

from typing_extensions import TypeAlias

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


class ConnectionState(Enum):
    """Enumeration of connection states."""

    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"
    DRAINING = "draining"


class EventType(Enum):
    """Enumeration of system event types."""

    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_FAILED = "connection_failed"
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


class SessionState(Enum):
    """Enumeration of WebTransport session states."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    DRAINING = "draining"
    CLOSED = "closed"


class StreamDirection(Enum):
    """Enumeration of stream directions."""

    BIDIRECTIONAL = "bidirectional"
    SEND_ONLY = "send_only"
    RECEIVE_ONLY = "receive_only"


class StreamState(Enum):
    """Enumeration of WebTransport stream states."""

    IDLE = "idle"
    OPEN = "open"
    HALF_CLOSED_LOCAL = "half_closed_local"
    HALF_CLOSED_REMOTE = "half_closed_remote"
    CLOSED = "closed"
    RESET_SENT = "reset_sent"
    RESET_RECEIVED = "reset_received"


Address: TypeAlias = Tuple[str, int]
Buffer: TypeAlias = Union[bytes, bytearray, memoryview]
BufferSize: TypeAlias = int
CertificateData: TypeAlias = Union[str, bytes]
ConnectionId: TypeAlias = str
ConnectionStats: TypeAlias = Dict[str, Union[int, float, str, List["SessionStats"]]]
Data: TypeAlias = Union[bytes, str]
ErrorCode: TypeAlias = int
EventData: TypeAlias = Any
FlowControlWindow: TypeAlias = int
Headers: TypeAlias = Dict[str, str]
Priority: TypeAlias = int
PrivateKeyData: TypeAlias = Union[str, bytes]
ReasonPhrase: TypeAlias = str
RoutePattern: TypeAlias = str
SSLContext: TypeAlias = ssl.SSLContext
SessionId: TypeAlias = str
SessionStats: TypeAlias = Dict[str, Union[int, float, str, List["StreamStats"]]]
StreamId: TypeAlias = int
StreamStats: TypeAlias = Dict[str, Union[int, float, str]]
Timestamp: TypeAlias = float
Timeout: TypeAlias = Optional[float]
TimeoutDict: TypeAlias = Dict[str, float]
URL: TypeAlias = str
URLParts: TypeAlias = Tuple[str, int, str]
Weight: TypeAlias = int

if TYPE_CHECKING:
    ConnectionLostHandler: TypeAlias = Callable[["WebTransportConnection", Optional[Exception]], Awaitable[None]]
    EventHandler: TypeAlias = Callable[["Event"], Awaitable[None]]
    RouteHandler: TypeAlias = Callable[["WebTransportSession"], Awaitable[None]]
    SessionHandler: TypeAlias = Callable[["WebTransportSession"], Awaitable[None]]
    StreamHandler: TypeAlias = Callable[[Union["WebTransportStream", "WebTransportReceiveStream"]], Awaitable[None]]
else:
    ConnectionLostHandler: TypeAlias = Callable[[Any, Optional[Exception]], Awaitable[None]]
    EventHandler: TypeAlias = Callable[[Any], Awaitable[None]]
    RouteHandler: TypeAlias = Callable[[Any], Awaitable[None]]
    SessionHandler: TypeAlias = Callable[[Any], Awaitable[None]]
    StreamHandler: TypeAlias = Callable[[Any], Awaitable[None]]
DatagramHandler: TypeAlias = Callable[[bytes], Awaitable[None]]
ErrorHandler: TypeAlias = Callable[[Exception], Awaitable[None]]
Routes: TypeAlias = Dict[RoutePattern, RouteHandler]


@runtime_checkable
class ClientConfigProtocol(Protocol):
    """A protocol defining the structure of a client configuration object."""

    connect_timeout: float
    read_timeout: Optional[float]
    write_timeout: Optional[float]
    close_timeout: float
    max_streams: int
    stream_buffer_size: int
    verify_mode: Optional[ssl.VerifyMode]
    ca_certs: Optional[str]
    certfile: Optional[str]
    keyfile: Optional[str]
    check_hostname: bool
    alpn_protocols: List[str]
    http_version: str
    user_agent: str
    headers: Headers


@runtime_checkable
class ConnectionInfoProtocol(Protocol):
    """A protocol for retrieving connection information."""

    local_address: Optional[Address]
    remote_address: Optional[Address]
    state: ConnectionState
    established_at: Optional[float]
    bytes_sent: int
    bytes_received: int
    streams_created: int
    datagrams_sent: int
    datagrams_received: int


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """A protocol for an event emitter."""

    def on(self, event_type: EventType, handler: EventHandler) -> None:
        """Register an event handler."""
        ...

    def off(self, event_type: EventType, *, handler: Optional[EventHandler] = None) -> None:
        """Unregister an event handler."""
        ...

    async def emit(self, event_type: EventType, *, data: EventData = None) -> None:
        """Emit an event."""
        ...


@runtime_checkable
class MiddlewareProtocol(Protocol):
    """A protocol for a middleware object."""

    async def process_session(self, session: "WebTransportSession") -> "WebTransportSession":
        """Process a session through the middleware."""
        ...


@runtime_checkable
class ReadableStreamProtocol(Protocol):
    """A protocol for a readable stream."""

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

    def at_eof(self) -> bool:
        """Check if the end of the stream has been reached."""
        ...


@runtime_checkable
class WritableStreamProtocol(Protocol):
    """A protocol for a writable stream."""

    async def write(self, data: Data) -> None:
        """Write data to the stream."""
        ...

    async def writelines(self, lines: List[Data]) -> None:
        """Write multiple lines to the stream."""
        ...

    async def flush(self) -> None:
        """Flush the stream's write buffer."""
        ...

    async def close(self, *, code: Optional[int] = None, reason: Optional[str] = None) -> None:
        """Close the stream."""
        ...

    def is_closing(self) -> bool:
        """Check if the stream is in the process of closing."""
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
    ca_certs: Optional[str]
    verify_mode: ssl.VerifyMode
    max_connections: int
    max_streams_per_connection: int
    connection_timeout: float
    read_timeout: Optional[float]
    write_timeout: Optional[float]
    alpn_protocols: List[str]
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
    ready_at: Optional[float]
    closed_at: Optional[float]
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
    closed_at: Optional[float]
    bytes_sent: int
    bytes_received: int


@runtime_checkable
class WebTransportProtocol(Protocol):
    """A protocol for the underlying WebTransport transport layer."""

    def connection_made(self, transport: Any) -> None:
        """Called when a connection is established."""
        ...

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called when a connection is lost."""
        ...

    def datagram_received(self, data: bytes, addr: Address) -> None:
        """Called when a datagram is received."""
        ...

    def error_received(self, exc: Exception) -> None:
        """Called when an error is received."""
        ...
