# API Reference: types

This document provides a comprehensive reference for the type system, covering enumerations, type aliases, and protocol interfaces.

---

## ConnectionState Class

Enumeration of connection states.

- `IDLE` (`str`): "idle"
- `CONNECTING` (`str`): "connecting"
- `CONNECTED` (`str`): "connected"
- `CLOSING` (`str`): "closing"
- `CLOSED` (`str`): "closed"
- `FAILED` (`str`): "failed"
- `DRAINING` (`str`): "draining"

## EventType Class

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
- `SESSION_DRAINING` (`str`): "session_draining"
- `SESSION_MAX_DATA_UPDATED` (`str`): "session_max_data_updated"
- `SESSION_MAX_STREAMS_BIDI_UPDATED` (`str`): "session_max_streams_bidi_updated"
- `SESSION_MAX_STREAMS_UNI_UPDATED` (`str`): "session_max_streams_uni_updated"
- `SESSION_READY` (`str`): "session_ready"
- `SESSION_REQUEST` (`str`): "session_request"
- `STREAM_CLOSED` (`str`): "stream_closed"
- `STREAM_DATA_RECEIVED` (`str`): "stream_data_received"
- `STREAM_ERROR` (`str`): "stream_error"
- `STREAM_OPENED` (`str`): "stream_opened"
- `TIMEOUT_ERROR` (`str`): "timeout_error"

## SessionState Class

Enumeration of WebTransport session states.

- `CONNECTING` (`str`): "connecting"
- `CONNECTED` (`str`): "connected"
- `CLOSING` (`str`): "closing"
- `DRAINING` (`str`): "draining"
- `CLOSED` (`str`): "closed"

## StreamDirection Class

Enumeration of stream directions.

- `BIDIRECTIONAL` (`str`): "bidirectional"
- `SEND_ONLY` (`str`): "send_only"
- `RECEIVE_ONLY` (`str`): "receive_only"

## StreamState Class

Enumeration of WebTransport stream states.

- `IDLE` (`str`): "idle"
- `OPEN` (`str`): "open"
- `HALF_CLOSED_LOCAL` (`str`): "half_closed_local"
- `HALF_CLOSED_REMOTE` (`str`): "half_closed_remote"
- `CLOSED` (`str`): "closed"
- `RESET_SENT` (`str`): "reset_sent"
- `RESET_RECEIVED` (`str`): "reset_received"

## Type Aliases

- `Address` (`tuple[str, int]`): A network address `(host, port)`.
- `Buffer` (`bytes | bytearray | memoryview`): A low-level buffer type.
- `BufferSize` (`int`): A buffer size in bytes.
- `CertificateData` (`str | bytes`): A path to a certificate file or raw certificate bytes.
- `ConnectionId` (`str`): A unique identifier for a connection.
- `ConnectionStats` (`dict[str, int | float | str | list[SessionStats]]`): Statistics for a connection.
- `Data` (`bytes | str`): Data that can be sent over a stream.
- `ErrorCode` (`int`): A numeric code for QUIC-level errors.
- `EventData` (`Any`): The payload of a generic event.
- `FlowControlWindow` (`int`): The size of a flow control window in bytes.
- `Headers` (`dict[str, str]`): HTTP headers.
- `Priority` (`int`): A priority level for resources.
- `PrivateKeyData` (`str | bytes`): A path to a private key file or raw key bytes.
- `ReasonPhrase` (`str`): A human-readable explanation for an error or closure.
- `RoutePattern` (`str`): A URL path pattern for server-side routing.
- `SSLContext` (`ssl.SSLContext`): An SSL context for secure connections.
- `SessionId` (`str`): A unique identifier for a session.
- `SessionStats` (`dict[str, int | float | str | list[StreamStats]]`): Statistics for a session.
- `StreamId` (`int`): A unique identifier for a stream.
- `StreamStats` (`dict[str, int | float | str]`): Statistics for a stream.
- `Timestamp` (`float`): A Unix timestamp from `time.time()`.
- `Timeout` (`float | None`): A timeout duration in seconds.
- `TimeoutDict` (`dict[str, float]`): A dictionary of named timeout values.
- `URL` (`str`): A URL string for a WebTransport endpoint.
- `URLParts` (`tuple[str, int, str]`): A parsed URL `(host, port, path)`.
- `Weight` (`int`): A weight for resource allocation.

