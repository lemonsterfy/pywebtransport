# API Reference: types

This module provides a comprehensive reference for the type system, covering enumerations, type aliases, and protocol interfaces.

---

## Enumerations

### ConnectionState Class

Enumeration of connection states.

- `IDLE` (`str`): "idle"
- `CONNECTING` (`str`): "connecting"
- `CONNECTED` (`str`): "connected"
- `CLOSING` (`str`): "closing"
- `CLOSED` (`str`): "closed"
- `FAILED` (`str`): "failed"
- `DRAINING` (`str`): "draining"

### EventType Class

Enumeration of system event types.

- `CAPSULE_RECEIVED` (`str`): "capsule_received"
- `CONNECTION_ESTABLISHED` (`str`): "connection_established"
- `CONNECTION_LOST` (`str`): "connection_lost"
- `CONNECTION_FAILED` (`str`): "connection_failed"
- `CONNECTION_CLOSED` (`str`): "connection_closed"
- `DATAGRAM_ERROR` (`str`): "datagram_error"
- `DATAGRAM_RECEIVED` (`str`): "datagram_received"
- `DATAGRAM_SENT` (`str`): "datagram_sent"
- `PROTOCOL_ERROR` (`str`): "protocol_error"
- `SETTINGS_RECEIVED` (`str`): "settings_received"
- `SESSION_CLOSED` (`str`): "session_closed"
- `SESSION_DATA_BLOCKED` (`str`): "session_data_blocked"
- `SESSION_DRAINING` (`str`): "session_draining"
- `SESSION_MAX_DATA_UPDATED` (`str`): "session_max_data_updated"
- `SESSION_MAX_STREAMS_BIDI_UPDATED` (`str`): "session_max_streams_bidi_updated"
- `SESSION_MAX_STREAMS_UNI_UPDATED` (`str`): "session_max_streams_uni_updated"
- `SESSION_READY` (`str`): "session_ready"
- `SESSION_REQUEST` (`str`): "session_request"
- `SESSION_STREAMS_BLOCKED` (`str`): "session_streams_blocked"
- `STREAM_CLOSED` (`str`): "stream_closed"
- `STREAM_DATA_RECEIVED` (`str`): "stream_data_received"
- `STREAM_ERROR` (`str`): "stream_error"
- `STREAM_OPENED` (`str`): "stream_opened"
- `TIMEOUT_ERROR` (`str`): "timeout_error"

### SessionState Class

Enumeration of WebTransport session states.

- `CONNECTING` (`str`): "connecting"
- `CONNECTED` (`str`): "connected"
- `CLOSING` (`str`): "closing"
- `DRAINING` (`str`): "draining"
- `CLOSED` (`str`): "closed"

### StreamDirection Class

Enumeration of stream directions.

- `BIDIRECTIONAL` (`str`): "bidirectional"
- `SEND_ONLY` (`str`): "send_only"
- `RECEIVE_ONLY` (`str`): "receive_only"

### StreamState Class

Enumeration of WebTransport stream states.

- `OPEN` (`str`): "open"
- `HALF_CLOSED_LOCAL` (`str`): "half_closed_local"
- `HALF_CLOSED_REMOTE` (`str`): "half_closed_remote"
- `CLOSED` (`str`): "closed"
- `RESET_SENT` (`str`): "reset_sent"
- `RESET_RECEIVED` (`str`): "reset_received"

## Type Aliases

- `Address` (`tuple[str, int]`): A network address `(host, port)`.
- `AsyncContextManager` (`AsyncContextManager`): A re-export of `typing.AsyncContextManager`.
- `AsyncGenerator` (`AsyncGenerator`): A re-export of `collections.abc.AsyncGenerator`.
- `AsyncIterator` (`AsyncIterator`): A re-export of `collections.abc.AsyncIterator`.
- `Buffer` (`bytes | bytearray | memoryview`): A low-level buffer type.
- `ConnectionId` (`str`): A unique identifier for a connection.
- `Data` (`bytes | bytearray | memoryview | str`): Data that can be sent over a stream.
- `ErrorCode` (`int`): A numeric code for QUIC-level errors.
- `EventData` (`Any`): The payload of a generic event.
- `EventType` (`EventType`): An enumeration of event types.
- `Future` (`asyncio.Future`): An alias for `asyncio.Future`.
- `Headers` (`dict[str, str]`): HTTP headers.
- `Priority` (`int`): A priority level for resources.
- `SSLContext` (`ssl.SSLContext`): An SSL context for secure connections.
- `SessionId` (`str`): A unique identifier for a session.
- `StreamId` (`int`): A unique identifier for a stream.
- `Timestamp` (`float`): A Unix timestamp from `time.time()`.
- `Timeout` (`float | None`): A timeout duration in seconds.
- `URL` (`str`): A URL string for a WebTransport endpoint.
- `URLParts` (`tuple[str, int, str]`): A parsed URL `(host, port, path)`.
- `Weight` (`int`): A weight for resource allocation.

## Protocols

### AuthHandlerProtocol Protocol

A protocol for auth handlers.

### Instance Methods

- **`async def __call__(self, *, headers: Headers) -> bool`**: Processes request headers to authorize a session.

### MiddlewareProtocol Protocol

A protocol for a middleware object.

### Instance Methods

- **`async def __call__(self, *, session: Any) -> bool`**: Processes a session and returns `True` to allow or `False` to reject.

### Serializer Protocol

A protocol for serializing and deserializing structured data.

### Instance Methods

- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes an object into bytes.
- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any`**: Deserializes bytes into an object.

### WebTransportProtocol Protocol

A protocol for the underlying WebTransport transport layer.

### Instance Methods

- **`def connection_made(self, transport: Any) -> None`**: Called when a connection is established.
- **`def connection_lost(self, exc: Exception | None) -> None`**: Called when a connection is lost.
- **`def datagram_received(self, data: bytes, addr: Address) -> None`**: Called when a datagram is received.
- **`def error_received(self, exc: Exception) -> None`**: Called when an error is received.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
