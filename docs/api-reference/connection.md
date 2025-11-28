# API Reference: connection

This document provides a reference for the `pywebtransport.connection` subpackage, which provides abstractions for the underlying QUIC connection.

---

## WebTransportConnection Class

A high-level handle for a WebTransport connection over QUIC. It manages the connection lifecycle, acts as a gateway to the protocol engine, and serves as a factory for sessions. This class implements the asynchronous context manager protocol (`async with`) to ensure resources are properly closed.

### Constructor

- **`def __init__(self, *, config: ClientConfig | ServerConfig, protocol: AdapterProtocol, transport: asyncio.DatagramTransport, is_client: bool) -> None`**: Initializes the WebTransport connection handle and the internal protocol engine.

### Properties

- `config` (`ClientConfig | ServerConfig`): The configuration object associated with this connection.
- `connection_id` (`str`): A unique identifier (UUID) generated for this connection instance.
- `events` (`EventEmitter`): The event emitter for connection-level events.
- `is_client` (`bool`): `True` if this is a client-side connection.
- `is_closed` (`bool`): `True` if the connection state is `CLOSED`.
- `is_closing` (`bool`): `True` if the connection state is `CLOSING`.
- `is_connected` (`bool`): `True` if the connection state is `CONNECTED`.
- `local_address` (`Address | None`): The local `(host, port)` tuple of the underlying transport, if available.
- `remote_address` (`Address | None`): The remote `(host, port)` tuple of the underlying transport, if available.
- `state` (`ConnectionState`): The current state of the connection (e.g., `IDLE`, `CONNECTING`, `CONNECTED`, `CLOSED`).

### Instance Methods

- **`async def close(self, *, error_code: int = 0, reason: str = "Closed by application") -> None`**: Immediately closes the WebTransport connection, stops the engine, and cleans up resources.
- **`async def create_session(self, *, path: str, headers: Headers | None = None) -> WebTransportSession`**: **(Client-only)** Initiates a new WebTransport session. Returns a `WebTransportSession` handle upon success.
- **`async def diagnostics(self) -> ConnectionDiagnostics`**: Asynchronously retrieves a snapshot of the connection's diagnostic information from the engine.
- **`def get_all_sessions(self) -> list[WebTransportSession]`**: Returns a list of all active `WebTransportSession` handles currently managed by this connection.
- **`async def graceful_shutdown(self) -> None`**: Initiates a graceful shutdown (sends GOAWAY), waits for active sessions to drain (with timeout), and then closes the connection.
- **`async def initialize(self) -> None`**: Starts the internal protocol engine loop. Typically called automatically by the adapter.

## ConnectionDiagnostics Class

A dataclass representing a snapshot of connection diagnostics.

### Attributes

- `connection_id` (`str`): The unique identifier for the connection.
- `state` (`ConnectionState`): The state of the connection at the time of the snapshot.
- `is_client` (`bool`): Whether the connection is client-side.
- `connected_at` (`float | None`): Timestamp when the connection was established.
- `closed_at` (`float | None`): Timestamp when the connection was closed.
- `max_datagram_size` (`int`): The maximum datagram size allowed.
- `remote_max_datagram_frame_size` (`int`): The maximum datagram frame size advertised by the peer.
- `session_count` (`int`): The total number of sessions tracked by the engine.
- `stream_count` (`int`): The total number of streams tracked by the engine.
- `active_session_handles` (`int`): The number of active `WebTransportSession` proxy objects.
- `active_stream_handles` (`int`): The number of active stream proxy objects.

## ConnectionLoadBalancer Class

Distributes outgoing WebTransport connections across multiple targets using configurable strategies. This class implements the asynchronous context manager protocol (`async with`) to securely manage background health checks.

### Constructor

- **`def __init__(self, *, targets: list[tuple[str, int]], connection_factory: Callable[..., Awaitable[WebTransportConnection]], health_checker: Callable[..., Awaitable[bool]], health_check_interval: float = 30.0, health_check_timeout: float = 5.0) -> None`**: Initializes the load balancer.
  - `targets`: List of `(host, port)` tuples.
  - `connection_factory`: Async callable to create connections.
  - `health_checker`: Async callable to check target availability.

### Instance Methods

- **`async def close_all_connections(self) -> None`**: Closes all currently managed active connections.
- **`async def get_connection(self, *, config: ClientConfig, path: str = "/", strategy: str = "round_robin") -> WebTransportConnection`**: Retrieves an existing or creates a new connection to a target selected by the strategy (`round_robin`, `weighted`, `least_latency`).
- **`async def get_load_balancer_stats(self) -> dict[str, Any]`**: Returns high-level statistics (targets, failures, active connections).
- **`async def get_target_stats(self) -> dict[str, Any]`**: Returns detailed statistics for each target.
- **`async def shutdown(self) -> None`**: Stops health checks and closes all connections.
- **`async def update_target_weight(self, *, host: str, port: int, weight: float) -> None`**: Updates the weight for a target (used by `weighted` strategy).

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.
