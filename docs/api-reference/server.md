# API Reference: Server

This document provides a comprehensive reference for the `pywebtransport.server` subpackage, which contains the high-level application framework and core components for building WebTransport servers.

---

## `ServerApp` Class

The primary high-level framework for building WebTransport applications. It provides a simple, decorator-based interface for routing, middleware, and lifecycle management.

### Decorators

- **`@app.route(path: str)`**:
  Registers a session handler for an exact URL path.

  ```python
  app = ServerApp()

  @app.route("/echo")
  async def echo_handler(session: WebTransportSession):
      # ... handler logic ...
  ```

- **`@app.pattern_route(pattern: str)`**:
  Registers a session handler for a regular expression pattern. Path parameters are attached to `session.path_params`.

  ```python
  @app.pattern_route(r"/users/(\d+)")
  async def user_handler(session: WebTransportSession):
      user_id = session.path_params[0]
      # ... handler logic ...
  ```

- **`@app.middleware`**:
  Registers a function as a middleware. The function should accept a `WebTransportSession` and return `True` to continue or `False` to reject the session.

- **`@app.on_startup`**:
  Registers a function to run when the application starts up.

- **`@app.on_shutdown`**:
  Registers a function to run when the application shuts down.

### Key Methods

- **`run(self, *, host: Optional[str] = None, port: Optional[int] = None, ...)`**:
  Runs the application in a blocking manner, creating a new event loop. Ideal for simple scripts.

- **`serve(self, *, host: Optional[str] = None, port: Optional[int] = None, ...)`**:
  Starts the server and serves forever within an existing event loop.

### Properties

- **`server` (WebTransportServer)**: The underlying `WebTransportServer` instance.

---

## Core Components

These are the underlying classes orchestrated by `ServerApp`.

### `WebTransportServer` Class

The core server class that manages the QUIC transport, connection lifecycle, and event emission.

- **`__init__(self, *, config: Optional[ServerConfig] = None)`**
- **`listen(self, *, host: Optional[str] = None, port: Optional[int] = None) -> None`**: Starts the QUIC server and begins listening for connections.
- **`close(self) -> None`**: Gracefully shuts down the server.
- **`serve_forever(self) -> None`**: Runs the server's event loop until it's closed.
- **`is_serving` (property)**: `True` if the server is currently listening.
- **`local_address` (property)**: The `(host, port)` tuple the server is bound to.
- **`get_server_stats(self) -> Dict[str, Any]`**: Returns a dictionary of detailed server statistics.

### `RequestRouter` Class

Manages the mapping of session paths to handlers.

- **`add_route(self, path: str, handler: SessionHandler) -> None`**
- **`add_pattern_route(self, pattern: str, handler: SessionHandler) -> None`**
- **`route_request(self, session: WebTransportSession) -> Optional[SessionHandler]`**: Finds the appropriate handler for a given session.

### `MiddlewareManager` Class

Manages the execution chain of middleware for incoming sessions.

- **`add_middleware(self, middleware: Callable[...]) -> None`**
- **`process_request(self, session: WebTransportSession) -> bool`**: Processes a session through the middleware chain.

---

## Advanced Components

### `ServerCluster` Class

Manages the lifecycle of multiple `WebTransportServer` instances for scaling across multiple CPU cores. It is an async context manager.

- **`__init__(self, configs: List[ServerConfig])`**
- **`start_all(self) -> None`**: Starts all configured servers.
- **`stop_all(self) -> None`**: Stops all running servers.
- **`get_cluster_stats(self) -> Dict[str, Any]`**: Returns aggregated statistics for the entire cluster.

### `ServerMonitor` Class

An async context manager that periodically collects metrics and checks the health of a `WebTransportServer` instance.

- **`__init__(self, server: WebTransportServer, *, monitoring_interval: float = 30.0)`**
- **`get_health_status(self) -> Dict[str, Any]`**: Returns the current server health (`healthy`, `degraded`, `unhealthy`).
- **`get_alerts(self, limit: int = 25) -> List[Dict[str, Any]]`**: Returns a list of recently generated health alerts.

---

## Built-in Middleware Factories

These functions create pre-configured middleware handlers.

- **`create_cors_middleware(*, allowed_origins: List[str]) -> Callable[...]`**:
  Creates middleware to validate the `Origin` header of incoming sessions.

- **`create_auth_middleware(auth_handler: Callable[[Headers], Awaitable[bool]]) -> Callable[...]`**:
  Creates authentication middleware using a custom async handler to validate session headers.

- **`create_rate_limit_middleware(*, max_requests: int = 100, window_seconds: int = 60, ...)`**:
  Creates a stateful middleware that rate-limits incoming sessions based on their IP address.

- **`create_logging_middleware() -> Callable[...]`**:
  Creates a simple middleware that logs information about each incoming session request.

---

## Utility Functions & Handlers

These helpers are available in the `pywebtransport.server.utils` module.

### Factory Functions

- **`create_development_server(*, host: str = "localhost", port: int = 4433, ...)`**:
  Creates a `ServerApp` instance configured for local development, automatically generating self-signed certificates.

- **`create_echo_server_app(*, config: Optional[ServerConfig] = None) -> ServerApp`**:
  Creates a `ServerApp` pre-configured with a single route that echoes all stream and datagram data.

- **`create_simple_app() -> ServerApp`**:
  Creates a `ServerApp` with pre-configured `/health` and `/echo` routes.

### Built-in Handlers

- **`echo_handler(session: WebTransportSession) -> None`**:
  A session handler that echoes all received datagrams and stream data.

- **`health_check_handler(session: WebTransportSession) -> None`**:
  A session handler that sends a `{"status": "healthy"}` datagram and immediately closes the session.

---

## See Also

- [**Session API**](session.md): The `WebTransportSession` object passed to handlers and middleware.
- [**Configuration API**](config.md): Details on the `ServerConfig` class.
- [**Connection API**](connection.md): The underlying connection objects managed by the server.
- [**Exceptions API**](exceptions.md): Exceptions like `ServerError` that may be raised.
