# API Reference: connection

This document provides a reference for the `pywebtransport.connection` subpackage, which contains high-level abstractions for creating and managing WebTransport connections.

---

## WebTransportConnection Class

The core class representing a single WebTransport connection.

### Class Methods

- **`async def create_client(*, config: ClientConfig, host: str, port: int, path: str = "/") -> Self`**: Creates and establishes a client connection in one step.
- **`async def create_server(*, config: ServerConfig, transport: Any, protocol: Any) -> Self`**: Creates and accepts a server-side connection instance from an underlying transport.

### Instance Methods

- **`async def accept(self, *, transport: asyncio.DatagramTransport, protocol: QuicConnectionProtocol) -> None`**: Accepts an incoming server connection.
- **`async def close(self, *, code: int = 0, reason: str = "") -> None`**: Gracefully closes the connection.
- **`async def diagnose_issues(self) -> dict[str, Any]`**: Runs checks and returns a dictionary of potential issues and recommendations.
- **`def get_ready_session_id(self) -> SessionId | None`**: Gets the ID of the first available ready session, if any.
- **`def get_summary(self) -> dict[str, Any]`**: Returns a structured summary of the connection for monitoring.
- **`async def monitor_health(self, *, check_interval: float = 30.0, rtt_timeout: float = 5.0) -> None`**: A long-running task that monitors connection health with periodic RTT checks.
- **`def record_activity(self) -> None`**: Manually records network activity on the connection to reset its idle timer.
- **`async def wait_closed(self) -> None`**: Waits until the connection is fully closed.
- **`async def wait_ready(self, *, timeout: float = 30.0) -> None`**: Waits for the connection to be established and ready.
- **`async def wait_for_ready_session(self, *, timeout: float = 30.0) -> SessionId`**: Waits for a session to become ready on this connection.

### Properties

- `config` (`ClientConfig | ServerConfig`): The configuration object for this connection.
- `connection_id` (`str`): The unique ID of the connection.
- `info` (`ConnectionInfo`): A data object with detailed connection statistics.
- `is_closed` (`bool`): `True` if the connection is fully closed.
- `is_closing` (`bool`): `True` if the connection is in the process of closing.
- `is_connected` (`bool`): `True` if the connection is established.
- `local_address` (`Address | None`): The local `(host, port)` tuple.
- `protocol_handler` (`WebTransportProtocolHandler | None`): The underlying protocol handler.
- `remote_address` (`Address | None`): The remote `(host, port)` tuple.
- `state` (`ConnectionState`): The current state of the connection.

## ConnectionManager Class

Manages the lifecycle of multiple `WebTransportConnection` objects.

**Note on Usage**: `ConnectionManager` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, max_connections: int = 3000, ...) -> None`**: Initializes the connection manager.

### Instance Methods

- **`async def add_connection(self, *, connection: WebTransportConnection) -> ConnectionId`**: Adds a connection to be managed.
- **`async def cleanup_closed_connections(self) -> int`**: Scans for and removes closed connections.
- **`async def close_all_connections(self) -> None`**: Closes all connections currently being managed.
- **`async def get_all_connections(self) -> list[WebTransportConnection]`**: Returns a list of all managed connections.
- **`async def get_connection(self, *, connection_id: ConnectionId) -> WebTransportConnection | None`**: Retrieves a managed connection.
- **`def get_connection_count(self) -> int`**: Returns the current number of connections.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics about the manager and its connections.
- **`async def remove_connection(self, *, connection_id: ConnectionId) -> WebTransportConnection | None`**: Removes a connection.
- **`async def shutdown(self) -> None`**: Stops background tasks and closes all connections.

## ConnectionPool Class

Manages a pool of reusable connections to reduce latency from connection setup.

**Note on Usage**: `ConnectionPool` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, max_size: int = 10, max_idle_time: float = 300.0, cleanup_interval: float = 60.0) -> None`**: Initializes the connection pool.

### Instance Methods

- **`async def close_all(self) -> None`**: Closes all connections in the pool and shuts down the pool.
- **`async def get_connection(self, *, config: ClientConfig, host: str, port: int, path: str = "/") -> WebTransportConnection`**: Gets an available connection from the pool or creates a new one.
- **`def get_stats(self) -> dict[str, Any]`**: Returns statistics about the pool's state.
- **`async def return_connection(self, *, connection: WebTransportConnection) -> None`**: Returns a healthy connection to the pool for reuse.

## ConnectionLoadBalancer Class

Distributes connection requests across a list of target servers and performs health checks.

**Note on Usage**: `ConnectionLoadBalancer` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, targets: list[tuple[str, int]], *, health_check_interval: float = 30.0, health_check_timeout: float = 5.0) -> None`**: Initializes the load balancer.

### Instance Methods

- **`async def get_connection(self, *, config: ClientConfig, path: str = "/", strategy: str = "round_robin") -> WebTransportConnection`**: Gets a connection to the next available target.
- **`async def get_load_balancer_stats(self) -> dict[str, Any]`**: Returns high-level stats about the load balancer.
- **`async def get_target_stats(self) -> dict[str, Any]`**: Returns health and performance stats for each target.
- **`async def shutdown(self) -> None`**: Shuts down the load balancer, stopping health checks and closing all connections.
- **`async def update_target_weight(self, *, host: str, port: int, weight: float) -> None`**: Updates the weight for a specific target.

## ConnectionInfo Class

A dataclass holding statistics and information about a `WebTransportConnection`.

**Note on Usage**: The constructor for this dataclass requires all parameters to be passed as keyword arguments.

### Attributes

- `connection_id` (`str`): The unique identifier for the connection.
- `state` (`ConnectionState`): The current state of the connection.
- `local_address` (`Address | None`): The local address. `Default: None`.
- `remote_address` (`Address | None`): The remote address. `Default: None`.
- `established_at` (`float | None`): Timestamp when the connection was established. `Default: None`.
- `closed_at` (`float | None`): Timestamp when the connection was closed. `Default: None`.
- `bytes_sent` (`int`): Total bytes sent. `Default: 0`.
- `bytes_received` (`int`): Total bytes received. `Default: 0`.
- `packets_sent` (`int`): Total packets sent. `Default: 0`.
- `packets_received` (`int`): Total packets received. `Default: 0`.
- `error_count` (`int`): Number of errors encountered. `Default: 0`.
- `last_activity` (`float | None`): Timestamp of the last activity. `Default: None`.

### Properties

- `uptime` (`float`): The total uptime of the connection in seconds.

## Utility Functions

These helper functions are available in the `pywebtransport.connection.utils` module.

- **`async def connect_with_retry(*, config: ClientConfig, host: str, port: int, path: str = "/", ...)`**: Establishes a connection with an exponential backoff retry mechanism.
- **`async def create_multiple_connections(*, config: ClientConfig, targets: list[tuple[str, int]], path: str = "/", ...)`**: Creates connections to multiple targets concurrently.
- **`async def ensure_connection(*, connection: WebTransportConnection, config: ClientConfig, host: str, port: int, ...)`**: Ensures a connection is active, reconnecting if necessary.
- **`async def test_multiple_connections(*, targets: list[tuple[str, int]], timeout: float = 10.0) -> dict[str, bool]`**: Tests TCP connectivity to multiple targets concurrently.
- **`async def test_tcp_connection(*, host: str, port: int, timeout: float = 10.0) -> bool`**: Tests if a basic TCP connection can be established.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
