# API Reference: monitor

This document provides a reference for the `pywebtransport.monitor` subpackage, which provides monitoring utilities for component health.

---

## ClientMonitor Class

Monitors client performance and health. It periodically collects statistics from a `WebTransportClient` instance and can generate alerts based on predefined conditions (e.g., low connection success rate, slow connection times). This class implements the asynchronous context manager protocol (`async with`) to start and stop the background monitoring task.

### Constructor

- **`def __init__(self, client: WebTransportClient, *, monitoring_interval: float = 30.0) -> None`**: Initializes the client monitor.
  - `client`: The client instance to monitor. Must be a `WebTransportClient`, not a wrapper like `ReconnectingClient`.
  - `monitoring_interval`: The interval in seconds between metrics collection.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`def clear_history(self) -> None`**: Clears all collected metrics and generated alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts.
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history snapshots.
- **`def get_metrics_summary(self) -> dict[str, Any]`**: Returns a summary containing the latest metrics snapshot, recent alerts, and current status.

## ConnectionMonitor Class

Monitors connection performance and health. It periodically collects statistics from a `WebTransportConnection` instance and generates alerts for unhealthy states or resource exhaustion. This class implements the asynchronous context manager protocol (`async with`).

### Constructor

- **`def __init__(self, connection: WebTransportConnection, *, monitoring_interval: float = 15.0) -> None`**: Initializes the connection monitor.
  - `connection`: The connection instance to monitor.
  - `monitoring_interval`: The interval in seconds between metrics collection.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`def clear_history(self) -> None`**: Clears all collected metrics and generated alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts.
- **`def get_current_metrics(self) -> dict[str, Any] | None`**: Gets the latest collected metrics snapshot, or `None` if none exist yet.
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history snapshots.

## ServerMonitor Class

Monitors server performance and health. It periodically collects statistics from a `WebTransportServer` instance and can generate alerts if the server becomes unhealthy or degraded. This class implements the asynchronous context manager protocol (`async with`).

### Constructor

- **`def __init__(self, server: WebTransportServer, *, monitoring_interval: float = 30.0) -> None`**: Initializes the server monitor.
  - `server`: The server instance to monitor.
  - `monitoring_interval`: The interval in seconds between metrics collection.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`def clear_history(self) -> None`**: Clears all collected metrics and generated alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts.
- **`def get_current_metrics(self) -> dict[str, Any] | None`**: Gets the latest collected metrics snapshot, or `None` if none exist yet.
- **`def get_health_status(self) -> dict[str, Any]`**: Returns the current inferred server health status (e.g., "healthy", "degraded", "unhealthy") based on the latest metrics.
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history snapshots.

## SessionMonitor Class

Monitors session performance and health. It periodically collects statistics from a `WebTransportSession` instance and alerts on unhealthy states or high stream contention. This class implements the asynchronous context manager protocol (`async with`).

### Constructor

- **`def __init__(self, session: WebTransportSession, *, monitoring_interval: float = 15.0) -> None`**: Initializes the session monitor.
  - `session`: The session instance to monitor.
  - `monitoring_interval`: The interval in seconds between metrics collection.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`def clear_history(self) -> None`**: Clears all collected metrics and generated alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts.
- **`def get_current_metrics(self) -> dict[str, Any] | None`**: Gets the latest collected metrics snapshot, or `None` if none exist yet.
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history snapshots.

## See Also

- **[Client API](client.md)**: Learn how to create and manage client connections.
- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Server API](server.md)**: Build and manage WebTransport servers.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
