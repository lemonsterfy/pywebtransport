# API Reference: Session

This document provides a comprehensive reference for the `pywebtransport.session` subpackage, which contains the high-level abstractions for managing WebTransport sessions.

---

## Core Components

### WebTransportSession Class

The primary user-facing class that represents a single, long-lived logical connection. It serves as the main entry point for creating streams and sending datagrams. It inherits from `EventEmitter` and can be used as an async context manager for lifecycle management.

**Note on Initialization**: `WebTransportSession` objects have an asynchronous initialization phase. The factory methods that create them are responsible for calling `await session.initialize()` internally.

#### Key Methods

- **`async def create_bidirectional_stream(self, *, timeout: float | None = None) -> WebTransportStream`**: Creates and returns a new bidirectional stream.
- **`async def create_unidirectional_stream(self, *, timeout: float | None = None) -> WebTransportSendStream`**: Creates and returns a new unidirectional (send-only) stream.
- **`async def incoming_streams(self) -> AsyncIterator[StreamType]`**: Returns an async iterator that yields incoming streams initiated by the remote peer.
- **`async def initialize(self) -> None`**: Initializes asyncio resources for the session.
- **`async def ready(self, *, timeout: float = 30.0) -> None`**: Waits until the session is fully established and ready for communication.
- **`async def close(self, *, code: int = 0, reason: str = "", close_connection: bool = True) -> None`**: Closes the session. If `close_connection` is `True`, the underlying connection will also be closed.
- **`async def wait_closed(self) -> None`**: Waits until the session is fully closed.
- **`async def get_session_stats(self) -> dict[str, Any]`**: Returns a dictionary of current, detailed statistics for the session.
- **`async def get_summary(self) -> dict[str, Any]`**: Returns a structured summary of the session, suitable for monitoring dashboards.
- **`async def debug_state(self) -> dict[str, Any]`**: Returns a detailed, structured snapshot of the session's internal state for debugging.
- **`async def diagnose_issues(self) -> list[str]`**: Runs a series of checks and returns a list of human-readable strings describing potential issues.
- **`async def monitor_health(self, *, check_interval: float = 60.0) -> None`**: A long-running task that continuously monitors session health.

#### Properties

- `datagrams` (`WebTransportDatagramDuplexStream`): Asynchronously accesses the datagram stream, creating and initializing it on first use.
- `state` (`SessionState`): The current state of the session (e.g., `CONNECTING`, `CONNECTED`, `CLOSED`).
- `is_ready` (`bool`): `True` if the session is connected and ready for use.
- `is_closed` (`bool`): `True` if the session is fully closed.
- `session_id` (`SessionId`): The unique ID of the session.
- `path` (`str`): The URL path associated with the session.
- `headers` (`Headers`): A copy of the initial HTTP headers used to establish the session.
- `connection` (`WebTransportConnection | None`): A weak reference to the parent `WebTransportConnection`.

---

## High-Level Abstractions

### SessionManager Class

A helper class for managing the lifecycle of multiple `WebTransportSession` objects, particularly on the server side.

**Note on Usage**: `SessionManager` must be used as an asynchronous context manager (`async with ...`) to ensure its internal resources are properly initialized and shut down.

#### Constructor

- **`__init__(self, *, max_sessions: int = 10000, cleanup_interval: float = 60.0)`**: Initializes the session manager.

#### Key Methods

- **`async def add_session(self, session: WebTransportSession) -> SessionId`**: Adds a session to be managed.
- **`async def remove_session(self, session_id: SessionId) -> WebTransportSession | None`**: Removes a session from the manager.
- **`async def get_session(self, session_id: SessionId) -> WebTransportSession | None`**: Retrieves a session by its ID.
- **`async def get_all_sessions(self) -> list[WebTransportSession]`**: Returns a list of all managed sessions.
- **`async def get_sessions_by_state(self, state: SessionState) -> list[WebTransportSession]`**: Filters and returns sessions that are in a specific state.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics about the sessions being managed.
- **`async def close_all_sessions(self) -> None`**: Closes all sessions currently being managed.
- **`async def shutdown(self) -> None`**: Stops the background cleanup task and closes all sessions.

---

## Supporting Data Classes

### SessionStats Class

A dataclass that holds a comprehensive set of statistics for a `WebTransportSession`.

#### Attributes

- `session_id` (`SessionId`): The unique identifier for the session.
- `created_at` (`float`): Timestamp when the session was created.
- `ready_at` (`float | None`): Timestamp when the session became ready.
- `closed_at` (`float | None`): Timestamp when the session was closed.
- `streams_created` (`int`): Total number of streams created.
- `streams_closed` (`int`): Total number of streams closed.
- `stream_errors` (`int`): Total number of stream errors.
- `bidirectional_streams` (`int`): Number of bidirectional streams.
- `unidirectional_streams` (`int`): Number of unidirectional streams.
- `datagrams_sent` (`int`): Total datagrams sent.
- `datagrams_received` (`int`): Total datagrams received.
- `protocol_errors` (`int`): Number of protocol errors.

#### Properties

- `uptime` (`float`): Total session uptime in seconds.
- `active_streams` (`int`): Current number of active streams.

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
