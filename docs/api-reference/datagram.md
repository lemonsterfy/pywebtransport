# API Reference: datagram

This document provides a reference for the `pywebtransport.datagram` subpackage, which provides abstractions for the WebTransport datagram transport layer.

---

## DatagramBroadcaster Class

A utility to send a single datagram to multiple `WebTransportSession` instances concurrently. This class implements the asynchronous context manager protocol (`async with`) to ensure proper resource management.

### Constructor

- **`def __init__(self) -> None`**: Initializes the datagram broadcaster.

### Instance Methods

- **`async def add_session(self, *, session: WebTransportSession) -> None`**: Adds a session to the broadcast list.
- **`async def broadcast(self, *, data: Data) -> int`**: Broadcasts a datagram to all registered sessions concurrently. Returns the number of successful sends.
- **`async def get_session_count(self) -> int`**: Returns the current number of active sessions in the broadcast list.
- **`async def remove_session(self, *, session: WebTransportSession) -> None`**: Removes a session from the broadcast list.
- **`async def shutdown(self) -> None`**: Clears the session list and shuts down the broadcaster.

## DatagramReliabilityLayer Class

Adds TCP-like reliability (acknowledgments and retries) over the unreliable datagram transport provided by a session. This class implements the asynchronous context manager protocol (`async with`) to manage background retry tasks.

### Constructor

- **`def __init__(self, session: WebTransportSession, *, ack_timeout: float = 2.0, max_retries: int = 5) -> None`**: Initializes the reliability layer.
  - `session`: The underlying WebTransport session.
  - `ack_timeout`: Time in seconds to wait for an ACK before retrying.
  - `max_retries`: Maximum number of retry attempts for a datagram.

### Instance Methods

- **`async def close(self) -> None`**: Gracefully closes the reliability layer, stopping background tasks and cleaning up.
- **`async def receive(self, *, timeout: float | None = None) -> bytes`**: Waits for and returns the payload of the next reliably received datagram. Raises `TimeoutError` on timeout.
- **`async def send(self, *, data: Data) -> None`**: Sends a datagram reliably. The method returns once the datagram is queued; delivery is guaranteed by background tasks.

## StructuredDatagramTransport Class

A high-level wrapper for sending and receiving structured Python objects over datagrams.

### Constructor

- **`def __init__(self, *, session: WebTransportSession, serializer: Serializer, registry: dict[int, type[Any]]) -> None`**: Initializes the structured datagram transport.
  - `session`: The underlying WebTransport session.
  - `serializer`: The serializer instance for encoding/decoding objects.
  - `registry`: A mapping from integer type IDs to Python class types.

### Properties

- `is_closed` (`bool`): `True` if the transport or underlying session is closed.

### Instance Methods

- **`async def close(self) -> None`**: Closes the structured transport and unsubscribes from session events.
- **`async def initialize(self, *, queue_size: int = 100) -> None`**: Initializes the async resources and event listeners. Must be called before use.
- **`async def receive_obj(self, *, timeout: float | None = None) -> Any`**: Receives and deserializes the next object from a datagram. Raises `TimeoutError` on timeout or `SerializationError` on parsing failure.
- **`async def send_obj(self, *, obj: Any) -> None`**: Serializes and sends a Python object as a datagram. Raises `SerializationError` if the object type is not registered.

## See Also

- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Monitor API](monitor.md)**: Monitor the health and performance of components.
- **[Serializer API](serializer.md)**: Learn about pluggable serializers for structured data.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
