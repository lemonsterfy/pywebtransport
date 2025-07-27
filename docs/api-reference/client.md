# API Reference: Client

This document provides a comprehensive reference for the `pywebtransport.client` subpackage, which contains the core client implementation and a suite of high-level abstractions for connection management, pooling, and monitoring.

---

## `WebTransportClient` Class

The foundational class for establishing WebTransport connections and creating sessions. It is an `EventEmitter` and an async context manager.

### Key Methods

- **`connect(self, url: URL, *, timeout: Optional[float] = None, headers: Optional[Headers] = None) -> WebTransportSession`**:
  Connects to a WebTransport server at the given URL and returns a ready-to-use `WebTransportSession`. This is the primary method for initiating communication.

- **`close(self) -> None`**:
  Closes the client and all its underlying connections.

### Properties

- **`is_closed` (bool)**: `True` if the client has been closed.
- **`stats` (Dict[str, Any])**: A dictionary of detailed client performance statistics.

---

## High-Level Client Abstractions

These classes provide specialized functionality built on top of the base `WebTransportClient`.

### `ClientPool` Class

Manages a pool of `WebTransportClient` instances to distribute concurrent `connect` calls across multiple clients, primarily for high-concurrency testing or scraping scenarios. It is an async context manager.

- **`get_client(self) -> WebTransportClient`**: Gets a client from the pool using a round-robin strategy.
- **`connect_all(self, url: str) -> List[WebTransportSession]`**: Instructs all clients in the pool to connect to a single URL concurrently.

### `PooledClient` Class

Manages pools of reusable `WebTransportSession` objects, keyed by endpoint URL. This is highly effective at reducing latency for applications that frequently connect to the same few endpoints by reusing active sessions. It is an async context manager.

- **`get_session(self, url: URL) -> WebTransportSession`**: Gets a reusable session from the pool for a specific URL, or creates a new one if none are available.
- **`return_session(self, session: WebTransportSession) -> None`**: Returns a healthy session to the pool for reuse.

### `ReconnectingClient` Class

Maintains a persistent connection to a single URL, automatically handling disconnects and reconnecting with an exponential backoff strategy. It is an `EventEmitter` and an async context manager.

- **`__init__(self, url: URL, *, config: Optional[ClientConfig] = None, ...)`**
- **`get_session(self) -> Optional[WebTransportSession]`**: Returns the currently active session, or `None` if disconnected.
- **`is_connected` (property)**: `True` if the client currently has a ready session.

### `WebTransportProxy` Class

Tunnels WebTransport connections through an HTTP proxy that supports the `CONNECT` method. It is an async context manager.

- **`connect_through_proxy(self, target_url: URL, *, ...) -> WebTransportStream`**: Establishes a raw tunnel to the target URL. The returned stream represents the tunnel and can be used for custom protocols.

### `WebTransportBrowser` Class

A stateful, browser-like client that manages a single active session and navigation history (`back`, `forward`, `refresh`). It is an async context manager.

- **`Maps(self, url: str) -> WebTransportSession`**: Navigates to a new URL, creating a new session.
- **`back(self) -> Optional[WebTransportSession]`**: Navigates to the previous URL in the history.
- **`forward(self) -> Optional[WebTransportSession]`**: Navigates to the next URL in the history.
- **`refresh(self) -> Optional[WebTransportSession]`**: Reconnects to the current URL.
- **`current_session` (property)**: The currently active `WebTransportSession`.

### `ClientMonitor` Class

An async context manager that periodically collects metrics and checks for performance alerts (e.g., low success rate, high latency) on a `WebTransportClient` instance.

- **`get_metrics_summary(self) -> Dict[str, Any]`**: Returns the latest metrics and any recent alerts.

---

## Supporting Data Classes

- **`ClientStats`**: A dataclass that holds aggregated statistics for a `WebTransportClient`, including connection attempts, success rate, and average connection times.

---

## Client Utility Functions

These helper functions are available in the `pywebtransport.client.utils` module.

- **`benchmark_client_performance(url: str, *, config: Optional[ClientConfig] = None, num_requests: int = 100, ...)`**:
  Runs a performance benchmark against a URL to measure request-response latency under concurrent load.

- **`test_client_connectivity(url: str, *, config: Optional[ClientConfig] = None, timeout: float = 10.0)`**:
  Performs a simple connection test to a URL and returns a dictionary with the result (`success`: bool) and connection time.

---

## See Also

- [**Session API**](session.md): The `WebTransportSession` object returned by `client.connect()`.
- [**Configuration API**](config.md): Details on the `ClientConfig` class.
- [**Connection API**](connection.md): The underlying connection objects managed by the client.
- [**Exceptions API**](exceptions.md): Exceptions like `ClientError` that may be raised.
