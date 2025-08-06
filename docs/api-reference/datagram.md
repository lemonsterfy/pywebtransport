# API Reference: Datagram

This document provides a comprehensive reference for the `pywebtransport.datagram` subpackage, which offers a powerful interface for sending and receiving unreliable datagrams, along with advanced components for broadcasting, monitoring, and reliability.

---

## Core Components

### WebTransportDatagramDuplexStream Class

The primary interface for sending and receiving WebTransport datagrams. An instance of this class is typically accessed via the `session.datagrams` asynchronous property.

**Note on Initialization**: `WebTransportDatagramDuplexStream` has an asynchronous initialization phase. It is automatically initialized upon first access via `await session.datagrams`.

#### Key Methods

##### Sending Datagrams

- **`async def send(self, data: Data, *, priority: int = 0, ttl: float | None = None) -> None`**: Sends a datagram. Raises `DatagramError` if the outgoing queue is full or the data exceeds `max_datagram_size`.
- **`async def try_send(self, data: Data, *, priority: int = 0, ttl: float | None = None) -> bool`**: Attempts to send a datagram without blocking. Returns `False` if the outgoing buffer is full or the data is too large.
- **`async def send_multiple(self, datagrams: list[Data], ...) -> int`**: Sends multiple datagrams and returns the number successfully sent.
- **`async def send_json(self, data: Any, *, ...) -> None`**: Serializes a Python object to JSON and sends it as a datagram.
- **`async def send_structured(self, message_type: str, payload: bytes, *, ...)`**: Sends a datagram with a prepended type header for structured messaging.

##### Receiving Datagrams

- **`async def receive(self, *, timeout: float | None = None) -> bytes`**: Waits for and returns the next incoming datagram. Raises `TimeoutError` if the timeout is exceeded.
- **`async def try_receive(self) -> bytes | None`**: Attempts to receive a datagram without blocking. Returns `None` if the incoming buffer is empty.
- **`async def receive_multiple(self, *, max_count: int = 10, timeout: float | None = None) -> list[bytes]`**: Receives multiple datagrams in a batch.
- **`async def receive_with_metadata(self, *, timeout: float | None = None) -> dict[str, Any]`**: Receives a datagram along with its metadata (timestamp, sequence, etc.).
- **`async def receive_json(self, *, timeout: float | None = None) -> Any`**: Receives and deserializes a JSON-encoded datagram.
- **`async def receive_structured(self, *, timeout: float | None = None) -> tuple[str, bytes]`**: Receives and parses a structured datagram into its `(type, payload)` tuple.

#### Properties & Other Methods

- `is_closed` (`bool`): `True` if the stream has been closed.
- `max_datagram_size` (`int`): The maximum size in bytes for a single datagram payload.
- `stats` (`dict[str, Any]`): A dictionary of detailed performance statistics.
- `session` (`WebTransportSession | None`): A weak reference to the parent session.
- **`async def close(self) -> None`**: Closes the datagram stream and cleans up all resources.

#### Monitoring & Debugging

- **`get_send_buffer_size(self) -> int`**: Returns the current number of datagrams in the send buffer.
- **`get_receive_buffer_size(self) -> int`**: Returns the current number of datagrams in the receive buffer.
- **`get_queue_stats(self) -> dict[str, dict[str, int]]`**: Returns detailed statistics for the internal queues.
- **`debug_state(self) -> dict[str, Any]`**: Returns a detailed snapshot of the stream's internal state for debugging.
- **`async def diagnose_issues(self) -> list[str]`**: Analyzes stream statistics to identify and report potential issues.

---

## Advanced Components

### DatagramReliabilityLayer Class

An async context manager that adds TCP-like reliability (acknowledgments and retries) over a `WebTransportDatagramDuplexStream`.

**Note on Usage**: `DatagramReliabilityLayer` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, datagram_stream: WebTransportDatagramDuplexStream, *, ack_timeout: float = 2.0, max_retries: int = 5)`**: Initializes the reliability layer.

#### Instance Methods

- **`async def send(self, data: Data) -> None`**: Sends a datagram with guaranteed delivery.
- **`async def receive(self, *, timeout: float | None = None) -> bytes`**: Receives a reliable datagram.

### DatagramBroadcaster Class

A helper class to send a single datagram to multiple `WebTransportDatagramDuplexStream` instances concurrently.

**Note on Usage**: `DatagramBroadcaster` must be used as an asynchronous context manager (`async with ...`).

#### Instance Methods

- **`async def add_stream(self, stream: WebTransportDatagramDuplexStream) -> None`**: Adds a stream to the broadcast list.
- **`async def remove_stream(self, stream: WebTransportDatagramDuplexStream) -> None`**: Removes a stream from the broadcast list.
- **`async def broadcast(self, data: Data, *, priority: int = 0, ttl: float | None = None) -> int`**: Sends a datagram to all registered streams and returns the count of successful sends.

### DatagramMonitor Class

An async context manager that monitors the performance of a `WebTransportDatagramDuplexStream`, collecting samples and generating alerts.

**Note on Usage**: `DatagramMonitor` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, datagram_stream: WebTransportDatagramDuplexStream, *, monitoring_interval: float = 5.0, ...)`**: Initializes the monitor.

#### Properties

- `is_monitoring` (`bool`): `True` if the monitor is active.

#### Instance Methods

- **`get_samples(self, *, limit: int | None = None) -> list[dict[str, Any]]`**: Returns a list of collected performance samples.
- **`get_alerts(self) -> list[dict[str, Any]]`**: Returns a list of generated alerts (e.g., for high queue size or low success rate).

---

## Supporting Data Classes

### DatagramStats Class

A dataclass holding a rich set of statistics for a datagram stream, including send/receive counts, success rates, and average timings.

### DatagramMessage Class

An internal representation of a datagram with metadata like `timestamp`, `priority`, and `ttl`.

### DatagramQueue Class

A priority queue with TTL and size limits, used internally by the datagram stream for buffering.

---

## Utility Functions

These helper functions are available in the `pywebtransport.datagram.utils` module.

- **`create_heartbeat_datagram() -> bytes`**: Creates a new heartbeat datagram payload.
- **`is_heartbeat_datagram(data: bytes) -> bool`**: Returns `True` if the provided data is a heartbeat datagram.
- **`async def datagram_throughput_test(datagram_stream: WebTransportDatagramDuplexStream, *, duration: float = 10.0, ...)`**: Runs a performance test on the stream to measure throughput and error rates.

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
