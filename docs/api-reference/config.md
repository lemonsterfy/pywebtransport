# API Reference: Client

This document provides a comprehensive reference for the `pywebtransport.client` subpackage, which contains the core client implementation and a suite of high-level abstractions for connection management, pooling, and monitoring.

---

## Core Components

### WebTransportClient Class

The foundational class for establishing WebTransport connections and creating sessions.

**Note on Usage**: `WebTransportClient` must be used as an asynchronous context manager (`async with ...`) to ensure its internal resources are properly managed.

#### Class Methods

- **`create(*, config: ClientConfig | None = None) -> WebTransportClient`**: The recommended factory method to create a new `WebTransportClient` instance.

#### Instance Methods

- **`async def connect(self, url: URL, *, timeout: float | None = None, headers: Headers | None = None) -> WebTransportSession`**: Connects to a WebTransport server at the given URL and returns a ready-to-use `WebTransportSession`.
- **`async def close(self) -> None`**: Closes the client and all its underlying connections.
- **`set_default_headers(self, headers: Headers) -> None`**: Sets default headers that will be sent with all subsequent `connect` calls.
- **`debug_state(self) -> dict[str, Any]`**: Returns a detailed snapshot of the client's internal state for debugging.
- **`diagnose_issues(self) -> list[str]`**: Analyzes client statistics to identify and report potential issues.

#### Properties

- `config` (`ClientConfig`): The client's configuration object.
- `is_closed` (`bool`): `True` if the client has been closed.
- `stats` (`dict[str, Any]`): A dictionary of detailed client performance statistics.

---

## High-Level Abstractions

### ClientPool Class

Manages a pool of `WebTransportClient` instances to distribute concurrent `connect` calls, ideal for high-concurrency testing or scraping.

#### Constructor

- **`__init__(self, configs: list[ClientConfig | None])`**: Initializes the client pool with a list of configurations for each client.

#### Instance Methods

- **`async def get_client(self) -> WebTransportClient`**: Gets a client from the pool using a round-robin strategy.
- **`async def connect_all(self, url: str) -> list[WebTransportSession]`**: Instructs all clients in the pool to connect to a single URL concurrently.

### PooledClient Class

Manages pools of reusable `WebTransportSession` objects, keyed by endpoint URL. This is highly effective at reducing latency by reusing active sessions.

#### Constructor

- **`__init__(self, *, config: ClientConfig | None = None, pool_size: int = 10, ...)`**: Initializes the session pool.

#### Instance Methods

- **`async def get_session(self, url: URL) -> WebTransportSession`**: Gets a reusable session from the pool for a specific URL, or creates a new one.
- **`async def return_session(self, session: WebTransportSession) -> None`**: Returns a healthy session to the pool for reuse.

### ReconnectingClient Class

Maintains a persistent connection to a single URL, automatically handling disconnects and reconnecting with an exponential backoff strategy. It inherits from `EventEmitter`.

#### Constructor

- **`__init__(self, url: URL, *, config: ClientConfig | None = None, ...)`**: Initializes the auto-reconnecting client.

#### Instance Methods

- **`async def get_session(self) -> WebTransportSession | None`**: Returns the currently active session, or `None` if disconnected.

#### Properties

- `is_connected` (`bool`): `True` if the client currently has a ready session.

### WebTransportProxy Class

Tunnels WebTransport connections through an HTTP proxy that supports the `CONNECT` method.

#### Constructor

- **`__init__(self, *, proxy_url: URL, config: ClientConfig | None = None)`**: Initializes the proxy client.

#### Instance Methods

- **`async def connect_through_proxy(self, target_url: URL, *, ...) -> WebTransportStream`**: Establishes a raw tunnel to the target URL.

### WebTransportBrowser Class

A stateful, browser-like client that manages a single active session and navigation history.

#### Constructor

- **`__init__(self, *, config: ClientConfig | None = None)`**: Initializes the browser-like client.

#### Instance Methods

- **`async def navigate(self, url: str) -> WebTransportSession`**: Navigates to a new URL, creating a new session.
- **`async def back(self) -> WebTransportSession | None`**: Navigates to the previous URL in the history.
- **`async def forward(self) -> WebTransportSession | None`**: Navigates to the next URL in the history.
- **`async def refresh(self) -> WebTransportSession | None`**: Reconnects to the current URL.

#### Properties

- `current_session` (`WebTransportSession`): The currently active `WebTransportSession`.

### ClientMonitor Class

Periodically collects metrics and checks for performance alerts on a `WebTransportClient` instance.

#### Constructor

- **`__init__(self, client: WebTransportClient, *, monitoring_interval: float = 30.0)`**: Initializes the monitor for a given client.

#### Instance Methods

- **`get_metrics_summary(self) -> dict[str, Any]`**: Returns the latest metrics and any recent alerts.

---

## Supporting Data Classes

### ClientStats Class

A dataclass that holds aggregated statistics for a `WebTransportClient`, including connection attempts, success rate, and average connection times.

---

## Utility Functions

These helper functions are available in the `pywebtransport.client.utils` module.

- **`async def benchmark_client_performance(url: str, *, config: ClientConfig | None = None, num_requests: int = 100, ...)`**: Runs a performance benchmark against a URL to measure request-response latency under concurrent load.
- **`async def test_client_connectivity(url: str, *, config: ClientConfig | None = None, timeout: float = 10.0)`**: Performs a simple connection test to a URL and returns a dictionary with the result (`success`: bool) and connection time.

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
