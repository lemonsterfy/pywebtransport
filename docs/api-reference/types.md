# API Reference: Types

This document provides a comprehensive reference for the type system used in `pywebtransport`. It covers enumerations, type aliases, and protocol interfaces that form the foundation of the library's public API, ensuring type safety and clear contracts for developers.

---

## Enumerations

Enumerations define constants for states, directions, and event types, providing a clear and readable way to handle specific conditions.

### ConnectionState

Defines the lifecycle states of a WebTransport connection.

```python
class ConnectionState(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"
    DRAINING = "draining"
```

### EventType

Defines the types of events emitted by the event system.

```python
class EventType(Enum):
    # Connection events
    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_FAILED = "connection_failed"

    # Session events
    SESSION_REQUEST = "session_request"
    SESSION_READY = "session_ready"
    SESSION_CLOSED = "session_closed"
    SESSION_DRAINING = "session_draining"

    # Stream events
    STREAM_OPENED = "stream_opened"
    STREAM_CLOSED = "stream_closed"
    STREAM_DATA_RECEIVED = "stream_data_received"
    STREAM_ERROR = "stream_error"

    # Datagram events
    DATAGRAM_RECEIVED = "datagram_received"
    DATAGRAM_SENT = "datagram_sent"
    DATAGRAM_ERROR = "datagram_error"

    # Protocol & Error events
    PROTOCOL_ERROR = "protocol_error"
    TIMEOUT_ERROR = "timeout_error"
```

### SessionState

Defines the lifecycle states of a WebTransport session.

```python
class SessionState(Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    DRAINING = "draining"
    CLOSED = "closed"
```

### StreamDirection

Defines the direction of data flow for a WebTransport stream.

```python
class StreamDirection(Enum):
    BIDIRECTIONAL = "bidirectional"
    SEND_ONLY = "send_only"
    RECEIVE_ONLY = "receive_only"
```

### StreamState

Defines the lifecycle states of a WebTransport stream.

```python
class StreamState(Enum):
    IDLE = "idle"
    OPEN = "open"
    HALF_CLOSED_LOCAL = "half_closed_local"
    HALF_CLOSED_REMOTE = "half_closed_remote"
    CLOSED = "closed"
    RESET_SENT = "reset_sent"
    RESET_RECEIVED = "reset_received"
```

---

## Core Type Aliases

These type aliases provide clear names for fundamental data types used throughout the library.

### Identifiers & Codes

- **`ConnectionId: TypeAlias = str`**: A unique identifier for a connection.
- **`SessionId: TypeAlias = str`**: A unique identifier for a session.
- **`StreamId: TypeAlias = int`**: A unique identifier for a stream.
- **`ErrorCode: TypeAlias = int`**: A numeric code for QUIC-level errors.
- **`ReasonPhrase: TypeAlias = str`**: A human-readable string explaining an error or closure.

### Network & URL

- **`Address: TypeAlias = Tuple[str, int]`**: A network address represented as a `(host, port)` tuple.
- **`URL: TypeAlias = str`**: A URL string, typically for a WebTransport endpoint.
- **`URLParts: TypeAlias = Tuple[str, int, str]`**: A parsed URL, containing `(host, port, path)`.
- **`Headers: TypeAlias = Dict[str, str]`**: A dictionary representing HTTP headers.

### Data & Buffers

- **`Data: TypeAlias = Union[bytes, str]`**: Represents data that can be sent over a stream.
- **`Buffer: TypeAlias = Union[bytes, bytearray, memoryview]`**: Represents a low-level buffer type.
- **`BufferSize: TypeAlias = int`**: An integer representing a buffer size in bytes.
- **`EventData: TypeAlias = Any`**: Represents the payload of a generic event.

### Timing & SSL

- **`Timestamp: TypeAlias = float`**: A Unix timestamp, typically from `time.time()`.
- **`Timeout: TypeAlias = Optional[float]`**: A timeout duration in seconds. `None` means no timeout.
- **`TimeoutDict: TypeAlias = Dict[str, float]`**: A dictionary of named timeout values.
- **`SSLContext: TypeAlias = ssl.SSLContext`**: An SSL context for secure connections.
- **`CertificateData: TypeAlias = Union[str, bytes]`**: A path to a certificate file or the raw certificate bytes.
- **`PrivateKeyData: TypeAlias = Union[str, bytes]`**: A path to a private key file or the raw key bytes.

### QUIC & Flow Control

