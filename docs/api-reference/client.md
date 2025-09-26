# API Reference: client

This document provides a reference for the `pywebtransport.client` subpackage, which contains the core client implementation and a suite of high-level abstractions.

---

## WebTransportClient Class

The foundational class for establishing WebTransport connections and creating sessions.

**Note on Usage**: The client must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, config: ClientConfig | None = None) -> None`**: Initializes the WebTransport client with a given configuration.

### Class Methods

- **`def create(*, url: URL, config: ClientConfig | None = None) -> WebTransportClient | ReconnectingClient`**: Smart factory that returns a `ReconnectingClient` if `config.auto_reconnect` is `True`, otherwise a standard `WebTransportClient`.

### Instance Methods

- **`async def connect(self, *, url: URL, timeout: float | None = None, headers: Headers | None = None) -> WebTransportSession`**: Connects to a server and returns a `WebTransportSession`.
- **`async def close(self) -> None`**: Closes the client and all its underlying connections.
- **`def set_default_headers(self, *, headers: Headers) -> None`**: Sets default headers for all subsequent `connect` calls.
- **`def debug_state(self) -> dict[str, Any]`**: Returns a detailed snapshot of the client's internal state for debugging.
- **`def diagnose_issues(self) -> list[str]`**: Analyzes client statistics to identify and report potential issues.

### Properties

- `config` (`ClientConfig`): The client's configuration object.
- `is_closed` (`bool`): `True` if the client has been closed.
- `stats` (`dict[str, Any]`): A dictionary of detailed client performance statistics.

## ClientPool Class

Manages a pool of `WebTransportClient` instances to distribute concurrent `connect` calls.

**Note on Usage**: `ClientPool` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, configs: list[ClientConfig | None]) -> None`**: Initializes the client pool with a list of configurations.

### Instance Methods

- **`async def get_client(self) -> WebTransportClient`**: Gets a client from the pool using a round-robin strategy.
- **`async def connect_all(self, *, url: str) -> list[WebTransportSession]`**: Instructs all clients in the pool to connect to a single URL concurrently.
- **`async def close_all(self) -> None`**: Closes all clients in the pool concurrently.
- **`def get_client_count(self) -> int`**: Gets the number of clients currently in the pool.

## PooledClient Class

Manages pools of reusable `WebTransportSession` objects, keyed by endpoint URL, to reduce latency.

**Note on Usage**: `PooledClient` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, config: ClientConfig | None = None, pool_size: int = 10, cleanup_interval: float = 60.0) -> None`**: Initializes the session pool.

### Instance Methods

- **`async def get_session(self, *, url: URL) -> WebTransportSession`**: Gets a reusable session from the pool for a specific URL, or creates a new one.
- **`async def return_session(self, *, session: WebTransportSession) -> None`**: Returns a healthy session to the pool for reuse.
- **`async def close(self) -> None`**: Closes all pooled sessions and the underlying client.

## ReconnectingClient Class

Maintains a persistent connection to a single URL, automatically reconnecting based on the parameters set in its `ClientConfig`.

**Note on Usage**: This class is typically not instantiated directly. Use `WebTransportClient.create()` with `auto_reconnect=True` in the `ClientConfig`. It must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, url: URL, config: ClientConfig) -> None`**: Initializes the reconnecting client.

### Class Methods

- **`def create(*, url: URL, config: ClientConfig) -> Self`**: Factory method to create a new `ReconnectingClient` instance.

### Instance Methods

- **`async def get_session(self, *, wait_timeout: float = 5.0) -> WebTransportSession | None`**: Returns the currently active session, waiting up to `wait_timeout` seconds if not immediately available.
- **`async def close(self) -> None`**: Closes the reconnecting client and all its resources.

### Properties

- `is_connected` (`bool`): `True` if the client currently has a ready session.

## WebTransportBrowser Class

A stateful, browser-like client that manages a single active session and navigation history.

**Note on Usage**: `WebTransportBrowser` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, config: ClientConfig | None = None) -> None`**: Initializes the browser-like client.

### Instance Methods

- **`async def navigate(self, *, url: str) -> WebTransportSession`**: Navigates to a new URL, creating a new session.
- **`async def back(self) -> WebTransportSession | None`**: Navigates to the previous URL in the history.
- **`async def forward(self) -> WebTransportSession | None`**: Navigates to the next URL in the history.
- **`async def refresh(self) -> WebTransportSession | None`**: Reconnects to the current URL.
- **`async def get_history(self) -> list[str]`**: Gets a copy of the navigation history.
- **`async def close(self) -> None`**: Closes the browser, the current session, and all underlying resources.

### Properties

- `current_session` (`WebTransportSession | None`): The currently active `WebTransportSession`.

## ClientMonitor Class

Periodically collects metrics and checks for performance alerts on a `WebTransportClient` instance.

**Note on Usage**: `ClientMonitor` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, client: WebTransportClient, *, monitoring_interval: float = 30.0) -> None`**: Initializes the monitor for a given client.

### Instance Methods

- **`def get_metrics_summary(self) -> dict[str, Any]`**: Returns the latest metrics and any recent alerts.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

## ClientStats Class

A dataclass that holds aggregated statistics for a `WebTransportClient`.

### Attributes

- `created_at` (`float`): Timestamp when the client was created. `Default: current timestamp`.
- `connections_attempted` (`int`): Total connections attempted. `Default: 0`.
- `connections_successful` (`int`): Total successful connections. `Default: 0`.
- `connections_failed` (`int`): Total failed connections. `Default: 0`.
- `total_connect_time` (`float`): Cumulative time spent in successful connections. `Default: 0.0`.
- `min_connect_time` (`float`): The shortest connection time. `Default: inf`.
- `max_connect_time` (`float`): The longest connection time. `Default: 0.0`.

### Properties

- `avg_connect_time` (`float`): The average connection time.
- `success_rate` (`float`): The connection success rate.

## Utility Functions

- **`async def benchmark_client_performance(*, url: str, config: ClientConfig | None = None, num_requests: int = 100, concurrent_requests: int = 10) -> dict[str, Any]`**: Runs a performance benchmark against a URL.
- **`async def test_client_connectivity(*, url: str, config: ClientConfig | None = None, timeout: float = 10.0) -> dict[str, Any]`**: Performs a connection test to a URL.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
