# API Reference: Connection

This document provides a comprehensive reference for the `pywebtransport.connection` subpackage, which contains high-level abstractions for creating and managing WebTransport connections.

---

## Core Components

### WebTransportConnection Class

The core class representing a single WebTransport connection. It manages the connection lifecycle, protocol handling, and event emission.

#### Class Method Factories

- **`async def create_client(*, config: ClientConfig, host: str, port: int, path: str = "/") -> WebTransportConnection`**: The recommended way to create and establish a client connection in one step.
- **`async def create_server(*, config: ServerConfig, transport: Any, protocol: Any) -> WebTransportConnection`**: Creates and accepts a server-side connection instance from an underlying transport.

#### Instance Methods

- **`async def connect(self, host: str, port: int, path: str = "/") -> None`**: Establishes a client connection. Typically, the `create_client` factory is preferred.
- **`async def accept(self, transport: asyncio.DatagramTransport, protocol: QuicConnectionProtocol) -> None`**: Accepts an incoming server connection. Typically, the `create_server` factory is preferred.
- **`async def close(self, *, code: int = 0, reason: str = "") -> None`**: Gracefully closes the connection.
- **`async def wait_closed(self) -> None`**: Waits until the connection is fully closed.
- **`async def wait_ready(self, *, timeout: float = 30.0) -> None`**: Waits for the connection to be established and ready.
- **`async def wait_for_ready_session(self, *, timeout: float = 30.0) -> SessionId`**: Waits for a session to become ready on this connection.
- **`get_summary() -> dict[str, Any]`**: Returns a structured summary of the connection for monitoring.
- **`async def monitor_health(self, *, check_interval: float = 30.0, rtt_timeout: float = 5.0) -> None`**: A long-running task that monitors connection health with periodic RTT checks.
- **`async def diagnose_issues(self) -> dict[str, Any]`**: Runs a series of checks and returns a dictionary of potential issues and recommendations.
- **`def record_activity(self) -> None`**: Manually records network activity on the connection, primarily to reset its server-side idle timeout timer.

#### Properties

- `state` (`ConnectionState`): The current state of the connection (e.g., `IDLE`, `CONNECTING`, `CONNECTED`).
- `is_connected` (`bool`): `True` if the connection is established.
- `is_closed` (`bool`): `True` if the connection is fully closed.
- `connection_id` (`str`): The unique ID of the connection.
- `local_address` (`Address | None`): The local `(host, port)` tuple.
- `remote_address` (`Address | None`): The remote `(host, port)` tuple.
- `protocol_handler` (`WebTransportProtocolHandler | None`): The underlying protocol handler.
- `info` (`ConnectionInfo`): A data object with detailed connection statistics.

---

## High-Level Abstractions

### ConnectionManager Class

Manages the lifecycle of multiple `WebTransportConnection` objects.

**Note on Usage**: `ConnectionManager` must be used as an asynchronous context manager (`async with ...`) to ensure its internal resources are properly initialized and shut down.

#### Constructor

- **`__init__(self, *, max_connections: int = 3000, connection_cleanup_interval: float = 30.0, connection_idle_check_interval: float = 5.0, connection_idle_timeout: float = 60.0)`**: Initializes the connection manager.

#### Instance Methods

- **`async def add_connection(self, connection: WebTransportConnection) -> ConnectionId`**: Adds a connection to be managed.
- **`async def remove_connection(self, connection_id: ConnectionId) -> WebTransportConnection | None`**: Removes a connection.
- **`async def get_connection(self, connection_id: ConnectionId) -> WebTransportConnection | None`**: Retrieves a managed connection.
- **`async def get_all_connections(self) -> list[WebTransportConnection]`**: Returns a list of all managed connections.
- **`get_connection_count(self) -> int`**: Returns the current number of connections.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics about the manager and its connections.
- **`async def cleanup_closed_connections(self) -> int`**: Scans for and removes closed connections.
- **`async def close_all_connections(self) -> None`**: Closes all connections currently being managed.
- **`async def shutdown(self) -> None`**: Stops the background cleanup task and closes all connections.

### ConnectionPool Class

Manages a pool of reusable connections to reduce latency from connection setup.

**Note on Usage**: `ConnectionPool` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, *, max_size: int = 10, max_idle_time: float = 300.0, cleanup_interval: float = 60.0)`**: Initializes the connection pool.

#### Instance Methods

- **`async def get_connection(self, *, config: ClientConfig, host: str, port: int, path: str = "/") -> WebTransportConnection`**: Gets an available connection from the pool or creates a new one.
- **`async def return_connection(self, connection: WebTransportConnection) -> None`**: Returns a healthy connection to the pool for reuse.
- **`async def close_all(self) -> None`**: Closes all connections in the pool and shuts down the pool.
- **`get_stats(self) -> dict[str, Any]`**: Returns statistics about the pool's state.

### ConnectionLoadBalancer Class

Distributes connection requests across a list of target servers and performs health checks.

**Note on Usage**: `ConnectionLoadBalancer` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, *, targets: list[tuple[str, int]], health_check_interval: float = 30.0, ...)`**: Initializes the load balancer.

#### Instance Methods

- **`async def get_connection(self, config: ClientConfig, *, path: str = "/", strategy: str = "round_robin") -> WebTransportConnection`**: Gets a connection to the next available target based on the specified `strategy`.
- **`async def get_target_stats(self) -> dict[str, Any]`**: Returns health and performance stats for each target.
- **`async def get_load_balancer_stats(self) -> dict[str, Any]`**: Returns high-level stats about the load balancer.
- **`async def shutdown(self) -> None`**: Shuts down the load balancer, stopping health checks and closing all connections.

---

## Supporting Data Classes

### ConnectionInfo Class

A dataclass holding comprehensive statistics and information about a `WebTransportConnection`.

#### Attributes

- `connection_id` (`str`): The unique identifier for the connection.
- `state` (`ConnectionState`): The current state of the connection.
- `local_address` (`Address | None`): The local address.
- `remote_address` (`Address | None`): The remote address.
- `established_at` (`float | None`): Timestamp when the connection was established.
- `closed_at` (`float | None`): Timestamp when the connection was closed.
- `bytes_sent` (`int`): Total bytes sent.
- `bytes_received` (`int`): Total bytes received.
- `packets_sent` (`int`): Total packets sent.
- `packets_received` (`int`): Total packets received.
- `error_count` (`int`): Number of errors encountered.
- `last_activity` (`float | None`): Timestamp of the last activity.

#### Properties

- `uptime` (`float`): The total uptime of the connection in seconds.

---

## Utility Functions

These helper functions are available in the `pywebtransport.connection.utils` module.

- **`async def connect_with_retry(*, config: ClientConfig, host: str, port: int, ...)`**: Establishes a connection with an exponential backoff retry mechanism.
- **`async def ensure_connection(connection: WebTransportConnection, config: ClientConfig, ...)`**: Ensures a connection is active, reconnecting if necessary.
- **`async def create_multiple_connections(*, config: ClientConfig, targets: list[tuple[str, int]], ...)`**: Creates connections to multiple targets concurrently, with a concurrency limit.
- **`async def test_multiple_connections(*, targets: list[tuple[str, int]], timeout: float = 10.0)`**: Tests TCP connectivity to multiple targets concurrently.
- **`async def test_tcp_connection(*, host: str, port: int, timeout: float = 10.0) -> bool`**: Tests if a basic TCP connection can be established to a host and port.

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
