# API Reference: connection

This document provides a reference for the `pywebtransport.connection` subpackage, which provides abstractions for the underlying QUIC connection.

---

## WebTransportConnection Class

The core class representing a single WebTransport connection over QUIC. It manages the connection lifecycle, protocol handling, and session initiation.

**Note on Usage**: Typically not instantiated directly. Use `WebTransportConnection.create_client()` for client-side connections or rely on server-side frameworks (`ServerApp`, `WebTransportServer`) which create instances for incoming connections. Must be used as an asynchronous context manager (`async with connection: ...`) or explicitly closed.

### Class Methods

- **`async def create_client(*, config: ClientConfig, host: str, port: int, path: str = "/", proxy_addr: Address | None = None) -> Self`**: Class method to create, establish, and perform the initial WebTransport handshake for a client connection. Returns the connected `WebTransportConnection` instance.
- **`async def create_server(cls, *, config: ServerConfig, transport: Any, protocol: Any) -> Self`**: Class method to create a `WebTransportConnection` instance for an accepted server-side connection.

### Properties

- `config` (`ClientConfig | ServerConfig`): The configuration object associated with this connection.
- `connection_id` (`str`): A unique identifier generated for this connection instance.
- `diagnostics` (`ConnectionDiagnostics`): Get a snapshot of the connection's diagnostics, including stats, RTT, CWND, etc.
- `is_closed` (`bool`): `True` if the connection is fully closed.
- `is_closing` (`bool`): `True` if the connection is in the process of closing but resources may still be cleaning up.
- `is_connected` (`bool`): `True` if the connection is established and the WebTransport handshake is complete (state is `CONNECTED`).
- `local_address` (`Address | None`): The local `(host, port)` tuple of the underlying transport, if available.
- `protocol_handler` (`WebTransportProtocolHandler | None`): The low-level protocol handler instance managing sessions and streams over this connection.
- `remote_address` (`Address | None`): The remote `(host, port)` tuple of the underlying transport, if available.
- `state` (`ConnectionState`): The current state of the connection (e.g., `IDLE`, `CONNECTING`, `CONNECTED`, `CLOSING`, `CLOSED`).

### Instance Methods

- **`async def accept(self, *, transport: asyncio.DatagramTransport, protocol: QuicConnectionProtocol) -> None`**: Accepts an incoming server connection, associating it with the transport and protocol provided by `aioquic`. Initializes the protocol handler and starts background tasks.
- **`async def close(self, *, code: int = 0, reason: str = "") -> None`**: Gracefully closes the WebTransport connection, including the underlying QUIC connection and protocol handler.
- **`def get_all_sessions(self) -> list[WebTransportSessionInfo]`**: Returns a list of `WebTransportSessionInfo` objects for all sessions currently tracked by the protocol handler on this connection.
- **`def get_ready_session_id(self) -> SessionId | None`**: Returns the `SessionId` of the first session found in the `CONNECTED` state, or `None` if no session is ready.
- **`def get_session_info(self, *, session_id: SessionId) -> WebTransportSessionInfo | None`**: Retrieves detailed state information (`WebTransportSessionInfo`) for a specific session ID on this connection.
- **`async def monitor_health(self, *, check_interval: float = 30.0, rtt_timeout: float = 5.0) -> None`**: A long-running task that periodically checks connection health by measuring RTT using QUIC pings. Will log warnings on timeouts.
- **`def record_activity(self) -> None`**: Manually records network activity on the connection, primarily used to reset the server-side idle timer.
- **`async def wait_closed(self) -> None`**: Waits until the connection has fully transitioned to the `CLOSED` state.
- **`async def wait_ready(self, *, timeout: float = 30.0) -> None`**: Waits for the connection itself to reach the `CONNECTED` state. Raises `asyncio.TimeoutError` on timeout.
- **`async def wait_for_ready_session(self, *, timeout: float = 30.0) -> SessionId`**: Waits for a `SESSION_READY` event from the protocol handler, indicating a session is established. Returns the `SessionId`. Raises `ConnectionError` or `ClientError` on failure or timeout.

## ConnectionLoadBalancer Class

Distributes outgoing client connection attempts across a list of target server addresses and performs periodic health checks on failed targets.

**Note on Usage**: `ConnectionLoadBalancer` must be used as an asynchronous context manager (`async with balancer: ...`).

### Constructor

