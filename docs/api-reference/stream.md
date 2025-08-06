# API Reference: Stream

This document provides a comprehensive reference for the `pywebtransport.stream` subpackage, which contains the classes for reliable, ordered, and multiplexed stream communication.

---

## Core Stream Classes

These are the primary classes used for stream-based communication. They are typically created via `WebTransportSession` methods and are returned fully initialized and ready for use. All stream classes can be used as async context managers for automatic resource cleanup.

### WebTransportStream Class

Represents a bidirectional WebTransport stream that can be both read from and written to. It inherits all methods from `WebTransportReceiveStream` and `WebTransportSendStream`.

### WebTransportSendStream Class

Represents a unidirectional (send-only) WebTransport stream.

#### Key Methods

- **`async def write(self, data: Data, *, end_stream: bool = False) -> None`**: Writes data to the stream, handling backpressure.
- **`async def write_all(self, data: bytes, *, chunk_size: int = 8192) -> None`**: Writes a large bytes object to the stream in chunks and then closes it.
- **`async def flush(self) -> None`**: Waits until the stream's internal write buffer is empty.
- **`async def close(self) -> None`**: Gracefully closes the stream's write side by sending a `FIN` bit.
- **`async def abort(self, *, code: int = 0) -> None`**: Forcefully closes the stream with an error code.
- **`async def wait_closed(self) -> None`**: Waits until the stream is fully closed.

#### Properties

- `is_writable` (`bool`): `True` if the stream can be written to.

### WebTransportReceiveStream Class

Represents a unidirectional (receive-only) WebTransport stream. These are typically initiated by the remote peer and accessed via `session.incoming_streams()`.

#### Key Methods

- **`async def read(self, *, size: int = 8192) -> bytes`**: Reads up to `size` bytes from the stream. Returns `b""` on EOF.
- **`async def read_all(self, *, max_size: int | None = None) -> bytes`**: Reads the entire stream content into a single bytes object.
- **`async def readuntil(self, separator: bytes = b"\n") -> bytes`**: Reads data until a separator is found.
- **`async def readline(self) -> bytes`**: Reads one line from the stream.
- **`async def readexactly(self, n: int) -> bytes`**: Reads exactly `n` bytes.
- **`async def read_iter(self, *, chunk_size: int = 8192) -> AsyncIterator[bytes]`**: Returns an async iterator to read the stream in chunks.
- **`async def abort(self, *, code: int = 0) -> None`**: Aborts the reading side of the stream.
- **`async def wait_closed(self) -> None`**: Waits until the stream is fully closed.

#### Properties

- `is_readable` (`bool`): `True` if the stream can be read from.

### Common Stream Properties & Methods

All stream classes share these common APIs.

#### Properties

- `stream_id` (`StreamId`): The unique ID of the stream.
- `state` (`StreamState`): The current state of the stream (e.g., `OPEN`, `CLOSED`).
- `direction` (`str`): The stream's direction (`"bidirectional"`, `"send_only"`, or `"receive_only"`).
- `is_closed` (`bool`): `True` if the stream is fully closed.

#### Monitoring Methods

- **`get_summary() -> dict[str, Any]`**: Returns a structured summary of the stream for monitoring.
- **`debug_state() -> dict[str, Any]`**: Returns a detailed snapshot of the stream's internal state for debugging.
- **`diagnose_issues(...) -> list[str]`**: (`WebTransportStream` only) Reports potential issues like high error rates or latency.
- **`monitor_health(...) -> None`**: (`WebTransportStream` only) A long-running task to continuously monitor stream health.

---

## Management Classes

### StreamManager Class

Manages the lifecycle of all streams within a `WebTransportSession`, enforcing concurrency limits.

**Note on Usage**: `StreamManager` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, session: WebTransportSession, *, max_streams: int = 100, ...)`**: Initializes the stream manager.

#### Instance Methods

- **`async def create_bidirectional_stream(self) -> WebTransportStream`**: Creates a new bidirectional stream, respecting the `max_streams` limit.
- **`async def create_unidirectional_stream(self) -> WebTransportSendStream`**: Creates a new unidirectional stream.
- **`async def get_stream(self, stream_id: StreamId) -> StreamType | None`**: Retrieves a managed stream by its ID.
- **`async def get_stats(self) -> dict[str, Any]`**: Returns detailed statistics about the managed streams.
- **`async def shutdown(self) -> None`**: Closes all managed streams and stops background tasks.

### StreamPool Class

Manages a pool of reusable `WebTransportStream` objects to reduce the latency of creating new streams.

**Note on Usage**: `StreamPool` must be used as an asynchronous context manager (`async with ...`).

#### Constructor

- **`__init__(self, session: WebTransportSession, *, pool_size: int = 10, ...)`**: Initializes the stream pool.

#### Instance Methods

- **`async def get_stream(self, *, timeout: float | None = None) -> WebTransportStream`**: Gets a stream from the pool or creates a new one as a fallback.
- **`async def return_stream(self, stream: WebTransportStream) -> None`**: Returns a healthy stream to the pool for reuse.
- **`async def close_all(self) -> None`**: Closes all idle streams in the pool and shuts down the pool.

---

## Supporting Data Classes

### StreamStats Class

A dataclass holding a rich set of statistics for a single stream, including byte counts, operation timings, and error counts.

### StreamBuffer Class

An internal, deque-based buffer that manages data for asynchronous read operations.

---

## Utility Functions

These helper functions are available in the `pywebtransport.stream.utils` module.

- **`async def copy_stream_data(*, source: WebTransportReceiveStream, destination: WebTransportSendStream, chunk_size: int = 8192) -> int`**: Copies all data from a source stream to a destination stream.
- **`async def echo_stream(*, stream: WebTransportStream) -> None`**: Reads all data from a bidirectional stream and writes it back to the same stream.

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
