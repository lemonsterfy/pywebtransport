# API Reference: datagram

This document provides a reference for the `pywebtransport.datagram` subpackage, which provides abstractions for the WebTransport datagram transport layer.

---

## WebTransportDatagramTransport Class

The primary interface for sending and receiving raw WebTransport datagrams for a specific session.

**Note on Usage**: `WebTransportDatagramTransport` is not instantiated directly but is created and managed internally, typically accessed via `WebTransportSession.create_datagram_transport()`. It requires `await transport.initialize()` to be called by its creator before use and should ideally be managed within an `async with` block or explicitly closed.

### Properties

- `bytes_received` (`int`): The total number of bytes received across all datagrams.
- `bytes_sent` (`int`): The total number of bytes sent across all datagrams.
- `datagrams_received` (`int`): The total number of datagrams successfully received and queued.
- `datagrams_sent` (`int`): The total number of datagrams successfully passed to the underlying sender.
- `diagnostics` (`DatagramTransportDiagnostics`): Get a snapshot of the datagram transport's diagnostics, stats, and queue info.
- `incoming_max_age` (`float | None`): The maximum age in seconds for incoming datagrams before being dropped by the internal queue cleanup task.
- `is_closed` (`bool`): `True` if the transport has been closed.
- `is_readable` (`bool`): `True` if the transport is open and can potentially receive datagrams.
- `is_writable` (`bool`): `True` if the transport is open and can potentially send datagrams.
- `max_datagram_size` (`int`): The maximum payload size in bytes allowed for a single datagram, dictated by the QUIC connection parameters.
- `outgoing_high_water_mark` (`int`): The maximum number of datagrams allowed in the outgoing buffer (queue). Sends will fail or block if this is exceeded.
- `outgoing_max_age` (`float | None`): The maximum age in seconds for outgoing datagrams before being dropped by the internal queue cleanup task.
- `receive_sequence` (`int`): The sequence number assigned to the next datagram received from the protocol layer.
- `send_sequence` (`int`): The sequence number assigned to the next datagram sent by the user.
- `session_id` (`SessionId`): The session ID associated with this transport.

### Instance Methods

- **`async def clear_receive_buffer(self) -> int`**: Clears the internal receive buffer and returns the number of datagrams discarded.
- **`async def clear_send_buffer(self) -> int`**: Clears the internal send buffer and returns the number of datagrams discarded.
- **`async def close(self) -> None`**: Closes the datagram transport, stops background tasks, and cleans up resources.
- **`async def disable_heartbeat(self) -> None`**: Stops the periodic heartbeat sender task if it is running.
- **`def enable_heartbeat(self, *, interval: float = 30.0) -> None`**: Starts a background task that sends periodic heartbeat datagrams. Requires the transport to be initialized.
- **`def get_receive_buffer_size(self) -> int`**: Returns the current number of datagrams waiting in the receive buffer.
- **`def get_send_buffer_size(self) -> int`**: Returns the current number of datagrams waiting in the send buffer.
- **`async def initialize(self) -> None`**: Initializes internal queues, locks, and background tasks. Must be called before sending or receiving.
- **`async def receive(self, *, timeout: float | None = None) -> bytes`**: Waits for and returns the payload of the next incoming datagram. Raises `TimeoutError` if the timeout expires.
- **`async def receive_from_protocol(self, *, data: bytes) -> None`**: Internal method called by the protocol layer to push a received raw datagram into the transport's incoming queue.
- **`async def receive_json(self, *, timeout: float | None = None) -> Any`**: Receives the next datagram and deserializes it as JSON. Raises `DatagramError` on parsing failure.
- **`async def receive_multiple(self, *, max_count: int = 10, timeout: float | None = None) -> list[bytes]`**: Receives up to `max_count` datagrams. Waits for the first datagram according to `timeout`, then retrieves subsequent datagrams without blocking until the buffer is empty or `max_count` is reached.
- **`async def receive_with_metadata(self, *, timeout: float | None = None) -> dict[str, Any]`**: Receives the next datagram along with associated metadata (size, age, sequence, etc.).
- **`async def send(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> None`**: Sends a datagram. Raises `DatagramError` if the transport is closed, the outgoing queue is full, or the datagram has expired based on `ttl`. Raises `ValueError` if data exceeds `max_datagram_size`. Priority influences queue order (2=high, 1=medium, 0=low).
- **`async def send_json(self, *, data: Any, priority: int = 0, ttl: float | None = None) -> None`**: Serializes a Python object to JSON and sends it as a datagram. Raises `DatagramError` on serialization failure.
- **`async def send_multiple(self, *, datagrams: list[Data], priority: int = 0, ttl: float | None = None) -> int`**: Sends multiple datagrams sequentially. Returns the number successfully queued before any failure occurred.
- **`async def try_receive(self) -> bytes | None`**: Attempts to receive a datagram from the buffer without blocking. Returns the datagram payload or `None` if the buffer is empty.
- **`async def try_send(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> bool`**: Attempts to send a datagram without blocking. Returns `True` if successfully queued, `False` otherwise (e.g., queue full, expired TTL, size limit exceeded).

