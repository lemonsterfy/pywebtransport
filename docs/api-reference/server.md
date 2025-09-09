# API Reference: server

This document provides a reference for the `pywebtransport.server` subpackage, which contains the high-level application framework and core components for building WebTransport servers.

---

## ServerApp Class

The primary high-level framework for building WebTransport applications.

**Note on Usage**: `ServerApp` must be used as an asynchronous context manager (`async with ...`).

### Properties

- `server` (`WebTransportServer`): The underlying `WebTransportServer` instance.

### Instance Methods

- **`def add_middleware(self, *, middleware: MiddlewareProtocol) -> None`**: Adds a middleware to the processing chain.
- **`def middleware(self, middleware_func: MiddlewareProtocol) -> MiddlewareProtocol`**: Decorator to register a middleware function.
- **`def on_shutdown(self, handler: F) -> F`**: Decorator to register a handler to run on application shutdown.
- **`def on_startup(self, handler: F) -> F`**: Decorator to register a handler to run on application startup.
- **`def pattern_route(self, *, pattern: str) -> Callable[[SessionHandler], SessionHandler]`**: Decorator to register a session handler for a URL pattern.
- **`def route(self, *, path: str) -> Callable[[SessionHandler], SessionHandler]`**: Decorator to register a session handler for a specific path.
- **`def run(self, \*, host: str | None = None, port: int | None = None, **kwargs: Any) -> None`\*\*: Runs the application in a blocking manner, creating a new event loop.
- **`async def serve(self, \*, host: str | None = None, port: int | None = None, **kwargs: Any) -> None`\*\*: Starts the server and serves forever within an existing event loop.
- **`async def shutdown(self) -> None`**: Runs all registered shutdown handlers.
- **`async def startup(self) -> None`**: Runs all registered startup handlers.

## WebTransportServer Class

The core server class that manages the QUIC transport and connection lifecycle.

### Constructor

- **`def __init__(self, *, config: ServerConfig | None = None)`**: Initializes the server.

### Properties

- `is_serving` (`bool`): `True` if the server is currently listening.
- `config` (`ServerConfig`): The server's configuration object.
- `local_address` (`Address | None`): The `(host, port)` tuple the server is bound to.
- `session_manager` (`SessionManager`): The server's session manager instance.

### Instance Methods

- **`async def close(self) -> None`**: Gracefully shuts down the server.
- **`async def debug_state(self) -> dict[str, Any]`**: Returns a detailed snapshot of the server's state for debugging.
- **`async def diagnose_issues(self) -> list[str]`**: Analyzes server stats and config to identify potential issues.
- **`async def get_server_stats(self) -> dict[str, Any]`**: Returns a dictionary of detailed server statistics.
- **`async def listen(self, *, host: str | None = None, port: int | None = None) -> None`**: Starts the QUIC server and begins listening for connections.
- **`async def serve_forever(self) -> None`**: Runs the server's event loop until it's closed.

## RequestRouter Class

Manages the mapping of session paths to handlers.

### Instance Methods

- **`def add_pattern_route(self, *, pattern: str, handler: SessionHandler) -> None`**: Adds a route for a regular expression pattern.
- **`def add_route(self, *, path: str, handler: SessionHandler) -> None`**: Adds a route for an exact path match.
- **`def remove_route(self, *, path: str) -> None`**: Removes a route for an exact path match.
- **`def route_request(self, *, session: WebTransportSession) -> SessionHandler | None`**: Finds the appropriate handler for a given session.
- **`def set_default_handler(self, *, handler: SessionHandler) -> None`**: Sets a default handler for routes that are not matched.
- **`def get_all_routes(self) -> dict[str, SessionHandler]`**: Gets a copy of all registered exact-match routes.
- **`def get_route_handler(self, *, path: str) -> SessionHandler | None`**: Gets the handler for a specific path (exact match only).
- **`def get_route_stats(self) -> dict[str, Any]`**: Gets statistics about the configured routes.

## MiddlewareManager Class

Manages the execution chain of middleware for incoming sessions.

### Instance Methods

- **`def add_middleware(self, *, middleware: MiddlewareProtocol) -> None`**: Adds a middleware to the chain.
- **`def get_middleware_count(self) -> int`**: Gets the number of registered middleware.
- **`async def process_request(self, *, session: WebTransportSession) -> bool`**: Processes a session through the middleware chain.
- **`def remove_middleware(self, *, middleware: MiddlewareProtocol) -> None`**: Removes a middleware from the chain.

## ServerCluster Class

Manages the lifecycle of multiple `WebTransportServer` instances.

**Note on Usage**: `ServerCluster` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, configs: list[ServerConfig])`**: Initializes the server cluster.

### Properties

- `is_running` (`bool`): `True` if the cluster is currently running.

### Instance Methods

- **`async def start_all(self) -> None`**: Starts all configured servers.
- **`async def stop_all(self) -> None`**: Stops all running servers.
- **`async def get_cluster_stats(self) -> dict[str, Any]`**: Returns aggregated statistics for the entire cluster.
- **`async def add_server(self, *, config: ServerConfig) -> WebTransportServer | None`**: Adds and starts a new server in the running cluster.
- **`async def remove_server(self, *, host: str, port: int) -> bool`**: Removes and stops a server from the cluster.
- **`async def get_server_count(self) -> int`**: Gets the number of running servers in the cluster.
- **`async def get_servers(self) -> list[WebTransportServer]`**: Gets a thread-safe copy of all active servers in the cluster.

## ServerMonitor Class

Monitors the performance of a `WebTransportServer` instance.

**Note on Usage**: `ServerMonitor` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, server: WebTransportServer, *, monitoring_interval: float = 30.0)`**: Initializes the server monitor.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`def clear_history(self) -> None`**: Clears all collected metrics and alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts.
- **`def get_current_metrics(self) -> dict[str, Any] | None`**: Gets the latest collected metrics.
- **`def get_health_status(self) -> dict[str, Any]`**: Returns the current server health.
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history.

## Built-in Middleware

- **`def create_auth_middleware(*, auth_handler: AuthHandlerProtocol) -> MiddlewareProtocol`**: Creates authentication middleware using a custom async handler.
- **`def create_cors_middleware(*, allowed_origins: list[str]) -> MiddlewareProtocol`**: Creates middleware to validate the `Origin` header of incoming sessions.
- **`def create_logging_middleware() -> MiddlewareProtocol`**: Creates a simple middleware that logs information about each incoming session request.
- **`def create_rate_limit_middleware(*, max_requests: int = 100, window_seconds: int = 60, cleanup_interval: int = 300) -> RateLimiter`**: Creates a stateful `RateLimiter` instance that rate-limits sessions.

## Utility Functions & Handlers

- **`def create_development_server(*, host: str = "localhost", port: int = 4433, generate_certs: bool = True) -> ServerApp`**: Creates a `ServerApp` instance configured for local development.
- **`def create_echo_server_app(*, config: ServerConfig | None = None) -> ServerApp`**: Creates a `ServerApp` pre-configured with a single route that echoes all data.
- **`def create_simple_app() -> ServerApp`**: Creates a `ServerApp` with pre-configured `/health` and `/echo` routes.
- **`async def echo_handler(session: WebTransportSession) -> None`**: A session handler that echoes all received datagrams and stream data.
- **`async def health_check_handler(session: WebTransportSession) -> None`**: A session handler that sends a health status datagram and closes the session.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
