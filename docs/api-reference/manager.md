# API Reference: manager

This document provides a reference for the `pywebtransport.manager` subpackage, which provides resource lifecycle managers. These managers typically operate as asynchronous context managers.

---

## ConnectionManager Class

Manages multiple concurrent `WebTransportConnection` objects, typically used on the server-side to track incoming connections. It enforces connection limits and handles automated cleanup via event subscriptions. This class implements the asynchronous context manager protocol (`async with`).

### Constructor

- **`def __init__(self, *, max_connections: int) -> None`**: Initializes the connection manager.
  - `max_connections` (`int`): Maximum number of concurrent connections allowed.

### Instance Methods

- **`async def add_connection(self, *, connection: WebTransportConnection) -> ConnectionId`**: Adds a new, established connection to the manager. Raises `RuntimeError` if the manager is not active or shutting down. Returns the connection ID.
- **`async def get_all_resources(self) -> list[WebTransportConnection]`**: Returns a list containing all currently managed (active) connections.
- **`async def get_resource(self, *, resource_id: ConnectionId) -> WebTransportConnection | None`**: Retrieves a specific connection by its ID, or `None` if not found.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics, including total created/closed, current count, max concurrent, and a breakdown of connections by their current state.
- **`async def remove_connection(self, *, connection_id: ConnectionId) -> WebTransportConnection | None`**: Manually removes a connection from the manager by its ID. Returns the removed connection or `None` if not found.
- **`async def shutdown(self) -> None`**: Initiates a graceful shutdown, cancelling background tasks and closing all managed connections.

## SessionManager Class

Manages multiple concurrent `WebTransportSession` objects. It enforces session limits and handles cleanup via event subscriptions. This class implements the asynchronous context manager protocol (`async with`).

### Constructor

- **`def __init__(self, *, max_sessions: int) -> None`**: Initializes the session manager.
  - `max_sessions` (`int`): Maximum number of concurrent sessions allowed.

### Instance Methods

- **`async def add_session(self, *, session: WebTransportSession) -> SessionId`**: Adds a new, established session to the manager. Raises `RuntimeError` if the manager is not active or shutting down. Returns the session ID.
- **`async def get_all_resources(self) -> list[WebTransportSession]`**: Returns a list containing all currently managed (active) sessions.
- **`async def get_resource(self, *, resource_id: SessionId) -> WebTransportSession | None`**: Retrieves a specific session by its ID, or `None` if not found.
- **`async def get_sessions_by_state(self, *, state: SessionState) -> list[WebTransportSession]`**: Retrieves sessions that are in a specific state.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics, including total created/closed, current count, max concurrent, and a breakdown of sessions by their current state.
- **`async def remove_session(self, *, session_id: SessionId) -> WebTransportSession | None`**: Manually removes a session from the manager by its ID. Returns the removed session or `None` if not found.
- **`async def shutdown(self) -> None`**: Initiates a graceful shutdown, cancelling background tasks and closing all managed sessions.

## See Also

- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