- **`FlowControlWindow: TypeAlias = int`**: The size of a flow control window in bytes.
- **`Priority: TypeAlias = int`**: A priority level for streams or other resources.
- **`Weight: TypeAlias = int`**: A weight for resource allocation, often used with priority.

---

## Handler Type Aliases

These types define the signatures for asynchronous callback handlers used in the event system and routing.

- **`ConnectionLostHandler: TypeAlias = Callable[[WebTransportConnection, Optional[Exception]], Awaitable[None]]`**: Handles connection loss events.
- **`DatagramHandler: TypeAlias = Callable[[bytes], Awaitable[None]]`**: Handles incoming datagrams.
- **`ErrorHandler: TypeAlias = Callable[[Exception], Awaitable[None]]`**: A generic handler for error events.
- **`EventHandler: TypeAlias = Callable[[Event], Awaitable[None]]`**: A generic handler for any `Event` object.
- **`RouteHandler: TypeAlias = Callable[[WebTransportSession], Awaitable[None]]`**: A handler associated with a specific server route.
- **`SessionHandler: TypeAlias = Callable[[WebTransportSession], Awaitable[None]]`**: Handles session-related events, such as new session requests.
- **`StreamHandler: TypeAlias = Callable[[Union[WebTransportStream, WebTransportReceiveStream]], Awaitable[None]]`**: Handles new incoming streams.
- **`Routes: TypeAlias = Dict[RoutePattern, RouteHandler]`**: A dictionary mapping URL path patterns to their corresponding handlers.

---

## Protocol Interfaces

Protocol interfaces define the expected behavior of core components, enabling dependency injection and custom implementations (duck typing).

### Stream Protocols

#### `ReadableStreamProtocol`

Defines the contract for a stream that can be read from.

```python
@runtime_checkable
class ReadableStreamProtocol(Protocol):
    async def read(self, size: int = -1) -> bytes: ...
    async def readline(self, separator: bytes = b"\n") -> bytes: ...
    async def readexactly(self, n: int) -> bytes: ...
    async def readuntil(self, separator: bytes = b"\n") -> bytes: ...
    def at_eof(self) -> bool: ...
```

#### `WritableStreamProtocol`

Defines the contract for a stream that can be written to.

```python
@runtime_checkable
class WritableStreamProtocol(Protocol):
    async def write(self, data: Data) -> None: ...
    async def writelines(self, lines: List[Data]) -> None: ...
    async def flush(self) -> None: ...
    async def close(self, *, code: Optional[int] = None, reason: Optional[str] = None) -> None: ...
    def is_closing(self) -> bool: ...
```

#### `BidirectionalStreamProtocol`

A composite protocol for streams that are both readable and writable.

```python
@runtime_checkable
class BidirectionalStreamProtocol(ReadableStreamProtocol, WritableStreamProtocol, Protocol):
    pass
```

### Configuration Protocols

These protocols define the required attributes for client and server configuration objects.

- **`ClientConfigProtocol`**: Defines the structure for client-side configuration.
- **`ServerConfigProtocol`**: Defines the structure for server-side configuration.

### Information Protocols

These protocols define read-only interfaces for accessing statistics and state information.

- **`ConnectionInfoProtocol`**: Provides access to connection-level details and stats.
- **`SessionInfoProtocol`**: Provides access to session-level details and stats.
- **`StreamInfoProtocol`**: Provides access to stream-level details and stats.

### Core Component Protocols

- **`EventEmitterProtocol`**: Defines the contract for an event emitter (`on`, `off`, `emit`).
- **`MiddlewareProtocol`**: Defines the contract for server middleware (`process_session`).
- **`WebTransportProtocol`**: Defines the low-level interface for the underlying transport, handling events like `connection_made`, `datagram_received`, etc.

---

## Statistics Types

These type aliases define the structure for dictionaries containing performance and usage statistics.

- **`StreamStats: TypeAlias = Dict[str, Union[int, float, str]]`**: Statistics for a single stream.
- **`SessionStats: TypeAlias = Dict[str, Union[int, float, str, List[StreamStats]]]`**: Statistics for a single session, including a list of its stream stats.
- **`ConnectionStats: TypeAlias = Dict[str, Union[int, float, str, List[SessionStats]]]`**: Statistics for a single connection, including a list of its session stats.

---

## See Also

- [**Protocol API**](protocol.md): Protocol implementation details.
- [**Events API**](events.md): Learn about the event system and how to use handlers.
- [**Exceptions API**](exceptions.md): Understand the library's error and exception hierarchy.
- [**Constants API**](constants.md): Review default values and protocol-level constants.
