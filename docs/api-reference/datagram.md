# API Reference: datagram

This document provides a reference for the `pywebtransport.datagram` subpackage, which offers an interface for sending and receiving unreliable datagrams.

---

## WebTransportDatagramTransport Class

The primary interface for sending and receiving WebTransport datagrams, accessed via `session.datagrams`.

**Note on Usage**: `WebTransportDatagramTransport` is initialized automatically upon first access via `await session.datagrams`.

### Constructor

- **`def __init__(self, session: WebTransportSession, *, high_water_mark: int = 100, sender_get_timeout: float = 1.0)`**: Initializes the datagram duplex transport.

### Properties

- `bytes_received` (`int`): The total number of bytes received.
- `bytes_sent` (`int`): The total number of bytes sent.
- `datagrams_received` (`int`): The total number of datagrams received.
- `datagrams_sent` (`int`): The total number of datagrams sent.
- `incoming_max_age` (`float | None`): The maximum age for incoming datagrams before being dropped.
- `is_closed` (`bool`): `True` if the transport has been closed.
- `is_readable` (`bool`): `True` if the readable side of the transport is open.
- `is_writable` (`bool`): `True` if the writable side of the transport is open.
- `max_datagram_size` (`int`): The maximum datagram size allowed by the QUIC connection.
- `outgoing_high_water_mark` (`int`): The high water mark for the outgoing buffer.
- `outgoing_max_age` (`float | None`): The maximum age for outgoing datagrams before being dropped.
- `receive_sequence` (`int`): The current receive sequence number.
- `send_sequence` (`int`): The current send sequence number.
- `session` (`WebTransportSession | None`): A weak reference to the parent session.
- `session_id` (`SessionId`): The session ID associated with this transport.
- `stats` (`dict[str, Any]`: A dictionary of all datagram statistics.

### Instance Methods

- **`async def clear_receive_buffer(self) -> int`**: Clears the receive buffer and returns the number of cleared datagrams.
- **`async def clear_send_buffer(self) -> int`**: Clears the send buffer and returns the number of cleared datagrams.
- **`async def close(self) -> None`**: Closes the datagram transport and cleans up all resources.
- **`def debug_state(self) -> dict[str, Any]`**: Returns a detailed snapshot of the transport's internal state for debugging.
- **`async def diagnose_issues(self) -> list[str]`**: Analyzes transport statistics to identify and report potential issues.
- **`def get_queue_stats(self) -> dict[str, dict[str, int]]`**: Returns detailed statistics for the internal queues.
- **`def get_receive_buffer_size(self) -> int`**: Returns the current number of datagrams in the receive buffer.
- **`def get_send_buffer_size(self) -> int`**: Returns the current number of datagrams in the send buffer.
- **`async def initialize(self) -> None`**: Initializes the transport, preparing it for use.
- **`async def receive(self, *, timeout: float | None = None) -> bytes`**: Waits for and returns the next incoming datagram.
- **`async def receive_json(self, *, timeout: float | None = None) -> Any`**: Receives and deserializes a JSON-encoded datagram.
- **`async def receive_multiple(self, *, max_count: int = 10, timeout: float | None = None) -> list[bytes]`**: Receives multiple datagrams in a batch.
- **`async def receive_with_metadata(self, *, timeout: float | None = None) -> dict[str, Any]`**: Receives a datagram along with its metadata.
- **`async def send(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> None`**: Sends a datagram.
- **`async def send_json(self, *, data: Any, priority: int = 0, ttl: float | None = None) -> None`**: Serializes a Python object to JSON and sends it as a datagram.
- **`async def send_multiple(self, *, datagrams: list[Data], priority: int = 0, ttl: float | None = None) -> int`**: Sends multiple datagrams and returns the number successfully sent.
- **`def start_heartbeat(self, *, interval: float = 30.0) -> asyncio.Task[None]`**: Runs a task that sends periodic heartbeat datagrams.
- **`async def try_receive(self) -> bytes | None`**: Attempts to receive a datagram without blocking.
- **`async def try_send(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> bool`**: Attempts to send a datagram without blocking.

## StructuredDatagramTransport Class

A high-level wrapper for sending and receiving structured objects over a datagram transport.

### Constructor

- **`def __init__(self, *, datagram_transport: WebTransportDatagramTransport, serializer: Serializer, registry: dict[int, Type[Any]])`**: Initializes the structured datagram transport.

### Properties

- `is_closed` (`bool`): `True` if the underlying datagram transport is closed.

### Instance Methods

- **`async def close(self) -> None`**: Closes the underlying datagram transport.
- **`async def receive_obj(self, *, timeout: float | None = None) -> Any`**: Receives and deserializes a Python object from a datagram.
- **`async def send_obj(self, *, obj: Any, priority: int = 0, ttl: float | None = None) -> None`**: Serializes and sends a Python object as a datagram.

## DatagramReliabilityLayer Class

Adds TCP-like reliability (acknowledgments and retries) over a datagram transport.

**Note on Usage**: `DatagramReliabilityLayer` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, datagram_transport: WebTransportDatagramTransport, *, ack_timeout: float = 2.0, max_retries: int = 5)`**: Initializes the reliability layer.

### Class Methods

- **`def create(cls, *, datagram_transport: WebTransportDatagramTransport, ack_timeout: float = 1.0, max_retries: int = 3) -> Self`**: Factory method to create a new datagram reliability layer.

### Instance Methods

- **`async def close(self) -> None`**: Gracefully closes the reliability layer and cleans up resources.
- **`async def receive(self, *, timeout: float | None = None) -> bytes`**: Receives a reliable datagram.
- **`async def send(self, *, data: Data) -> None`**: Sends a datagram with guaranteed delivery.

## DatagramBroadcaster Class

A helper to send a single datagram to multiple datagram transports concurrently.

**Note on Usage**: `DatagramBroadcaster` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self) -> None`**: Initializes the datagram broadcaster.

