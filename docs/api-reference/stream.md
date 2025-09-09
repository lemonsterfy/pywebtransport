# API Reference: stream

This document provides a reference for the `pywebtransport.stream` subpackage, which contains classes for stream communication.

---

## WebTransportStream Class

Represents a bidirectional WebTransport stream that can be both read from and written to. It inherits all methods and properties from `WebTransportReceiveStream` and `WebTransportSendStream`.

### Instance Methods

- **`async def close(self) -> None`**: Gracefully closes the stream's write side by sending a `FIN` bit.
- **`async def diagnose_issues(self, *, error_rate_threshold: float = 0.1, latency_threshold: float = 1.0, stale_threshold: float = 3600.0) -> list[str]`**: Runs checks and returns a list of strings describing potential issues.
- **`async def monitor_health(self, *, check_interval: float = 30.0, error_rate_threshold: float = 0.1) -> None`**: A long-running task that continuously monitors stream health.

## WebTransportSendStream Class

Represents a unidirectional (send-only) WebTransport stream.

### Properties

- `is_writable` (`bool`): `True` if the stream can be written to.

### Instance Methods

- **`async def abort(self, *, code: int = 0) -> None`**: Forcefully closes the stream with an error code.
- **`async def close(self) -> None`**: Gracefully closes the stream's write side by sending a `FIN` bit.
- **`async def flush(self) -> None`**: Waits until the stream's internal write buffer is empty.
- **`async def wait_closed(self) -> None`**: Waits until the stream is fully closed.
- **`async def write(self, *, data: Data, end_stream: bool = False, wait_flush: bool = True) -> None`**: Writes data to the stream.
- **`async def write_all(self, *, data: bytes, chunk_size: int = 8192) -> None`**: Writes a large bytes object to the stream in chunks and then closes it.

## WebTransportReceiveStream Class

Represents a unidirectional (receive-only) WebTransport stream.

### Properties

- `is_readable` (`bool`): `True` if the stream can be read from.

### Instance Methods

- **`async def abort(self, *, code: int = 0) -> None`**: Aborts the reading side of the stream.
- **`async def read(self, *, size: int = 8192) -> bytes`**: Reads up to `size` bytes from the stream. Returns `b""` on EOF.
- **`async def read_all(self, *, max_size: int | None = None) -> bytes`**: Reads the entire stream content into a single bytes object.
- **`async def read_iter(self, *, chunk_size: int = 8192) -> AsyncIterator[bytes]`**: Returns an async iterator to read the stream in chunks.
- **`async def readexactly(self, *, n: int) -> bytes`**: Reads exactly `n` bytes.
- **`async def readline(self) -> bytes`**: Reads one line from the stream.
- **`async def readuntil(self, *, separator: bytes = b"\n") -> bytes`**: Reads data until a separator is found.
- **`async def wait_closed(self) -> None`**: Waits until the stream is fully closed.

## StructuredStream Class

A high-level wrapper for sending and receiving structured Python objects over a `WebTransportStream`.

**Note on Usage**: This class is not instantiated directly but through `WebTransportSession.create_structured_stream()`.

### Constructor

- **`def __init__(self, *, stream: WebTransportStream, serializer: Serializer, registry: dict[int, Type[Any]])`**: Initializes the structured stream.

### Properties

- `is_closed` (`bool`): `True` if the underlying stream is fully closed.
- `stream_id` (`int`): The underlying stream's ID.

### Instance Methods

- **`async def close(self) -> None`**: Closes the underlying stream.
- **`async def receive_obj(self) -> Any`**: Receives, deserializes, and returns a Python object from the stream.
- **`async def send_obj(self, *, obj: Any) -> None`**: Serializes and sends a Python object over the stream.

## Management Classes

### StreamManager Class

Manages the lifecycle of all streams within a `WebTransportSession`, enforcing concurrency limits.

**Note on Usage**: `StreamManager` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, session: WebTransportSession, *, max_streams: int = 100, stream_cleanup_interval: float = 15.0)`**: Initializes the stream manager.

### Instance Methods

- **`async def create_bidirectional_stream(self) -> WebTransportStream`**: Creates a new bidirectional stream.
- **`async def create_unidirectional_stream(self) -> WebTransportSendStream`**: Creates a new unidirectional stream.
- **`async def get_stream(self, *, stream_id: StreamId) -> StreamType | None`**: Retrieves a managed stream by its ID.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics about the managed streams.
- **`async def shutdown(self) -> None`**: Closes all managed streams and stops background tasks.

### StreamPool Class

Manages a pool of reusable `WebTransportStream` objects to reduce the latency of creating new streams.

**Note on Usage**: `StreamPool` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, session: WebTransportSession, *, pool_size: int = 10, maintenance_interval: float = 60.0)`**: Initializes the stream pool.

### Instance Methods

- **`async def close_all(self) -> None`**: Closes all idle streams in the pool and shuts down the pool.
- **`async def get_stream(self, *, timeout: float | None = None) -> WebTransportStream`**: Gets a stream from the pool or creates a new one.
- **`async def return_stream(self, *, stream: WebTransportStream) -> None`**: Returns a healthy stream to the pool for reuse.

## Supporting Data Classes

### StreamStats Class

A dataclass holding statistics for a single stream.

### Attributes

- `stream_id` (`StreamId`): The ID of the stream.
- `created_at` (`float`): Timestamp when the stream was created.
- `closed_at` (`float | None`): Timestamp when the stream was closed. `Default: None`.
- `bytes_sent` (`int`): Total bytes sent. `Default: 0`.
- `bytes_received` (`int`): Total bytes received. `Default: 0`.
- `writes_count` (`int`): Number of write operations. `Default: 0`.
- `reads_count` (`int`): Number of read operations. `Default: 0`.
- `total_write_time` (`float`): Cumulative time spent in write operations. `Default: 0.0`.
- `total_read_time` (`float`): Cumulative time spent in read operations. `Default: 0.0`.
- `max_write_time` (`float`): The longest time a single write operation took. `Default: 0.0`.
- `max_read_time` (`float`): The longest time a single read operation took. `Default: 0.0`.
- `write_errors` (`int`): Number of write operations that failed. `Default: 0`.
- `read_errors` (`int`): Number of read operations that failed. `Default: 0`.
- `flow_control_errors` (`int`): Number of times flow control was triggered. `Default: 0`.

### Properties

- `avg_read_time` (`float`): The average time for a read operation in seconds.
- `avg_write_time` (`float`): The average time for a write operation in seconds.
- `uptime` (`float`): The total uptime of the stream in seconds.

### StreamBuffer Class

An internal, deque-based buffer for asynchronous read operations.

### Constructor

- **`def __init__(self, *, max_size: int = 65536)`**: Initializes the stream buffer.

## Utility Functions

These helper functions are available in the `pywebtransport.stream.utils` module.

- **`async def copy_stream_data(*, source: WebTransportReceiveStream, destination: WebTransportSendStream, chunk_size: int = 8192) -> int`**: Copies all data from a source stream to a destination stream.
- **`async def echo_stream(*, stream: WebTransportStream) -> None`**: Reads all data from a bidirectional stream and writes it back to the same stream.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
