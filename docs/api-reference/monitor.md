# API Reference: monitor

This document provides a reference for the `pywebtransport.monitor` subpackage, which provides monitoring utilities for component health.

---

## ClientMonitor Class

Monitors client performance and health. It periodically collects statistics from a `WebTransportClient` instance and can generate alerts based on predefined conditions (e.g., low connection success rate, slow connection times).

**Note on Usage**: `ClientMonitor` must be used as an asynchronous context manager (`async with monitor: ...`) to start and stop the background monitoring task. It only supports monitoring `WebTransportClient` instances, not derivatives like `ReconnectingClient`.

### Constructor

- **`def __init__(self, client: WebTransportClient, *, monitoring_interval: float = 30.0) -> None`**: Initializes the client monitor.
  - `client` (`WebTransportClient`): The client instance to monitor.
  - `monitoring_interval` (`float`): The interval in seconds between metrics collection attempts. `Default: 30.0`.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context and starts the background monitoring loop.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context and stops the background monitoring loop.
- **`def clear_history(self) -> None`**: Clears all collected metrics and generated alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts (up to `limit`).
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history snapshots (up to `limit`).
- **`def get_metrics_summary(self) -> dict[str, Any]`**: Returns a dictionary containing the latest metrics snapshot, recent alerts, and the current monitoring status.

## DatagramMonitor Class

Monitors datagram transport performance and health. It periodically collects statistics from a `WebTransportDatagramTransport` instance and can generate alerts based on thresholds for queue size, send success rate, and increasing send times.

**Note on Usage**: `DatagramMonitor` must be used as an asynchronous context manager (`async with monitor: ...`).

### Constructor

- **`def __init__(self, datagram_transport: WebTransportDatagramTransport, *, monitoring_interval: float = 5.0, samples_maxlen: int = 100, alerts_maxlen: int = 50, queue_size_threshold: float = 0.9, success_rate_threshold: float = 0.8, trend_analysis_window: int = 10) -> None`**: Initializes the datagram performance monitor.
  - `datagram_transport` (`WebTransportDatagramTransport`): The datagram transport instance to monitor.
  - `monitoring_interval` (`float`): Interval in seconds between metrics collection. `Default: 5.0`.
  - `samples_maxlen` (`int`): Maximum number of historical metric samples to retain. `Default: 100`.
  - `alerts_maxlen` (`int`): Maximum number of historical alerts to retain. `Default: 50`.
  - `queue_size_threshold` (`float`): Threshold (0.0 to 1.0) of `outgoing_high_water_mark` before triggering a high queue size alert. `Default: 0.9`.
  - `success_rate_threshold` (`float`): Threshold (0.0 to 1.0) for the send success rate before triggering an alert. `Default: 0.8`.
  - `trend_analysis_window` (`int`): Number of recent samples to use for trend analysis (e.g., detecting increasing send times). `Default: 10`.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context and starts the background monitoring loop.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context and stops the background monitoring loop.
- **`def clear_history(self) -> None`**: Clears all collected metrics and generated alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated alerts (up to `limit`).
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history snapshots (up to `limit`).
- **`def get_samples(self, *, limit: int | None = None) -> list[dict[str, Any]]`**: Alias for `get_metrics_history`. Returns collected performance samples.

## ServerMonitor Class

Monitors server performance and health. It periodically collects statistics from a `WebTransportServer` instance and can generate alerts if the server becomes unhealthy or degraded (e.g., low connection success rate).

**Note on Usage**: `ServerMonitor` must be used as an asynchronous context manager (`async with monitor: ...`).

### Constructor

- **`def __init__(self, server: WebTransportServer, *, monitoring_interval: float = 30.0) -> None`**: Initializes the server monitor.
  - `server` (`WebTransportServer`): The server instance to monitor.
  - `monitoring_interval` (`float`): The interval in seconds between metrics collection attempts. `Default: 30.0`.

### Properties

- `is_monitoring` (`bool`): `True` if the monitoring task is currently active.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context and starts the background monitoring loop.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context and stops the background monitoring loop.
- **`def clear_history(self) -> None`**: Clears all collected metrics and generated alerts history.
- **`def get_alerts(self, *, limit: int = 25) -> list[dict[str, Any]]`**: Returns a list of recently generated health alerts (up to `limit`).
- **`def get_current_metrics(self) -> dict[str, Any] | None`**: Gets the latest collected metrics snapshot, or `None` if none exist yet.
- **`def get_health_status(self) -> dict[str, Any]`**: Returns the current inferred server health status (e.g., "healthy", "degraded", "unhealthy", "idle", "unknown") based on the latest metrics.
- **`def get_metrics_history(self, *, limit: int = 100) -> list[dict[str, Any]]`**: Returns a list of recent metrics history snapshots (up to `limit`).

## See Also

- **[Client API](client.md)**: Learn how to create and manage client connections.
- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Datagram API](datagram.md)**: Send and receive unreliable datagrams.
- **[Server API](server.md)**: Build and manage WebTransport servers.
