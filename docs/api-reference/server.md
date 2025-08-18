# API Reference: Server

This document provides a comprehensive reference for the `pywebtransport.server` subpackage, which contains the high-level application framework and core components for building WebTransport servers.

---

## Application Framework

### ServerApp Class

The primary high-level framework for building WebTransport applications. It provides a simple, decorator-based interface for routing, middleware, and lifecycle management. It should be used as an async context manager.

#### Key Methods & Properties

- **`async def serve(self, *, host: str | None = None, port: int | None = None, ...)`**: Starts the server and serves forever within an existing event loop.
- **`run(self, *, host: str | None = None, port: int | None = None, ...)`**: Runs the application in a blocking manner, creating a new event loop. Ideal for simple scripts.
- `server` (`WebTransportServer`): The underlying `WebTransportServer` instance.

#### Decorators

- **`@app.route(path: str)`**: Registers a session handler for an exact URL path.

  ```python
  app = ServerApp()

  @app.route("/echo")
  async def echo_handler(session: WebTransportSession):
      # ... handler logic ...
  ```

- **`@app.pattern_route(pattern: str)`**: Registers a session handler for a regular expression pattern. Path parameters are attached to `session.path_params`.
  ```python
  @app.pattern_route(r"/users/(\d+)")
  async def user_handler(session: WebTransportSession):
      user_id = session.path_params[0]
      # ... handler logic ...
  ```
- **`@app.middleware`**: Registers a function as a middleware.
- **`@app.on_startup`**: Registers a function to run when the application starts up.
- **`@app.on_shutdown`**: Registers a function to run when the application shuts down.

---

## Core Components

These are the underlying classes orchestrated by `ServerApp`.

### WebTransportServer Class

The core server class that manages the QUIC transport, connection lifecycle, and event emission.

#### Constructor

- **`__init__(self, *, config: ServerConfig | None = None)`**: Initializes the server.

#### Instance Methods

- **`async def listen(self, *, host: str | None = None, port: int | None = None) -> None`**: Starts the QUIC server and begins listening for connections.
- **`async def close(self) -> None`**: Gracefully shuts down the server.
- **`async def serve_forever(self) -> None`**: Runs the server's event loop until it's closed.
- **`async def get_server_stats(self) -> dict[str, Any]`**: Returns a dictionary of detailed server statistics.
- **`async def debug_state(self) -> dict[str, Any]`**: Returns a detailed snapshot of the server's state for debugging.
- **`async def diagnose_issues(self) -> list[str]`**: Analyzes server stats and config to identify potential issues.

#### Properties

- `is_serving` (`bool`): `True` if the server is currently listening.
- `local_address` (`tuple[str, int]`): The `(host, port)` tuple the server is bound to.
- `session_manager` (`SessionManager`): The server's session manager instance, which tracks all active sessions.

### RequestRouter Class

Manages the mapping of session paths to handlers.

#### Instance Methods

- **`add_route(self, path: str, handler: SessionHandler) -> None`**: Adds a route for an exact path.
- **`add_pattern_route(self, pattern: str, handler: SessionHandler) -> None`**: Adds a route for a regex pattern.
- **`route_request(self, session: WebTransportSession) -> SessionHandler | None`**: Finds the appropriate handler for a given session.

### MiddlewareManager Class

Manages the execution chain of middleware for incoming sessions.

#### Instance Methods

- **`add_middleware(self, middleware: Callable[...]) -> None`**: Adds a middleware to the chain.
- **`async def process_request(self, session: WebTransportSession) -> bool`**: Processes a session through the middleware chain.

---

## Advanced Components

### ServerCluster Class

Manages the lifecycle of multiple `WebTransportServer` instances for scaling across multiple CPU cores.

**Note on Usage**: `ServerCluster` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, configs: list[ServerConfig])`**: Initializes the server cluster.

#### Instance Methods

- **`async def start_all(self) -> None`**: Starts all configured servers.
- **`async def stop_all(self) -> None`**: Stops all running servers.
- **`async def get_cluster_stats(self) -> dict[str, Any]`**: Returns aggregated statistics for the entire cluster.
- **`async def add_server(self, config: ServerConfig) -> WebTransportServer | None`**: Adds and starts a new server in the running cluster.
- **`async def remove_server(self, *, host: str, port: int) -> bool`**: Removes and stops a server from the cluster.

### ServerMonitor Class

Monitors the performance of a `WebTransportServer` instance, collecting metrics and checking health.

**Note on Usage**: `ServerMonitor` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, server: WebTransportServer, *, monitoring_interval: float = 30.0)`**: Initializes the server monitor.

#### Instance Methods

- **`get_health_status(self) -> dict[str, Any]`**: Returns the current server health.
- **`get_alerts(self, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts.
- **`get_metrics_history(self, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history.

---

## Built-in Middleware Factories

These functions create pre-configured middleware handlers.

- **`create_cors_middleware(*, allowed_origins: list[str]) -> Callable[...]`**: Creates middleware to validate the `Origin` header of incoming sessions.
- **`create_auth_middleware(auth_handler: Callable[[Headers], Awaitable[bool]]) -> Callable[...]`**: Creates authentication middleware using a custom async handler.
- **`create_rate_limit_middleware(*, max_requests: int = 100, window_seconds: int = 60, ...)`**: Creates a stateful `RateLimiter` instance that rate-limits sessions based on their IP address.
- **`create_logging_middleware() -> Callable[...]`**: Creates a simple middleware that logs information about each incoming session request.

---

## Utility Functions & Handlers

These helpers are available in the `pywebtransport.server.utils` module.

### Factory Functions

- **`create_development_server(*, host: str = "localhost", port: int = 4433, ...)`**: Creates a `ServerApp` instance configured for local development.
- **`create_echo_server_app(*, config: ServerConfig | None = None) -> ServerApp`**: Creates a `ServerApp` pre-configured with a single route that echoes all data.
- **`create_simple_app() -> ServerApp`**: Creates a `ServerApp` with pre-configured `/health` and `/echo` routes.

### Built-in Handlers

- **`async def echo_handler(session: WebTransportSession) -> None`**: A session handler that echoes all received datagrams and stream data.
- **`async def health_check_handler(session: WebTransportSession) -> None`**: A session handler that sends a health status datagram and closes the session.

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
