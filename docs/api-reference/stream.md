# API Reference: Stream

This document provides a comprehensive reference for the `pywebtransport.stream` subpackage, which contains the classes for reliable, ordered, and multiplexed stream communication.

---

## Core Stream Classes

These are the primary classes used for stream-based communication. They are typically created via `WebTransportSession` methods.

### `WebTransportStream` Class

Represents a bidirectional WebTransport stream that can be both read from and written to.

#### Key Methods

- **`read(self, *, size: int = 8192) -> bytes`**: Reads up to `size` bytes from the stream.
- **`read_all(self, *, max_size: Optional[int] = None) -> bytes`**: Reads the entire stream content into a single bytes object.
- **`read_iter(self, *, chunk_size: int = 8192) -> AsyncIterator[bytes]`**: Returns an async iterator to read the stream in chunks.
- **`write(self, data: Data, *, end_stream: bool = False) -> None`**: Writes data to the stream.
- **`flush(self) -> None`**: Waits until the stream's write buffer is empty.
- **`close(self) -> None`**: Gracefully closes the stream's write side.
- **`abort(self, *, code: int = 0) -> None`**: Forcefully closes the stream with an error code.

#### Properties

- `stream_id` (StreamId): The unique ID of the stream.
- `state` (StreamState): The current state of the stream (e.g., `OPEN`, `HALF_CLOSED_LOCAL`, `CLOSED`).
- `direction` (str): Always `"bidirectional"`.
- `is_readable` (bool): `True` if the stream can be read from.
- `is_writable` (bool): `True` if the stream can be written to.
- `is_closed` (bool): `True` if the stream is fully closed.

### `WebTransportSendStream` Class

Represents a unidirectional (send-only) WebTransport stream.

#### Key Methods

- **`write(self, data: Data, *, end_stream: bool = False) -> None`**: Writes data to the stream.
- **`flush(self) -> None`**: Waits until the write buffer is empty.
- **`close(self) -> None`**: Gracefully closes the stream.
- **`abort(self, *, code: int = 0) -> None`**: Forcefully closes the stream.

### `WebTransportReceiveStream` Class

Represents a unidirectional (receive-only) WebTransport stream. These are typically initiated by the remote peer and accessed via `session.incoming_streams()`.

#### Key Methods

- **`read(self, *, size: int = 8192) -> bytes`**: Reads data from the stream.
- **`read_all(self, *, max_size: Optional[int] = None) -> bytes`**: Reads the entire stream content.
- **`read_iter(self, *, chunk_size: int = 8192) -> AsyncIterator[bytes]`**: Returns an async iterator for reading.
- **`abort(self, *, code: int = 0) -> None`**: Aborts the reading side of the stream.

---

## Management Classes

### `StreamManager` Class

Manages the lifecycle of all streams within a `WebTransportSession`, enforcing concurrency limits. It is an async context manager.

- **`__init__(self, session: WebTransportSession, *, max_streams: int = 100, ...)`**
- **`create_bidirectional_stream(self) -> WebTransportStream`**: Creates a new bidirectional stream, respecting the `max_streams` limit.
- **`create_unidirectional_stream(self) -> WebTransportSendStream`**: Creates a new unidirectional stream.
- **`get_stream(self, stream_id: StreamId) -> Optional[StreamType]`**: Retrieves a managed stream by its ID.
- **`get_stats(self) -> Dict[str, Any]`**: Returns detailed statistics about the managed streams.
- **`shutdown(self) -> None`**: Closes all managed streams and stops background tasks.

### `StreamPool` Class

Manages a pool of reusable `WebTransportStream` objects to reduce the latency of creating new streams. It is an async context manager.

- **`__init__(self, session: WebTransportSession, *, pool_size: int = 10, ...)`**
- **`get_stream(self, *, timeout: Optional[float] = None) -> WebTransportStream`**:
  Gets a stream from the pool. If the pool is empty, it creates a new, unpooled stream as a fallback.
- **`return_stream(self, stream: WebTransportStream) -> None`**:
  Returns a healthy stream to the pool for reuse. If the pool is full, the stream is closed.
- **`close_all(self) -> None`**: Closes all idle streams in the pool and shuts down the pool.

---

## Supporting Data Classes

- **`StreamStats`**: A dataclass holding a rich set of statistics for a single stream, including byte counts, operation timings, and error counts.
- **`StreamBuffer`**: An internal, deque-based buffer that manages data for asynchronous read operations.

---

## Stream Utility Functions

These helper functions are available in the `pywebtransport.stream.utils` module.

- **`copy_stream_data(*, source: WebTransportReceiveStream, destination: WebTransportSendStream, chunk_size: int = 8192) -> int`**:
  Copies all data from a source stream to a destination stream and returns the total bytes copied.

- **`echo_stream(*, stream: WebTransportStream) -> None`**:
  Reads all data from a bidirectional stream and writes it back to the same stream, effectively creating an echo service.

---

## See Also

- [**Session API**](session.md): The `WebTransportSession` class used to create and manage streams.
- [**Exceptions API**](exceptions.md): Exceptions like `StreamError` that may be raised.
- [**Types API**](types.md): Core type definitions like `StreamState`.
- [**Datagram API**](datagram.md): For unreliable, unordered messaging.