## StructuredDatagramTransport Class

A high-level wrapper around `WebTransportDatagramTransport` for sending and receiving typed Python objects. It handles object serialization/deserialization and adds a type identifier header.

**Note on Usage**: This class requires a base `WebTransportDatagramTransport`, a `Serializer` instance, and a type registry mapping integer IDs to object types. It is typically created via a helper method rather than direct instantiation.

### Constructor

- **`def __init__(self, *, datagram_transport: WebTransportDatagramTransport, serializer: Serializer, registry: dict[int, type[Any]]) -> None`**: Initializes the structured datagram transport.
  - `datagram_transport` (`WebTransportDatagramTransport`): The underlying transport to use.
  - `serializer` (`Serializer`): The serializer instance (e.g., `JSONSerializer`) for encoding/decoding objects.
  - `registry` (`dict[int, type[Any]]`): A mapping from integer type IDs to Python class types. Type IDs must be unique.

### Properties

- `is_closed` (`bool`): `True` if the underlying datagram transport is closed.

### Instance Methods

- **`async def close(self) -> None`**: Closes the underlying datagram transport.
- **`async def receive_obj(self, *, timeout: float | None = None) -> Any`**: Receives the next datagram, reads the type ID, deserializes the payload into the corresponding Python object from the registry, and returns it. Raises `SerializationError` if the type ID is unknown or deserialization fails.
- **`async def send_obj(self, *, obj: Any, priority: int = 0, ttl: float | None = None) -> None`**: Determines the type ID of the object from the registry, serializes the object, prepends the type ID header, and sends the resulting datagram using the underlying transport. Raises `SerializationError` if the object's type is not in the registry.

## DatagramReliabilityLayer Class

Adds TCP-like reliability (acknowledgments and retries) over an underlying `WebTransportDatagramTransport`. It introduces a simple protocol using "DATA" and "ACK" message types.

**Note on Usage**: `DatagramReliabilityLayer` must be used as an asynchronous context manager (`async with layer: ...`). It takes ownership of the underlying datagram transport's receive path.

### Constructor

- **`def __init__(self, datagram_transport: WebTransportDatagramTransport, *, ack_timeout: float = 2.0, max_retries: int = 5) -> None`**: Initializes the reliability layer.
  - `datagram_transport` (`WebTransportDatagramTransport`): The underlying unreliable transport.
  - `ack_timeout` (`float`): Time in seconds to wait for an ACK before retrying a sent datagram. `Default: 2.0`.
  - `max_retries` (`int`): Maximum number of times to retry sending an unacknowledged datagram before giving up. `Default: 5`.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context, initializing internal queues, locks, starting the background retry task, and attaching listeners to the underlying transport.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context, stops the retry task, detaches listeners, and cleans up resources.
- **`async def close(self) -> None`**: Gracefully closes the reliability layer, stopping background tasks and clearing internal state. Does not close the underlying transport.
- **`async def receive(self, *, timeout: float | None = None) -> bytes`**: Waits for and returns the payload of the next reliably received datagram (handles ACKs, duplicates, and reordering internally). Raises `TimeoutError` on timeout.
- **`async def send(self, *, data: Data) -> None`**: Sends a datagram reliably. The method returns after the datagram is initially sent; delivery is managed by background ACK checks and retries. Raises `DatagramError` if the layer or transport is closed.

## DatagramBroadcaster Class

A utility to send a single datagram to multiple `WebTransportDatagramTransport` instances concurrently.

**Note on Usage**: `DatagramBroadcaster` must be used as an asynchronous context manager (`async with broadcaster: ...`).

### Constructor

- **`def __init__(self) -> None`**: Initializes the datagram broadcaster.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context, initializing internal locks.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context, clearing the list of managed transports.
- **`async def add_transport(self, *, transport: WebTransportDatagramTransport) -> None`**: Adds a datagram transport to the list of recipients for broadcasts.
- **`async def broadcast(self, *, data: Data, priority: int = 0, ttl: float | None = None) -> int`**: Sends the given datagram concurrently to all currently registered, active transports. Returns the number of transports the datagram was successfully sent to. Failed or closed transports are automatically removed.
- **`async def get_transport_count(self) -> int`**: Returns the current number of transports registered with the broadcaster.
- **`async def remove_transport(self, *, transport: WebTransportDatagramTransport) -> None`**: Removes a specific transport from the broadcast list.
- **`async def shutdown(self) -> None`**: Clears the list of transports, effectively stopping broadcasts.

