# API Reference: manager

This document provides a reference for the `pywebtransport.manager` subpackage, which provides resource lifecycle managers. These managers typically operate as asynchronous context managers and often include background tasks for cleanup.

---

## ConnectionManager Class

Manages multiple concurrent `WebTransportConnection` objects, often used on the server-side to track incoming connections. Includes features for enforcing connection limits and automatically closing idle connections. Inherits common lifecycle management methods from an internal base class.

**Note on Usage**: `ConnectionManager` must be used as an asynchronous context manager (`async with manager: ...`) to initialize resources and start background cleanup/idle check tasks.

### Constructor

- **`def __init__(self, *, max_connections: int = DEFAULT_SERVER_MAX_CONNECTIONS, connection_cleanup_interval: float = DEFAULT_CONNECTION_CLEANUP_INTERVAL, connection_idle_check_interval: float = DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL, connection_idle_timeout: float = DEFAULT_CONNECTION_IDLE_TIMEOUT) -> None`**: Initializes the connection manager.
  - `max_connections` (`int`): Maximum number of concurrent connections allowed. `Default: 3000`.
  - `connection_cleanup_interval` (`float`): Interval in seconds for checking and removing closed connections. `Default: 30.0`.
  - `connection_idle_check_interval` (`float`): Interval in seconds for checking connection idle status. `Default: 5.0`.
  - `connection_idle_timeout` (`float`): Duration in seconds after which an idle connection will be closed. Set <= 0 to disable idle timeout. `Default: 60.0`.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context, initializing internal locks and starting background tasks (cleanup, idle check).
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context, shutting down background tasks and closing all managed connections.
- **`async def add_connection(self, *, connection: WebTransportConnection) -> ConnectionId`**: Adds a new, established connection to the manager. Raises `ConnectionError` if the maximum connection limit is exceeded. Returns the connection ID.
- **`async def cleanup_closed_resources(self) -> int`**: Scans managed connections, removes those that are closed, and returns the count of removed connections. Primarily for internal use by the background task but can be called manually.
- **`async def get_all_resources(self) -> list[WebTransportConnection]`**: Returns a list containing all currently managed (active) connections.
- **`async def get_resource(self, *, resource_id: ConnectionId) -> WebTransportConnection | None`**: Retrieves a specific connection by its ID, or `None` if not found.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics, including total created/closed, current count, max concurrent, max limit, and a breakdown of connections by their current state.
- **`async def remove_connection(self, *, connection_id: ConnectionId) -> WebTransportConnection | None`**: Removes a connection from the manager by its ID. Returns the removed connection or `None` if not found. Does not close the connection.
- **`async def shutdown(self) -> None`**: Initiates a graceful shutdown, stopping background tasks and closing all managed connections.

## SessionManager Class

Manages multiple concurrent `WebTransportSession` objects, typically used on the server-side within a connection or globally. Enforces session limits and handles cleanup. Inherits common lifecycle management methods from an internal base class.

**Note on Usage**: `SessionManager` must be used as an asynchronous context manager (`async with manager: ...`).

### Constructor

- **`def __init__(self, *, max_sessions: int = DEFAULT_MAX_SESSIONS, session_cleanup_interval: float = DEFAULT_SESSION_CLEANUP_INTERVAL) -> None`**: Initializes the session manager.
  - `max_sessions` (`int`): Maximum number of concurrent sessions allowed. `Default: 10000`.
  - `session_cleanup_interval` (`float`): Interval in seconds for checking and removing closed sessions. `Default: 60.0`.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context, initializing internal locks and starting the background cleanup task.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context, shutting down the background task and closing all managed sessions.