## Handler Types

- `ConnectionLostHandler` (`Callable[[WebTransportConnection, Exception | None], Awaitable[None]]`): Handles connection loss events.
- `DatagramHandler` (`Callable[[bytes], Awaitable[None]]`): Handles incoming datagrams.
- `ErrorHandler` (`Callable[[Exception], Awaitable[None]]`): A generic handler for error events.
- `EventHandler` (`Callable[[Event], Awaitable[None]]`): A generic handler for any `Event` object.
- `RouteHandler` (`Callable[[WebTransportSession], Awaitable[None]]`): A handler for a specific server route.
- `Routes` (`dict[RoutePattern, RouteHandler]`): A mapping of URL path patterns to handlers.
- `SessionHandler` (`Callable[[WebTransportSession], Awaitable[None]]`): Handles session-related events.
- `StreamHandler` (`Callable[[WebTransportStream | WebTransportReceiveStream], Awaitable[None]]`): Handles new incoming streams.

## ClientConfigProtocol Protocol

A protocol defining the structure of a client configuration object.

### Attributes

- `alpn_protocols` (`list[str]`): A list of ALPN protocols to negotiate.
- `auto_reconnect` (`bool`): Flag to enable or disable client auto-reconnection.
- `ca_certs` (`str | None`): Path to a CA certificate file for server verification.
- `certfile` (`str | None`): Path to a certificate file for client authentication.
- `close_timeout` (`float`): Time in seconds to wait for a graceful connection closure.
- `congestion_control_algorithm` (`str`): The congestion control algorithm to use.
- `connect_timeout` (`float`): Time in seconds to wait for connection establishment.
- `connection_cleanup_interval` (`float`): Interval in seconds for cleaning up closed connections.
- `connection_idle_check_interval` (`float`): Interval in seconds for checking connection idle status.
- `connection_idle_timeout` (`float`): Time in seconds after which an idle connection is closed.
- `connection_keepalive_timeout` (`float`): Time in seconds for sending keep-alive packets.
- `debug` (`bool`): Flag to enable or disable debug mode.
- `flow_control_window_auto_scale` (`bool`): Flag for flow control window auto-scaling.
- `flow_control_window_size` (`int`): The size of the flow control window.
- `headers` (`Headers`): Custom headers for the initial connection request.
- `initial_max_data` (`int`): Initial max data for flow control.
- `initial_max_streams_bidi` (`int`): Initial max bidirectional streams.
- `initial_max_streams_uni` (`int`): Initial max unidirectional streams.
- `keep_alive` (`bool`): Flag to enable or disable TCP keep-alive.
- `keyfile` (`str | None`): Path to a private key file for client authentication.
- `log_level` (`str`): The logging level for the client.
- `max_connections` (`int`): Maximum number of concurrent connections.
- `max_datagram_size` (`int`): Maximum size in bytes for an outgoing datagram.
- `max_incoming_streams` (`int`): Maximum number of concurrent incoming streams.
- `max_pending_events_per_session` (`int`): Maximum buffered events per pending session.
- `max_retries` (`int`): Maximum number of retries for a failed connection.
- `max_retry_delay` (`float`): Maximum delay in seconds between connection retries.
- `max_stream_buffer_size` (`int`): Maximum size in bytes for a stream buffer.
- `max_streams` (`int`): Maximum number of concurrent streams per connection.
- `max_total_pending_events` (`int`): Global maximum for buffered events.
- `pending_event_ttl` (`float`): TTL for buffered events in seconds.
- `read_timeout` (`float | None`): Timeout in seconds for stream read operations.
- `retry_backoff` (`float`): The backoff factor for connection retries.
- `retry_delay` (`float`): Initial delay in seconds between connection retries.
- `stream_buffer_size` (`int`): Default buffer size in bytes for streams.
- `stream_cleanup_interval` (`float`): Interval in seconds for cleaning up closed streams.
- `stream_creation_timeout` (`float`): Timeout in seconds for creating a new stream.
- `stream_flow_control_increment_bidi` (`int`): Stream increment for bidirectional flow control.
- `stream_flow_control_increment_uni` (`int`): Stream increment for unidirectional flow control.
- `user_agent` (`str`): The User-Agent string for the connection request.
- `verify_mode` (`ssl.VerifyMode | None`): The SSL verification mode.
- `write_timeout` (`float | None`): Timeout in seconds for stream write operations.

