# API Reference: Connection

This document provides a comprehensive reference for the `pywebtransport.connection` subpackage, which contains high-level abstractions for creating and managing WebTransport connections.

---

## `WebTransportConnection` Class

The core class representing a single WebTransport connection. It manages the connection lifecycle, protocol handling, and event emission.

### Class Method Factories

- **`create_client(*, config: ClientConfig, host: str, port: int, path: str = "/") -> WebTransportConnection`**:
  The recommended way to create and establish a client connection in one step.

- **`create_server(*, config: ServerConfig, transport: Any, protocol: Any) -> WebTransportConnection`**:
  Creates a server-side connection instance from an accepted transport.

### Key Instance Methods

- **`connect(self, host: str, port: int, path: str = "/") -> None`**:
  Establishes a client connection. Typically, `create_client` is preferred.

- **`accept(self, transport: asyncio.DatagramTransport, protocol: QuicConnectionProtocol) -> None`**:
  Accepts an incoming server connection.

- **`close(self, *, code: int = 0, reason: str = "") -> None`**:
  Gracefully closes the connection.

- **`wait_closed(self) -> None`**:
  Waits until the connection is fully closed.

- **`wait_ready(self, *, timeout: float = 30.0) -> None`**:
  Waits for the connection to be established and ready.

- **`wait_for_ready_session(self, *, timeout: float = 30.0) -> SessionId`**:
  Waits for a session to become ready on this connection.

### Properties

- **`state` (ConnectionState)**: The current state of the connection (e.g., `IDLE`, `CONNECTING`, `CONNECTED`).
- **`is_connected` (bool)**: `True` if the connection is established.
- **`is_closed` (bool)**: `True` if the connection is fully closed.
- **`connection_id` (str)**: The unique ID of the connection.
- **`local_address` (Optional[Address])**: The local `(host, port)` tuple.
- **`remote_address` (Optional[Address])**: The remote `(host, port)` tuple.
- **`protocol_handler` (Optional[WebTransportProtocolHandler])**: The underlying protocol handler.
- **`info` (ConnectionInfo)**: A data object with detailed connection statistics.

---

## `ConnectionInfo` Class

A dataclass holding comprehensive statistics and information about a `WebTransportConnection`.

### Attributes

- `connection_id` (str)
- `state` (ConnectionState)
- `local_address` (Optional[Address])
- `remote_address` (Optional[Address])
- `established_at` (Optional[float])
- `closed_at` (Optional[float])
- `bytes_sent` (int)
- `bytes_received` (int)
- `packets_sent` (int)
- `packets_received` (int)
- `error_count` (int)
- `last_activity` (Optional[float])
- `uptime` (property) -> float: The total uptime of the connection in seconds.

---

## `ConnectionManager` Class

Manages the lifecycle of multiple `WebTransportConnection` objects. It is an async context manager.

- **`__init__(self, *, max_connections: int = 1000, cleanup_interval: float = 60.0)`**
- **`add_connection(self, connection: WebTransportConnection) -> ConnectionId`**: Adds a connection to be managed.
- **`remove_connection(self, connection_id: ConnectionId) -> Optional[WebTransportConnection]`**: Removes a connection from the manager.
- **`get_connection(self, connection_id: ConnectionId) -> Optional[WebTransportConnection]`**: Retrieves a managed connection.
- **`get_all_connections(self) -> List[WebTransportConnection]`**: Returns a list of all managed connections.
- **`get_connection_count(self) -> int`**: Returns the current number of connections.
- **`get_stats(self) -> Dict[str, Any]`**: Returns detailed statistics about the manager and its connections.
- **`cleanup_closed_connections(self) -> int`**: Scans for and removes closed connections, returning the count of removed connections.
- **`close_all_connections(self) -> None`**: Closes all connections currently being managed.
- **`shutdown(self) -> None`**: Stops the background cleanup task and closes all connections.

---

## `ConnectionPool` Class

Manages a pool of reusable connections to reduce latency from connection setup. It is an async context manager.

- **`__init__(self, *, max_size: int = 10, max_idle_time: float = 300.0, cleanup_interval: float = 60.0)`**
- **`get_connection(self, *, config: ClientConfig, host: str, port: int, path: str = "/") -> WebTransportConnection`**: Gets an available connection from the pool or creates a new one.
- **`return_connection(self, connection: WebTransportConnection) -> None`**: Returns a healthy connection to the pool for reuse.
- **`close_all(self) -> None`**: Closes all connections in the pool and shuts down the pool.
- **`get_stats(self) -> Dict[str, Any]`**: Returns statistics about the pool's state.

---

## `ConnectionLoadBalancer` Class

Distributes connection requests across a list of target servers and performs health checks. It is an async context manager.

- **`__init__(self, *, targets: List[Tuple[str, int]], health_check_interval: float = 30.0, ...)`**
- **`get_connection(self, config: ClientConfig, *, path: str = "/", strategy: str = "round_robin") -> WebTransportConnection`**: Gets a connection to the next available target based on the specified `strategy` ("round_robin", "weighted", "least_latency").
- **`get_target_stats(self) -> Dict[str, Any]`**: Returns health and performance stats for each target.
- **`get_load_balancer_stats(self) -> Dict[str, Any]`**: Returns high-level stats about the load balancer.
- **`shutdown(self) -> None`**: Shuts down the load balancer, stopping health checks and closing all connections.

---

## Connection Utility Functions

These helper functions are available in the `pywebtransport.connection.utils` module.

- **`connect_with_retry(*, config: ClientConfig, host: str, port: int, ...)`**: Establishes a connection with an exponential backoff retry mechanism.
- **`ensure_connection(connection: WebTransportConnection, config: ClientConfig, ...)`**: Ensures a connection is active, reconnecting if necessary.
- **`create_multiple_connections(*, config: ClientConfig, targets: List[Tuple[str, int]], ...)`**: Creates connections to multiple targets concurrently, with a concurrency limit.
- **`test_multiple_connections(*, targets: List[Tuple[str, int]], timeout: float = 10.0)`**: Tests TCP connectivity to multiple targets concurrently.
- **`test_tcp_connection(*, host: str, port: int, timeout: float = 10.0) -> bool`**: Tests if a basic TCP connection can be established to a host and port.

---

## See Also

- [**Protocol API**](protocol.md): The low-level protocol handler used by `WebTransportConnection`.
- [**Session API**](session.md): High-level abstractions for managing sessions over connections.
- [**Configuration API**](config.md): Details on the `ClientConfig` and `ServerConfig` classes.
- [**Exceptions API**](exceptions.md): Exceptions like `ConnectionError` that may be raised.