- **`async def add_session(self, *, session: WebTransportSession) -> SessionId`**: Adds a new, established session to the manager. Raises `SessionError` if the maximum session limit is exceeded. Returns the session ID.
- **`async def cleanup_closed_resources(self) -> int`**: Scans managed sessions, removes those that are closed, and returns the count of removed sessions. Primarily for internal use.
- **`async def get_all_resources(self) -> list[WebTransportSession]`**: Returns a list containing all currently managed (active) sessions.
- **`async def get_resource(self, *, resource_id: SessionId) -> WebTransportSession | None`**: Retrieves a specific session by its ID, or `None` if not found.
- **`async def get_sessions_by_state(self, *, state: SessionState) -> list[WebTransportSession]`**: Returns a list of managed sessions that are currently in the specified `SessionState`.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics, including total created/closed, current count, max concurrent, max limit, and a breakdown of sessions by their current state.
- **`async def remove_session(self, *, session_id: SessionId) -> WebTransportSession | None`**: Removes a session from the manager by its ID. Returns the removed session or `None` if not found. Does not close the session.
- **`async def shutdown(self) -> None`**: Initiates a graceful shutdown, stopping the background task and closing all managed sessions.

## StreamManager Class

Manages the lifecycle and concurrency limits of streams within a single `WebTransportSession`. Inherits common lifecycle management methods from an internal base class.

**Note on Usage**: `StreamManager` must be used as an asynchronous context manager (`async with manager: ...`).

### Constructor

- **`def __init__(self, *, stream_factory: Callable[[bool], Awaitable[StreamId]], session_factory: Callable[[], WebTransportSession], max_streams: int = DEFAULT_MAX_STREAMS, stream_cleanup_interval: float = DEFAULT_STREAM_CLEANUP_INTERVAL) -> None`**: Initializes the stream manager.
  - `stream_factory` (`Callable[[bool], Awaitable[StreamId]]`): An awaitable function (usually bound to a `WebTransportProtocolHandler` method) that takes a boolean `is_unidirectional` and returns a new `StreamId`.
  - `session_factory` (`Callable[[], WebTransportSession]`): A function that returns the parent `WebTransportSession` instance (used when creating stream objects).
  - `max_streams` (`int`): Maximum number of concurrent streams allowed within this session. `Default: 100`.
  - `stream_cleanup_interval` (`float`): Interval in seconds for checking and removing closed streams. `Default: 15.0`.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context, initializing locks, a semaphore for creation limits, and starting the background cleanup task.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context, shutting down the background task and closing all managed streams.
- **`async def __aiter__(self) -> AsyncIterator[StreamType]`**: Returns an async iterator over a snapshot of the currently managed streams.
- **`def __contains__(self, item: object) -> bool`**: Checks if a given stream ID (`int`) is currently managed.
- **`async def add_stream(self, *, stream: StreamType) -> None`**: Adds an externally created stream (e.g., an incoming stream) to the manager.
- **`async def cleanup_closed_resources(self) -> int`**: Scans managed streams, removes those that are closed (releasing semaphore counts if applicable), and returns the count of removed streams. Primarily for internal use.
- **`async def cleanup_closed_streams(self) -> int`**: Alias for `cleanup_closed_resources`.
- **`async def create_bidirectional_stream(self) -> WebTransportStream`**: Creates a new bidirectional stream, respecting the `max_streams` limit via an internal semaphore. Raises `StreamError` if the limit is reached.
- **`async def create_unidirectional_stream(self) -> WebTransportSendStream`**: Creates a new unidirectional (send-only) stream, respecting the `max_streams` limit. Raises `StreamError` if the limit is reached.
- **`async def get_all_resources(self) -> list[StreamType]`**: Returns a list containing all currently managed (active) streams.
- **`async def get_resource(self, *, resource_id: StreamId) -> StreamType | None`**: Retrieves a specific stream by its ID, or `None` if not found.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics, including total created/closed, current count, max concurrent, max limit, semaphore status, and breakdowns by stream state and direction.
- **`async def remove_stream(self, *, stream_id: StreamId) -> StreamType | None`**: Removes a stream from the manager by its ID (releasing semaphore counts if applicable). Returns the removed stream or `None` if not found. Does not close the stream.
- **`async def shutdown(self) -> None`**: Initiates a graceful shutdown, stopping the background task and closing all managed streams.

## Type Aliases

- **`StreamType`**: `WebTransportStream | WebTransportReceiveStream | WebTransportSendStream`
  A type alias representing any of the concrete WebTransport stream classes.

## See Also

- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.