## Supporting Data Classes

### DatagramTransportDiagnostics Class

A structured, immutable snapshot of a `WebTransportDatagramTransport`'s health, including statistics and queue information.

### Attributes

- `stats` (`DatagramStats`): The full statistics object for the transport.
- `queue_stats` (`dict[str, dict[str, int]]`): Statistics for the internal 'incoming' and 'outgoing' queues (e.g., current size, max size).
- `is_closed` (`bool`): `True` if the transport is closed.

### Properties

- `issues` (`list[str]`): A list of potential issues derived from the diagnostics (e.g., "Low send success rate", "Outgoing queue nearly full").

### DatagramStats Class

A dataclass holding detailed statistics for a `WebTransportDatagramTransport`.

### Attributes

- `session_id` (`SessionId`): The session ID associated with these stats.
- `created_at` (`float`): Timestamp when the datagram transport was created.
- `datagrams_sent` (`int`): Total datagrams successfully passed to the sender function. `Default: 0`.
- `bytes_sent` (`int`): Total bytes sent. `Default: 0`.
- `send_failures` (`int`): Number of times the sender function raised an exception. `Default: 0`.
- `send_drops` (`int`): Number of datagrams dropped before sending (e.g., queue full, expired TTL, size exceeded). `Default: 0`.
- `datagrams_received` (`int`): Total datagrams successfully received and placed in the incoming queue. `Default: 0`.
- `bytes_received` (`int`): Total bytes received. `Default: 0`.
- `receive_drops` (`int`): Number of datagrams dropped after receiving (e.g., queue full, expired TTL). `Default: 0`.
- `receive_errors` (`int`): Number of errors encountered while processing received datagrams. `Default: 0`.
- `total_send_time` (`float`): Cumulative time spent executing the sender function. `Default: 0.0`.
- `total_receive_time` (`float`): Cumulative time spent by users waiting in `receive()` calls. `Default: 0.0`.
- `max_send_time` (`float`): The longest time a single sender function execution took. `Default: 0.0`.
- `max_receive_time` (`float`): The longest time a single successful `receive()` call took. `Default: 0.0`.
- `min_datagram_size` (`float`): The size of the smallest datagram processed (sent or received). `Default: inf`.
- `max_datagram_size` (`int`): The size of the largest datagram processed. `Default: 0`.
- `total_datagram_size` (`int`): Cumulative size of all datagrams processed. `Default: 0`.

### Properties

- `avg_datagram_size` (`float`): The average size of all datagrams processed.
- `avg_receive_time` (`float`): The average time spent waiting in successful `receive()` calls.
- `avg_send_time` (`float`): The average time spent executing the sender function per successful send.
- `receive_success_rate` (`float`): Proportion of datagrams received vs. receive errors.
- `send_success_rate` (`float`): Proportion of datagrams successfully sent vs. send failures.

### Instance Methods

- **`def to_dict(self) -> dict[str, Any]`**: Converts the statistics object to a dictionary, including calculated properties.

### DatagramMessage Class

Internal representation of a datagram with metadata, used within queues.

### Attributes

- `data` (`bytes`): The raw payload of the datagram.
- `timestamp` (`float`): Timestamp of message creation (used for TTL checks). `Default: <factory>`.
- `size` (`int`): The size of the data payload in bytes (computed automatically).
- `checksum` (`str | None`): A pre-computed checksum (first 8 chars of SHA256) of the data. `Default: <factory>`.
- `sequence` (`int | None`): An optional sequence number assigned by the transport. `Default: None`.
- `priority` (`int`): The priority level for queueing (0-2). `Default: 0`.
- `ttl` (`float | None`): Time-to-live in seconds. If expired, the datagram may be dropped. `Default: None`.

### Properties

- `age` (`float`): The current age of the datagram in seconds since creation.
- `is_expired` (`bool`): `True` if the datagram's age has exceeded its TTL.

### Instance Methods

- **`def to_dict(self) -> dict[str, Any]`**: Converts the datagram message metadata to a dictionary.

## See Also

- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Monitor API](monitor.md)**: Monitor the health and performance of components.
- **[Serializer API](serializer.md)**: Learn about pluggable serializers for structured data.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