### Class Methods

- **`def create(cls) -> Self`**: Factory method to create a new datagram broadcaster instance.

### Instance Methods

- **`async def add_transport(self, *, transport: WebTransportDatagramTransport) -> None`**: Adds a transport to the broadcast list.
- **`async def broadcast(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> int`**: Sends a datagram to all registered transports.
- **`async def get_transport_count(self) -> int`**: Gets the current number of active transports safely.
- **`async def remove_transport(self, *, transport: WebTransportDatagramTransport) -> None`**: Removes a transport from the broadcast list.

## DatagramMonitor Class

Monitors the performance of a datagram transport, collecting samples and generating alerts.

**Note on Usage**: `DatagramMonitor` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, datagram_transport: WebTransportDatagramTransport, *, monitoring_interval: float = 5.0, samples_maxlen: int = 100, ...)`**: Initializes the monitor.

### Properties

- `is_monitoring` (`bool`): `True` if the monitor is active.

### Class Methods

- **`def create(cls, *, datagram_transport: WebTransportDatagramTransport, monitoring_interval: float = 5.0) -> Self`**: Factory method to create a new datagram monitor.

### Instance Methods

- **`def get_alerts(self) -> list[dict[str, Any]]`**: Returns a list of generated alerts.
- **`def get_samples(self, *, limit: int | None = None) -> list[dict[str, Any]]`**: Returns a list of collected performance samples.

## Supporting Data Classes

### DatagramStats Class

A dataclass holding statistics for a datagram transport.

### Attributes

- `session_id` (`SessionId`): The session ID associated with these stats.
- `created_at` (`float`): Timestamp when the datagram transport was created.
- `datagrams_sent` (`int`): Total datagrams sent. `Default: 0`.
- `bytes_sent` (`int`): Total bytes sent. `Default: 0`.
- `send_failures` (`int`): Number of send operations that failed. `Default: 0`.
- `send_drops` (`int`): Number of datagrams dropped before sending. `Default: 0`.
- `datagrams_received` (`int`): Total datagrams received. `Default: 0`.
- `bytes_received` (`int`): Total bytes received. `Default: 0`.
- `receive_drops` (`int`): Number of datagrams dropped before being processed. `Default: 0`.
- `receive_errors` (`int`): Number of errors during datagram processing. `Default: 0`.
- `total_send_time` (`float`): Cumulative time spent in send operations. `Default: 0.0`.
- `total_receive_time` (`float`): Cumulative time spent waiting for receives. `Default: 0.0`.
- `max_send_time` (`float`): The longest time a single send operation took. `Default: 0.0`.
- `max_receive_time` (`float`): The longest time a single receive operation took. `Default: 0.0`.
- `min_datagram_size` (`float`): The size of the smallest datagram processed. `Default: inf`.
- `max_datagram_size` (`int`): The size of the largest datagram processed. `Default: 0`.
- `total_datagram_size` (`int`): Cumulative size of all datagrams processed. `Default: 0`.

### Properties

- `avg_datagram_size` (`float`): The average size of all datagrams.
- `avg_receive_time` (`float`): The average receive time for datagrams.
- `avg_send_time` (`float`): The average send time for datagrams.
- `receive_success_rate` (`float`): The success rate of receiving datagrams.
- `send_success_rate` (`float`): The success rate of sending datagrams.

### DatagramMessage Class

An internal representation of a datagram with metadata.

### Attributes

- `data` (`bytes`): The raw payload of the datagram.
- `timestamp` (`float`): Timestamp of message creation.
- `size` (`int`): The size of the data payload in bytes (computed automatically).
- `checksum` (`str | None`): An optional checksum of the data. `Default: None`.
- `sequence` (`int | None`): An optional sequence number. `Default: None`.
- `priority` (`int`): The priority level for queueing. `Default: 0`.
- `ttl` (`float | None`): Time-to-live in seconds. `Default: None`.

### Properties

- `age` (`float`): The current age of the datagram in seconds.
- `is_expired` (`bool`): `True` if the datagram's age has exceeded its TTL.

### DatagramQueue Class

A priority queue with TTL and size limits used internally for buffering.

## Utility Functions

### Module-Level Functions

- **`def create_heartbeat_datagram() -> bytes`**: Creates a new heartbeat datagram payload.
- **`async def datagram_throughput_test(*, datagram_transport: WebTransportDatagramTransport, duration: float = 10.0, datagram_size: int = 1000) -> dict[str, Any]`**: Runs a performance test on the transport to measure throughput.
- **`def is_heartbeat_datagram(*, data: bytes) -> bool`**: Returns `True` if the provided data is a heartbeat datagram.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
