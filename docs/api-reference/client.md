# API Reference: client

This document provides a reference for the `pywebtransport.client` subpackage, the client-side interface for the WebTransport protocol.

---

## WebTransportClient Class

The foundational class for establishing WebTransport connections and creating sessions.

**Note on Usage**: The client must be used as an asynchronous context manager (`async with client: ...`).

### Constructor

- **`def __init__(self, *, config: ClientConfig | None = None, connection_factory: Callable[..., Awaitable[WebTransportConnection]] | None = None, session_factory: Callable[..., Awaitable[WebTransportSession]] | None = None) -> None`**: Initializes the WebTransport client. Allows optionally overriding the default factories used for creating connection and session objects.

### Properties

- `config` (`ClientConfig`): The client's configuration object.
- `is_closed` (`bool`): `True` if the client has been closed.

### Instance Methods

- **`async def close(self) -> None`**: Closes the client and all its underlying connections managed by its internal `ConnectionManager`.
- **`async def connect(self, *, url: URL, timeout: float | None = None, headers: Headers | None = None) -> WebTransportSession`**: Connects to a WebTransport server at the specified URL. Handles URL parsing, connection establishment (including proxy handshake if configured), WebTransport handshake, and returns a `WebTransportSession` upon success. Raises `ClientError`, `ConnectionError`, or `TimeoutError` on failure.
- **`async def diagnostics(self) -> ClientDiagnostics`**: Get a snapshot of the client's diagnostics, including aggregated statistics and connection state distribution.
- **`def set_default_headers(self, *, headers: Headers) -> None`**: Sets default HTTP headers that will be included in the initial request for all subsequent `connect` calls made by this client instance.

## ReconnectingClient Class

Maintains a persistent connection to a single URL, automatically reconnecting based on the parameters set in the underlying `WebTransportClient`'s `ClientConfig`.

**Note on Usage**: This client automatically manages the connection lifecycle. It must be used as an asynchronous context manager (`async with client: ...`).

### Constructor

- **`def __init__(self, *, url: URL, client: WebTransportClient) -> None`**: Initializes the reconnecting client. Requires the target URL and an underlying `WebTransportClient` instance whose configuration dictates retry behavior.

### Properties

- `is_connected` (`bool`): `True` if the client currently has a ready session established.

### Instance Methods

- **`async def close(self) -> None`**: Closes the reconnecting client, stops the reconnection loop, and closes the current session (if any).
- **`async def get_session(self, *, wait_timeout: float = 5.0) -> WebTransportSession | None`**: Returns the currently active `WebTransportSession`, waiting up to `wait_timeout` seconds if a connection is currently being established. Returns `None` if the client is closed or the timeout expires.

## WebTransportBrowser Class

A stateful, browser-like client that manages a single active session and navigation history (back/forward/refresh).

**Note on Usage**: `WebTransportBrowser` must be used as an asynchronous context manager (`async with browser: ...`).

### Constructor

- **`def __init__(self, *, client: WebTransportClient) -> None`**: Initializes the browser-like client, taking an underlying `WebTransportClient` instance to handle connections.

### Properties

- `current_session` (`WebTransportSession | None`): The currently active `WebTransportSession`, or `None` if no page is loaded or navigation failed.

### Instance Methods

- **`async def back(self) -> WebTransportSession | None`**: Navigates to the previous URL in the history, closing the current session and opening a new one. Returns the new session or `None` if at the beginning of history.
- **`async def close(self) -> None`**: Closes the browser, the current session, and all underlying resources associated with the client.
- **`async def forward(self) -> WebTransportSession | None`**: Navigates to the next URL in the history, closing the current session and opening a new one. Returns the new session or `None` if at the end of history.
- **`async def get_history(self) -> list[str]`**: Gets a copy of the navigation history list.
- **`async def navigate(self, *, url: str) -> WebTransportSession`**: Navigates to a new URL. Closes the current session (if any), establishes a new session to the given URL, updates the history (clearing forward entries), and returns the new `WebTransportSession`. Raises exceptions on connection failure.
- **`async def refresh(self) -> WebTransportSession | None`**: Reconnects to the current URL in the history, closing the current session and opening a new one. Returns the new session or `None` if history is empty.

## ClientFleet Class

Manages a collection (fleet) of `WebTransportClient` instances, distributing connection requests among them using a round-robin strategy.

**Note on Usage**: `ClientFleet` must be used as an asynchronous context manager (`async with fleet: ...`) to manage the lifecycle of the underlying clients.

### Constructor

- **`def __init__(self, *, clients: list[WebTransportClient]) -> None`**: Initializes the client fleet with a list of pre-configured `WebTransportClient` instances. Requires at least one client.

### Instance Methods

- **`async def close_all(self) -> None`**: Closes all `WebTransportClient` instances within the fleet concurrently.
- **`async def connect_all(self, *, url: str) -> list[WebTransportSession]`**: Instructs all clients in the fleet to connect to a single URL concurrently. Returns a list of successfully established sessions. Logs warnings for failed connections.
- **`async def get_client(self) -> WebTransportClient`**: Gets the next available client from the fleet using a round-robin strategy. Raises `ClientError` if the fleet is empty or not activated.
- **`def get_client_count(self) -> int`**: Returns the number of clients currently managed by the fleet.

## Supporting Data Classes

### ClientDiagnostics Class

A structured, immutable snapshot of a `WebTransportClient`'s health, including aggregated statistics and connection state distribution.

### Attributes

- `stats` (`ClientStats`): The full statistics object for the client.
- `connection_states` (`dict[ConnectionState, int]`): A dictionary mapping `ConnectionState` enums to the count of connections currently in that state within the client's internal manager.

### Properties

- `issues` (`list[str]`): A list of potential issues derived from the diagnostics (e.g., "Low connection success rate", "Slow average connection time").

### ClientStats Class

A dataclass that holds aggregated connection statistics for a `WebTransportClient`.

### Attributes

- `created_at` (`float`): Timestamp when the client statistics object was created. `Default: <factory>`.
- `connections_attempted` (`int`): Total number of connection attempts initiated by the client. `Default: 0`.
- `connections_successful` (`int`): Total number of connections that successfully reached the `CONNECTED` state and established a session. `Default: 0`.
- `connections_failed` (`int`): Total number of connection attempts that failed. `Default: 0`.
- `total_connect_time` (`float`): Cumulative time (in seconds) spent establishing successful connections. `Default: 0.0`.
- `min_connect_time` (`float`): The shortest time recorded for a successful connection establishment. `Default: inf`.
- `max_connect_time` (`float`): The longest time recorded for a successful connection establishment. `Default: 0.0`.

### Properties

- `avg_connect_time` (`float`): The average time (in seconds) taken to establish a successful connection.
- `success_rate` (`float`): The proportion of successful connection attempts (successful / attempted).

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
