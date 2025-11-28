# API Reference: stream

This document provides a reference for the `pywebtransport.stream` subpackage, which contains classes for stream communication.

---

## WebTransportStream Class

Represents a bidirectional WebTransport stream that can be both read from and written to. It inherits all methods and properties from `WebTransportReceiveStream` and `WebTransportSendStream`. This class supports asynchronous iteration to yield data chunks as they arrive.

### Properties

- `direction` (`StreamDirection`): The directionality of the stream (`BIDIRECTIONAL`).
- `is_closed` (`bool`): `True` if the stream is fully closed.
- `session` (`WebTransportSession`): The parent session object.
- `state` (`StreamState`): The current state of the stream (e.g., `OPEN`, `CLOSED`).
- `stream_id` (`int`): The unique identifier for this stream.

### Instance Methods

- **`async def close(self, *, error_code: int | None = None) -> None`**: Closes both sides of the stream. Optionally sends an application error code.
- **`async def diagnostics(self) -> StreamDiagnostics`**: Asynchronously retrieves a snapshot of the stream's diagnostic information.

## WebTransportSendStream Class

Represents the writable side of a WebTransport stream (or a unidirectional send stream).

### Properties

- `can_write` (`bool`): `True` if the stream is in a writable state.
- `direction` (`StreamDirection`): The directionality of the stream.
- `is_closed` (`bool`): `True` if the stream is fully closed.
- `session` (`WebTransportSession`): The parent session object.
- `state` (`StreamState`): The current state of the stream.
- `stream_id` (`int`): The unique identifier for this stream.

### Instance Methods

- **`async def close(self, *, error_code: int | None = None) -> None`**: Closes the sending side. If `error_code` is provided, it resets the stream; otherwise, it sends a FIN.
- **`async def diagnostics(self) -> StreamDiagnostics`**: Asynchronously retrieves a snapshot of the stream's diagnostic information.
- **`async def stop_sending(self, *, error_code: int = 0) -> None`**: Sends a `RESET_STREAM` frame to the peer to stop sending data.
- **`async def write(self, *, data: Data, end_stream: bool = False) -> None`**: Writes data to the stream.
- **`async def write_all(self, *, data: bytes, chunk_size: int = 65536) -> None`**: Writes a large bytes object in chunks.

## WebTransportReceiveStream Class

Represents the readable side of a WebTransport stream. This class supports asynchronous iteration (`async for chunk in stream`) to read data chunks.

### Properties

- `can_read` (`bool`): `True` if the stream is in a readable state.
- `direction` (`StreamDirection`): The directionality of the stream.
- `is_closed` (`bool`): `True` if the stream is fully closed.
- `session` (`WebTransportSession`): The parent session object.
- `state` (`StreamState`): The current state of the stream.
- `stream_id` (`int`): The unique identifier for this stream.

### Instance Methods

- **`async def close(self) -> None`**: Closes the receiving side (stops receiving).
- **`async def diagnostics(self) -> StreamDiagnostics`**: Asynchronously retrieves a snapshot of the stream's diagnostic information.
- **`async def read(self, *, max_bytes: int = -1) -> bytes`**: Reads up to `max_bytes` from the stream. Returns `b""` on EOF.
- **`async def read_all(self) -> bytes`**: Reads all remaining data from the stream until EOF.
- **`async def readexactly(self, *, n: int) -> bytes`**: Reads exactly `n` bytes. Raises `IncompleteReadError` if EOF is reached before `n` bytes.
- **`async def readline(self, *, limit: int = -1) -> bytes`**: Reads one line (terminated by `\n`).
- **`async def readuntil(self, *, separator: bytes, limit: int = -1) -> bytes`**: Reads data until a separator is found.
- **`async def stop_receiving(self, *, error_code: int = 0) -> None`**: Sends a `STOP_SENDING` frame to the peer.

## StructuredStream Class

A high-level wrapper for sending and receiving structured Python objects over a `WebTransportStream`. This class supports asynchronous iteration (`async for obj in stream`) to receive deserialized objects.

### Constructor

- **`def __init__(self, *, stream: WebTransportStream, serializer: Serializer, registry: dict[int, type[Any]], max_message_size: int) -> None`**: Initializes the structured stream.

### Properties

- `is_closed` (`bool`): `True` if the underlying stream is closed.
- `stream_id` (`int`): The underlying stream's ID.

### Instance Methods

- **`async def close(self) -> None`**: Closes the underlying stream.
- **`async def receive_obj(self) -> Any`**: Receives, deserializes, and returns a Python object from the stream.
- **`async def send_obj(self, *, obj: Any) -> None`**: Serializes and sends a Python object over the stream.

## StreamDiagnostics Class

A dataclass representing a snapshot of stream diagnostics.

### Attributes

- `stream_id` (`int`): The ID of the stream.
- `session_id` (`str`): The ID of the parent session.
- `direction` (`StreamDirection`): The direction of the stream.
- `state` (`StreamState`): The current state of the stream.
- `created_at` (`float`): Timestamp when the stream was created.
- `bytes_sent` (`int`): Total bytes sent.
- `bytes_received` (`int`): Total bytes received.
- `read_buffer` (`bytes`): Current content of the read buffer (snapshot).
- `read_buffer_size` (`int`): Size of the read buffer in bytes.
- `pending_read_requests` (`list[Any]`): List of pending read futures.
- `write_buffer` (`list[tuple[bytes, Any, bool]]`): List of buffered write chunks.
- `close_code` (`int | None`): The error code if the stream is closed.
- `close_reason` (`str | None`): The reason string if the stream is closed.
- `closed_at` (`float | None`): Timestamp when the stream was closed.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