## AuthHandlerProtocol Protocol

A protocol for auth handlers.

### Instance Methods

- **`async def __call__(self, *, headers: Headers) -> bool`**: Processes request headers to authorize a session.

## ConnectionInfoProtocol Protocol

A protocol for retrieving connection information.

### Attributes

- `local_address` (`Address | None`): The local address of the connection.
- `remote_address` (`Address | None`): The remote address of the connection.
- `state` (`ConnectionState`): The current state of the connection.
- `established_at` (`float | None`): Timestamp when the connection was established.
- `bytes_sent` (`int`): Total bytes sent over the connection.
- `bytes_received` (`int`): Total bytes received over the connection.
- `streams_created` (`int`): Number of streams created on the connection.
- `datagrams_sent` (`int`): Number of datagrams sent over the connection.
- `datagrams_received` (`int`): Number of datagrams received over the connection.

## EventEmitterProtocol Protocol

A protocol for an event emitter.

### Instance Methods

- **`async def emit(self, *, event_type: EventType, data: EventData | None = None) -> None`**: Emits an event.
- **`def off(self, *, event_type: EventType, handler: EventHandler | None = None) -> None`**: Unregisters an event handler.
- **`def on(self, *, event_type: EventType, handler: EventHandler) -> None`**: Registers an event handler.

## MiddlewareProtocol Protocol

A protocol for a middleware object.

### Instance Methods

- **`async def __call__(self, *, session: WebTransportSession) -> bool`**: Processes a session and returns `True` to allow or `False` to reject.

## ReadableStreamProtocol Protocol

A protocol for a readable stream.

### Instance Methods

- **`def at_eof(self) -> bool`**: Checks if the end of the stream has been reached.
- **`async def read(self, *, size: int = -1) -> bytes`**: Reads data from the stream.
- **`async def readline(self, *, separator: bytes = b"\n") -> bytes`**: Reads a line from the stream.
- **`async def readexactly(self, *, n: int) -> bytes`**: Reads exactly `n` bytes from the stream.
- **`async def readuntil(self, *, separator: bytes = b"\n") -> bytes`**: Reads from the stream until a separator is found.

## Serializer Protocol

A protocol for serializing and deserializing structured data.

### Instance Methods

- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes an object into bytes.
- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any`**: Deserializes bytes into an object.

## WritableStreamProtocol Protocol

A protocol for a writable stream.

### Instance Methods

- **`async def close(self, *, code: int | None = None, reason: str | None = None) -> None`**: Closes the stream.
- **`async def flush(self) -> None`**: Flushes the stream's write buffer.
- **`def is_closing(self) -> bool`**: Checks if the stream is in the process of closing.
- **`async def write(self, *, data: Data) -> None`**: Writes data to the stream.
- **`async def writelines(self, *, lines: list[Data]) -> None`**: Writes multiple lines to the stream.

## BidirectionalStreamProtocol Protocol

A protocol for a bidirectional stream. Inherits from `ReadableStreamProtocol` and `WritableStreamProtocol`.

## ServerConfigProtocol Protocol

A protocol defining the structure of a server configuration object.

### Attributes

- `access_log` (`bool`): Flag to enable or disable the access log.
- `alpn_protocols` (`list[str]`): A list of ALPN protocols to negotiate.
- `bind_host` (`str`): The host address to bind the server to.
- `bind_port` (`int`): The port number to bind the server to.
- `ca_certs` (`str | None`): Path to a CA certificate file for client verification.
- `certfile` (`str`): Path to the server's certificate file.
- `congestion_control_algorithm` (`str`): The congestion control algorithm to use.
- `connection_cleanup_interval` (`float`): Interval in seconds for cleaning up closed connections.
- `connection_idle_check_interval` (`float`): Interval in seconds for checking connection idle status.
- `connection_idle_timeout` (`float`): Time in seconds after which an idle connection is closed.
- `connection_keepalive_timeout` (`float`): Time in seconds for sending keep-alive packets.
- `debug` (`bool`): Flag to enable or disable debug mode.
- `flow_control_window_auto_scale` (`bool`): Flag for flow control window auto-scaling.
- `flow_control_window_size` (`int`): The size of the flow control window.
- `initial_max_data` (`int`): Initial max data for flow control.
- `initial_max_streams_bidi` (`int`): Initial max bidirectional streams.
- `initial_max_streams_uni` (`int`): Initial max unidirectional streams.
- `keep_alive` (`bool`): Flag to enable or disable TCP keep-alive.
- `keyfile` (`str`): Path to the server's private key file.
- `log_level` (`str`): The logging level for the server.
- `max_connections` (`int`): Maximum number of concurrent client connections.
- `max_datagram_size` (`int`): Maximum size in bytes for an outgoing datagram.
- `max_incoming_streams` (`int`): Maximum number of concurrent incoming streams per session.
- `max_pending_events_per_session` (`int`): Maximum buffered events per pending session.
- `max_sessions` (`int`): Maximum number of concurrent sessions per connection.
- `max_stream_buffer_size` (`int`): Maximum size in bytes for a stream buffer.
- `max_streams_per_connection` (`int`): Maximum number of concurrent streams per connection.
- `max_total_pending_events` (`int`): Global maximum for buffered events.
- `middleware` (`list[Any]`): A list of middleware to apply to incoming sessions.
- `pending_event_ttl` (`float`): TTL for buffered events in seconds.
- `read_timeout` (`float | None`): Timeout in seconds for stream read operations.
- `session_cleanup_interval` (`float`): Interval in seconds for cleaning up closed sessions.
- `stream_buffer_size` (`int`): Default buffer size in bytes for streams.
- `stream_cleanup_interval` (`float`): Interval in seconds for cleaning up closed streams.
- `stream_flow_control_increment_bidi` (`int`): Stream increment for bidirectional flow control.
- `stream_flow_control_increment_uni` (`int`): Stream increment for unidirectional flow control.
- `verify_mode` (`ssl.VerifyMode`): The SSL verification mode for client certificates.
- `write_timeout` (`float | None`): Timeout in seconds for stream write operations.

## SessionInfoProtocol Protocol

A protocol for retrieving session information.

### Attributes

- `session_id` (`SessionId`): The unique ID of the session.
- `state` (`SessionState`): The current state of the session.
- `created_at` (`float`): Timestamp when the session was created.
- `ready_at` (`float | None`): Timestamp when the session became ready.
- `closed_at` (`float | None`): Timestamp when the session was closed.
- `streams_count` (`int`): The number of active streams in the session.
- `bytes_sent` (`int`): Total bytes sent during the session.
- `bytes_received` (`int`): Total bytes received during the session.

## StreamInfoProtocol Protocol

A protocol for retrieving stream information.

### Attributes

- `stream_id` (`StreamId`): The unique ID of the stream.
- `direction` (`StreamDirection`): The direction of the stream.
- `state` (`StreamState`): The current state of the stream.
- `created_at` (`float`): Timestamp when the stream was created.
- `closed_at` (`float | None`): Timestamp when the stream was closed.
- `bytes_sent` (`int`): Total bytes sent on the stream.
- `bytes_received` (`int`): Total bytes received on the stream.

## WebTransportProtocol Protocol

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
