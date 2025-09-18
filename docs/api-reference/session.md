# API Reference: session

This document provides a reference for the `pywebtransport.session` subpackage, which contains the high-level abstractions for managing WebTransport sessions.

---

## WebTransportSession Class

The primary user-facing class that represents a single, long-lived logical connection.

**Note on Usage**: `WebTransportSession` is not instantiated directly but through a `WebTransportConnection`.

### Constructor

- **`def __init__(self, connection: WebTransportConnection, *, session_id: SessionId, max_streams: int = 100, ...)`**: Initializes a new session object.

### Properties

- `connection` (`WebTransportConnection | None`): A weak reference to the parent `WebTransportConnection`.
- `datagrams` (`WebTransportDatagramTransport`): Asynchronously accesses the datagram transport, creating it on first use.
- `headers` (`Headers`): A copy of the initial HTTP headers used to establish the session.
- `is_closed` (`bool`): `True` if the session is fully closed.
- `is_ready` (`bool`): `True` if the session is connected and ready for use.
- `path` (`str`): The URL path associated with the session.
- `protocol_handler` (`WebTransportProtocolHandler | None`): The underlying protocol handler.
- `session_id` (`SessionId`): The unique ID of the session.
- `state` (`SessionState`): The current state of the session.

### Instance Methods

- **`async def close(self, *, code: int = 0, reason: str = "", close_connection: bool = True) -> None`**: Closes the session.
- **`async def create_bidirectional_stream(self, *, timeout: float | None = None) -> WebTransportStream`**: Creates and returns a new bidirectional stream.
- **`async def create_structured_datagram_transport(self, *, serializer: Serializer, registry: dict[int, Type[Any]]) -> StructuredDatagramTransport`**: Creates a new structured datagram transport for sending and receiving objects.
- **`async def create_structured_stream(self, *, serializer: Serializer, registry: dict[int, Type[Any]], timeout: float | None = None) -> StructuredStream`**: Creates a new structured bidirectional stream for sending and receiving objects.
- **`async def create_unidirectional_stream(self, *, timeout: float | None = None) -> WebTransportSendStream`**: Creates and returns a new unidirectional (send-only) stream.
- **`async def debug_state(self) -> dict[str, Any]`**: Returns a detailed, structured snapshot of the session's internal state for debugging.
- **`async def diagnose_issues(self) -> list[str]`**: Runs checks and returns a list of strings describing potential issues.
- **`async def get_session_stats(self) -> dict[str, Any]`**: Returns a dictionary of current, detailed statistics for the session.
- **`async def get_summary(self) -> dict[str, Any]`**: Returns a structured summary of the session, suitable for monitoring.
- **`async def incoming_streams(self) -> AsyncIterator[StreamType]`**: Returns an async iterator that yields incoming streams from the remote peer.
- **`async def initialize(self) -> None`**: Initializes asyncio resources for the session.
- **`async def monitor_health(self, *, check_interval: float = 60.0) -> None`**: A long-running task that continuously monitors session health.
- **`async def ready(self, *, timeout: float = 30.0) -> None`**: Waits until the session is fully established and ready.
- **`async def wait_closed(self) -> None`**: Waits until the session is fully closed.

## SessionManager Class

A helper class for managing the lifecycle of multiple `WebTransportSession` objects.

**Note on Usage**: `SessionManager` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, max_sessions: int = 10000, session_cleanup_interval: float = 60.0)`**: Initializes the session manager.

### Class Methods

- **`def create(*, max_sessions: int = 10000, session_cleanup_interval: float = 60.0) -> SessionManager`**: Factory method to create a new session manager instance.

### Instance Methods

- **`async def add_session(self, *, session: WebTransportSession) -> SessionId`**: Adds a session to be managed.
- **`async def cleanup_closed_sessions(self) -> int`**: Finds and removes any sessions that are marked as closed.
- **`async def close_all_sessions(self) -> None`**: Closes all sessions currently being managed.
- **`async def get_all_sessions(self) -> list[WebTransportSession]`**: Returns a list of all managed sessions.
- **`async def get_session(self, *, session_id: SessionId) -> WebTransportSession | None`**: Retrieves a session by its ID.
- **`def get_session_count(self) -> int`**: Get the current number of active sessions (non-locking).
- **`async def get_sessions_by_state(self, *, state: SessionState) -> list[WebTransportSession]`**: Filters and returns sessions that are in a specific state.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics about the managed sessions.
- **`async def remove_session(self, *, session_id: SessionId) -> WebTransportSession | None`**: Removes a session from the manager.
- **`async def shutdown(self) -> None`**: Stops the background cleanup task and closes all sessions.

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

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
