# API Reference: session

This document provides a reference for the `pywebtransport.session` subpackage, which contains the high-level abstractions for managing WebTransport sessions.

---

## SessionDiagnostics Class

A structured, immutable snapshot of a session's health.

### Attributes

- `stats` (`SessionStats`): The full statistics object for the session.
- `state` (`SessionState`): The current state of the session.
- `is_connection_active` (`bool`): `True` if the underlying connection is available and connected.
- `datagram_receive_buffer_size` (`int`): The current size of the datagram receive buffer.
- `send_credit_available` (`int`): Available flow control credit for sending data.
- `receive_credit_available` (`int`): Available flow control credit for receiving data.

### Properties

- `issues` (`list[str]`): Get a list of potential issues based on the current diagnostics.

## SessionStats Class

A dataclass that holds a comprehensive set of statistics for a `WebTransportSession`.

### Attributes

- `session_id` (`SessionId`): The unique identifier for the session.
- `created_at` (`float`): Timestamp when the session was created.
- `ready_at` (`float | None`): Timestamp when the session became ready. `Default: None`.
- `closed_at` (`float | None`): Timestamp when the session was closed. `Default: None`.
- `streams_created` (`int`): Total number of streams created. `Default: 0`.
- `streams_closed` (`int`): Total number of streams closed. `Default: 0`.
- `stream_errors` (`int`): Total number of stream errors. `Default: 0`.
- `bidirectional_streams` (`int`): Number of bidirectional streams. `Default: 0`.
- `unidirectional_streams` (`int`): Number of unidirectional streams. `Default: 0`.
- `datagrams_sent` (`int`): Total datagrams sent. `Default: 0`.
- `datagrams_received` (`int`): Total datagrams received. `Default: 0`.
- `protocol_errors` (`int`): Number of protocol errors. `Default: 0`.

### Properties

- `active_streams` (`int`): Current number of active streams.
- `uptime` (`float`): Total session uptime in seconds.

### Instance Methods

- **`def to_dict(self) -> dict[str, Any]`**: Converts the session statistics to a dictionary.

## WebTransportSession Class

The primary user-facing class that represents a single, long-lived logical connection.

**Note on Usage**: `WebTransportSession` is not instantiated directly but is typically provided by a `WebTransportClient` or a server application.

### Properties

- `connection` (`WebTransportConnection | None`): A weak reference to the parent `WebTransportConnection`.
- `headers` (`Headers`): A copy of the initial HTTP headers used to establish the session.
- `is_closed` (`bool`): `True` if the session is fully closed.
- `is_ready` (`bool`): `True` if the session is connected and ready for use.
- `path` (`str`): The URL path associated with the session.
- `protocol_handler` (`WebTransportProtocolHandler | None`): The underlying protocol handler.
- `session_id` (`SessionId`): The unique ID of the session.
- `state` (`SessionState`): The current state of the session.

### Instance Methods

- **`async def close(self, *, code: int = 0, reason: str = "", close_connection: bool = True) -> None`**: Closes the session and all its associated resources.
- **`async def create_bidirectional_stream(self, *, timeout: float | None = None) -> WebTransportStream`**: Creates and returns a new bidirectional stream.
- **`async def create_datagram_transport(self) -> WebTransportDatagramTransport`**: Creates a datagram transport for this session.
- **`async def create_unidirectional_stream(self, *, timeout: float | None = None) -> WebTransportSendStream`**: Creates and returns a new unidirectional (send-only) stream.
- **`async def diagnostics(self) -> SessionDiagnostics`**: Get a snapshot of the session's diagnostics and statistics.
- **`async def incoming_streams(self) -> AsyncIterator[StreamType]`**: Returns an async iterator that yields incoming streams from the remote peer.
- **`async def initialize(self) -> None`**: Initializes asyncio resources for the session.
- **`async def monitor_health(self, *, check_interval: float = 60.0) -> None`**: A long-running task that continuously monitors session health.
- **`async def ready(self, *, timeout: float = 30.0) -> None`**: Waits until the session is fully established and ready.
- **`async def wait_closed(self) -> None`**: Waits until the session is fully closed.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
