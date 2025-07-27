# API Reference: Session

This document provides a comprehensive reference for the `pywebtransport.session` subpackage, which contains the high-level abstractions for managing WebTransport sessions.

---

## `WebTransportSession` Class

The primary user-facing class that represents a single, long-lived logical connection. It serves as the main entry point for creating streams and sending datagrams. It is an `EventEmitter` and also an async context manager.

### Key Methods

- **`create_bidirectional_stream(self, *, timeout: Optional[float] = None) -> WebTransportStream`**:
  Creates and returns a new bidirectional stream. Raises `StreamError` on timeout.

- **`create_unidirectional_stream(self, *, timeout: Optional[float] = None) -> WebTransportSendStream`**:
  Creates and returns a new unidirectional (send-only) stream. Raises `StreamError` on timeout.

- **`incoming_streams(self) -> AsyncIterator[StreamType]`**:
  Returns an async iterator that yields incoming streams (both bidirectional and unidirectional) initiated by the remote peer.

- **`ready(self, *, timeout: float = 30.0) -> None`**:
  Waits until the session is fully established and ready for communication. Raises `TimeoutError` if the timeout is exceeded.

- **`close(self, *, code: int = 0, reason: str = "") -> None`**:
  Closes the session and all its associated streams and datagrams.

- **`wait_closed(self) -> None`**:
  Waits until the session is fully closed.

- **`get_session_stats(self) -> Dict[str, Any]`**:
  Returns a dictionary of current, detailed statistics for the session.

### Properties

- **`datagrams` (WebTransportDatagramDuplexStream)**:
  Provides access to the datagram transport for sending and receiving datagrams. This property is lazily initialized on first access.

- **`state` (SessionState)**: The current state of the session (e.g., `CONNECTING`, `CONNECTED`, `CLOSED`).
- **`is_ready` (bool)**: `True` if the session is connected and ready for use.
- **`is_closed` (bool)**: `True` if the session is fully closed.
- **`session_id` (SessionId)**: The unique ID of the session.
- **`path` (str)**: The URL path associated with the session.
- **`headers` (Headers)**: The initial HTTP headers used to establish the session.
- **`connection` (Optional[WebTransportConnection])**: A weak reference to the parent `WebTransportConnection`.

---

## `SessionManager` Class

A helper class for managing the lifecycle of multiple `WebTransportSession` objects, particularly on the server side. It is an async context manager that handles background cleanup.

### Key Methods

- **`__init__(self, *, max_sessions: int = 1000, cleanup_interval: float = 300.0)`**
- **`add_session(self, session: WebTransportSession) -> SessionId`**:
  Adds a session to be managed. Raises `SessionError` if the manager is at capacity.

- **`remove_session(self, session_id: SessionId) -> Optional[WebTransportSession]`**:
  Removes a session from the manager.

- **`get_session(self, session_id: SessionId) -> Optional[WebTransportSession]`**:
  Retrieves a session by its ID.

- **`get_all_sessions(self) -> List[WebTransportSession]`**:
  Returns a list of all managed sessions.

- **`get_sessions_by_state(self, state: SessionState) -> List[WebTransportSession]`**:
  Filters and returns sessions that are in a specific state.

- **`get_stats(self) -> Dict[str, Any]`**:
  Returns detailed statistics about the sessions being managed.

- **`close_all_sessions(self) -> None`**:
  Closes all sessions currently being managed.

- **`shutdown(self) -> None`**:
  Stops the background cleanup task and closes all sessions.

---

## `SessionStats` Class

A dataclass that holds a comprehensive set of statistics for a `WebTransportSession`.

### Attributes

- `session_id` (SessionId)
- `created_at` (float)
- `ready_at` (Optional[float])
- `closed_at` (Optional[float])
- `streams_created` (int)
- `streams_closed` (int)
- `stream_errors` (int)
- `bidirectional_streams` (int)
- `unidirectional_streams` (int)
- `datagrams_sent` (int)
- `datagrams_received` (int)
- `protocol_errors` (int)
- `uptime` (property) -> float: Total session uptime in seconds.
- `active_streams` (property) -> int: Current number of active streams.

---

## See Also

- [**Connection API**](connection.md): The `WebTransportConnection` that hosts sessions.
- [**Stream API**](stream.md): The stream objects created and managed by the session.
- [**Datagram API**](datagram.md): The datagram stream accessed via `session.datagrams`.
- [**Exceptions API**](exceptions.md): Exceptions like `SessionError` that may be raised.
