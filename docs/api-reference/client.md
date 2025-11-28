# API Reference: client

This document provides a reference for the `pywebtransport.client` subpackage, the client-side interface for the WebTransport protocol.

---

## WebTransportClient Class

The foundational class for establishing WebTransport connections and sessions. This class implements the asynchronous context manager protocol (`async with`) to manage the underlying connection manager.

### Constructor

- **`def __init__(self, *, config: ClientConfig | None = None) -> None`**: Initializes the WebTransport client.

### Properties

- `config` (`ClientConfig`): The client's configuration object.
- `is_closed` (`bool`): `True` if the client has been closed.

### Instance Methods

- **`async def close(self) -> None`**: Closes the client and all its underlying connections.
- **`async def connect(self, *, url: URL, timeout: float | None = None, headers: Headers | None = None) -> WebTransportSession`**: Connects to a WebTransport server at the specified URL and returns a new session. Raises `ClientError`, `ConnectionError`, or `TimeoutError` on failure.
- **`async def diagnostics(self) -> ClientDiagnostics`**: Asynchronously retrieves a snapshot of the client's diagnostics and statistics.
- **`def set_default_headers(self, *, headers: Headers) -> None`**: Sets default HTTP headers that will be included in all subsequent connection requests.

## ReconnectingClient Class

Maintains a persistent connection to a single URL, automatically reconnecting based on the client's configuration. This class implements the asynchronous context manager protocol (`async with`) to manage the reconnection loop.

### Constructor

- **`def __init__(self, *, url: URL, client: WebTransportClient) -> None`**: Initializes the reconnecting client.

### Properties

- `is_connected` (`bool`): `True` if the client currently has a ready session established.

### Instance Methods

- **`async def close(self) -> None`**: Closes the reconnecting client, stops the reconnection loop, and closes the current session.
- **`async def get_session(self, *, wait_timeout: float = 5.0) -> WebTransportSession | None`**: Returns the currently active session, waiting up to `wait_timeout` seconds if a connection is pending. Returns `None` if closed or timed out.

## WebTransportBrowser Class

A stateful, browser-like client that manages a single active session and navigation history. This class implements the asynchronous context manager protocol (`async with`) to manage resources.

### Constructor

- **`def __init__(self, *, client: WebTransportClient) -> None`**: Initializes the browser-like client.

### Properties

- `current_session` (`WebTransportSession | None`): The currently active session, or `None` if no page is loaded.

### Instance Methods

- **`async def back(self) -> WebTransportSession | None`**: Navigates to the previous URL in history. Returns `None` if at the beginning.
- **`async def close(self) -> None`**: Closes the browser, the current session, and all underlying resources.
- **`async def forward(self) -> WebTransportSession | None`**: Navigates to the next URL in history. Returns `None` if at the end.
- **`async def get_history(self) -> list[str]`**: Gets a copy of the navigation history list.
- **`async def navigate(self, *, url: str) -> WebTransportSession`**: Navigates to a new URL, closing the current session and clearing forward history.
- **`async def refresh(self) -> WebTransportSession | None`**: Reconnects to the current URL. Returns `None` if history is empty.

## ClientFleet Class

Manages a fleet of `WebTransportClient` instances to distribute load. This class implements the asynchronous context manager protocol (`async with`) to manage the lifecycle of all clients in the fleet.

### Constructor

- **`def __init__(self, *, clients: list[WebTransportClient]) -> None`**: Initializes the client fleet. Requires at least one client.

### Instance Methods

- **`async def close_all(self) -> None`**: Closes all clients in the fleet concurrently.
- **`async def connect_all(self, *, url: str) -> list[WebTransportSession]`**: Instructs all clients to connect to a URL concurrently. Returns a list of successfully established sessions.
- **`async def get_client(self) -> WebTransportClient`**: Gets the next available client using a round-robin strategy.
- **`def get_client_count(self) -> int`**: Returns the number of clients in the fleet.

## ClientDiagnostics Class

A structured, immutable snapshot of a client's health.

### Attributes

- `stats` (`ClientStats`): The full statistics object for the client.
- `connection_states` (`dict[ConnectionState, int]`): A count of connections in each state.

### Properties

- `issues` (`list[str]`): Get a list of potential issues based on the current diagnostics.

## ClientStats Class

Stores client-wide connection statistics.

### Attributes

- `created_at` (`float`): Timestamp when the client was created.
- `connections_attempted` (`int`): Total connection attempts. `Default: 0`.
- `connections_successful` (`int`): Total successful connections. `Default: 0`.
- `connections_failed` (`int`): Total failed connections. `Default: 0`.
- `total_connect_time` (`float`): Cumulative time spent connecting. `Default: 0.0`.
- `min_connect_time` (`float`): Minimum time taken to connect. `Default: inf`.
- `max_connect_time` (`float`): Maximum time taken to connect. `Default: 0.0`.

### Properties

- `avg_connect_time` (`float`): The average connection time.
- `success_rate` (`float`): The connection success rate.

### Instance Methods

- **`def to_dict(self) -> dict[str, Any]`**: Converts statistics to a dictionary.

## Module-Level Functions

- **`def parse_webtransport_url(*, url: URL) -> URLParts`**: Parses a WebTransport URL into `(host, port, path)`. Raises `ConfigurationError` if invalid.
- **`def validate_url(*, url: URL) -> bool`**: Validates the format of a WebTransport URL. Returns `True` if valid.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
