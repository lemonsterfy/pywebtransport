# API Reference: Datagram

This document provides a comprehensive reference for the `pywebtransport.datagram` subpackage, which offers a powerful interface for sending and receiving unreliable datagrams, along with advanced components for broadcasting, monitoring, and reliability.

---

## `WebTransportDatagramDuplexStream` Class

The primary interface for sending and receiving WebTransport datagrams. An instance of this class is typically accessed via `session.datagrams`.

### Key Methods

#### Sending Datagrams

- **`send(self, data: Data, *, priority: int = 0, ttl: Optional[float] = None) -> None`**:
  Sends a datagram. Raises `DatagramError` if the outgoing queue is full or the data exceeds `max_datagram_size`.
- **`try_send(self, data: Data, *, priority: int = 0, ttl: Optional[float] = None) -> bool`**:
  Attempts to send a datagram without blocking. Returns `False` if the outgoing buffer is full.
- **`send_json(self, data: Any, *, priority: int = 0, ttl: Optional[float] = None) -> None`**:
  Serializes a Python object to JSON and sends it as a datagram.
- **`send_structured(self, message_type: str, payload: bytes, *, ...)`**:
  Sends a datagram with a prepended type header for structured messaging.

#### Receiving Datagrams

- **`receive(self, *, timeout: Optional[float] = None) -> bytes`**:
  Waits for and returns the next incoming datagram. Raises `TimeoutError` if the timeout is exceeded.
- **`try_receive(self) -> Optional[bytes]`**:
  Attempts to receive a datagram without blocking. Returns `None` if the incoming buffer is empty.
- **`receive_json(self, *, timeout: Optional[float] = None) -> Any`**:
  Receives and deserializes a JSON-encoded datagram.
- **`receive_structured(self, *, timeout: Optional[float] = None) -> Tuple[str, bytes]`**:
  Receives and parses a structured datagram into its `(type, payload)` tuple.

### Properties

- **`is_closed` (bool)**: `True` if the stream has been closed.
- **`max_datagram_size` (int)**: The maximum size in bytes for a single datagram payload.
- **`stats` (Dict[str, Any])**: A dictionary of detailed performance statistics.
- **`session` (Optional[WebTransportSession])**: A weak reference to the parent session.

---

## Advanced Components

### `DatagramReliabilityLayer` Class

An async context manager that adds TCP-like reliability (acknowledgments and retries) over a `WebTransportDatagramDuplexStream`.

- **`__init__(self, datagram_stream: WebTransportDatagramDuplexStream, *, ack_timeout: float = 2.0, max_retries: int = 5)`**
- **`send(self, data: Data) -> None`**: Sends a datagram with guaranteed delivery. The call completes when the message is queued; delivery is handled in the background.
- **`receive(self, *, timeout: Optional[float] = None) -> bytes`**: Receives a reliable datagram.

### `DatagramBroadcaster` Class

A helper class to send a single datagram to multiple `WebTransportDatagramDuplexStream` instances concurrently.

- **`add_stream(self, stream: WebTransportDatagramDuplexStream) -> None`**: Adds a stream to the broadcast list.
- **`remove_stream(self, stream: WebTransportDatagramDuplexStream) -> None`**: Removes a stream from the broadcast list.
- **`broadcast(self, data: Data, *, priority: int = 0, ttl: Optional[float] = None) -> int`**: Sends a datagram to all registered streams and returns the count of successful sends.

### `DatagramMonitor` Class

An async context manager that monitors the performance of a `WebTransportDatagramDuplexStream`, collecting samples and generating alerts.

- **`__init__(self, datagram_stream: WebTransportDatagramDuplexStream, *, monitoring_interval: float = 5.0, ...)`**
- **`is_monitoring` (property)**: `True` if the monitor is active.
- **`get_samples(self, *, limit: Optional[int] = None) -> List[Dict[str, Any]]`**: Returns a list of collected performance samples.
- **`get_alerts(self) -> List[Dict[str, Any]]`**: Returns a list of generated alerts (e.g., for high queue size or low success rate).

---

## Supporting Data Classes

- **`DatagramStats`**: A dataclass holding a rich set of statistics for a datagram stream, including send/receive counts, success rates, and average timings.
- **`DatagramMessage`**: An internal representation of a datagram with metadata like `timestamp`, `priority`, and `ttl`.
- **`DatagramQueue`**: A priority queue with TTL and size limits, used internally by the datagram stream for buffering.

---

## Datagram Utility Functions

These helper functions are available in the `pywebtransport.datagram.utils` module.

- **`create_heartbeat_datagram() -> bytes`**:
  Creates a new heartbeat datagram payload.

- **`is_heartbeat_datagram(data: bytes) -> bool`**:
  Returns `True` if the provided data is a heartbeat datagram.

- **`datagram_throughput_test(datagram_stream: WebTransportDatagramDuplexStream, *, duration: float = 10.0, ...)`**:
  Runs a performance test on the stream to measure throughput and error rates.

---

## See Also

- [**Session API**](session.md): The `WebTransportSession` class that owns the datagram stream.
- [**Events API**](events.md): Datagram-related events like `DATAGRAM_RECEIVED`.
- [**Exceptions API**](exceptions.md): The `DatagramError` exception.
- [**Types API**](types.md): Core type definitions used by the datagram module.