- **`def __init__(self, *, targets: list[tuple[str, int]], connection_factory: Callable[..., Awaitable[WebTransportConnection]], health_checker: Callable[..., Awaitable[bool]], health_check_interval: float = 30.0, health_check_timeout: float = 5.0) -> None`**: Initializes the load balancer.
  - `targets` (`list[tuple[str, int]]`): A list of `(host, port)` tuples representing the target servers.
  - `connection_factory` (`Callable[..., Awaitable[WebTransportConnection]]`): An awaitable function (like `WebTransportConnection.create_client`) used to create new connections. It will receive `config`, `host`, `port`, and `path`.
  - `health_checker` (`Callable[..., Awaitable[bool]]`): An awaitable function used to check if a failed target is back online. It receives `host`, `port`, and `timeout`.
  - `health_check_interval` (`float`): Interval in seconds between health checks for failed targets. `Default: 30.0`.
  - `health_check_timeout` (`float`): Timeout in seconds for each individual health check attempt. `Default: 5.0`.

### Instance Methods

- **`async def close_all_connections(self) -> None`**: Closes all currently active connections managed by the load balancer.
- **`async def get_connection(self, *, config: ClientConfig, path: str = "/", strategy: str = "round_robin") -> WebTransportConnection`**: Retrieves or creates a connection to an available target based on the chosen strategy (`round_robin`, `weighted`, `least_latency`). Handles concurrent connection attempts to the same target and retries if the initially chosen target fails. Raises `ConnectionError` if no targets are available.
- **`async def get_load_balancer_stats(self) -> dict[str, Any]`**: Returns high-level statistics about the balancer (total targets, failed targets, active connections, available targets).
- **`async def get_target_stats(self) -> dict[str, Any]`**: Returns detailed statistics for each configured target (host, port, weight, last latency, failed status, connected status).
- **`async def shutdown(self) -> None`**: Stops the health check task and closes all managed connections.
- **`async def update_target_weight(self, *, host: str, port: int, weight: float) -> None`**: Updates the weight used by the `weighted` strategy for a specific target.

## ConnectionDiagnostics Class

A structured, immutable snapshot of a `WebTransportConnection`'s health, including statistics and QUIC transport metrics.

### Attributes

- `stats` (`ConnectionInfo`): The comprehensive statistics and state object for the connection.
- `rtt` (`float`): The latest smoothed Round-Trip Time (RTT) in seconds, as reported by QUIC.
- `cwnd` (`int`): The current congestion window size in bytes, as reported by QUIC's congestion controller.
- `packets_in_flight` (`int`): The number of QUIC packets currently considered in flight (sent but not acknowledged or lost).
- `packet_loss_rate` (`float`): The estimated packet loss rate (lost packets / total sent packets).

### Properties

- `issues` (`list[str]`): A list of potential issues derived from the diagnostics (e.g., "Connection not established", "High latency (RTT)", "Connection appears stale").

## ConnectionInfo Class

A dataclass holding comprehensive information and statistics about a `WebTransportConnection`.

**Note on Usage**: The constructor for this dataclass requires all parameters to be passed as keyword arguments.

### Attributes

- `connection_id` (`str`): The unique identifier for the connection.
- `state` (`ConnectionState`): The current state of the connection (e.g., `CONNECTING`, `CONNECTED`, `CLOSED`).
- `local_address` (`Address | None`): The local `(host, port)` tuple. `Default: None`.
- `remote_address` (`Address | None`): The remote `(host, port)` tuple. `Default: None`.
- `established_at` (`float | None`): Timestamp when the connection reached the `CONNECTED` state. `Default: None`.
- `closed_at` (`float | None`): Timestamp when the connection transitioned to the `CLOSED` state. `Default: None`.
- `bytes_sent` (`int`): Total bytes sent at the WebTransport protocol layer. `Default: 0`.
- `bytes_received` (`int`): Total bytes received at the WebTransport protocol layer. `Default: 0`.
- `packets_sent` (`int`): Total QUIC packets sent. `Default: 0`.
- `packets_received` (`int`): Total QUIC packets received. `Default: 0`.
- `error_count` (`int`): Count of significant errors logged or handled by the connection/protocol. `Default: 0`.
- `last_activity` (`float | None`): Timestamp of the last recorded network activity (used for idle checks). `Default: None`.

### Properties

- `uptime` (`float`): The duration in seconds the connection has been established (from `established_at` to `closed_at` or current time).

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Protocol API](protocol.md)**: Understand the low-level protocol handling.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
