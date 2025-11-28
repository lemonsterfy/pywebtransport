# API Reference: pool

This document provides a reference for the `pywebtransport.pool` subpackage, which provides robust, reusable object pooling implementations.

---

## SessionPool Class

A robust pool for reusing and managing concurrent `WebTransportSession` objects. This class implements the asynchronous context manager protocol (`async with`) to manage the pool lifecycle.

### Constructor

- **`def __init__(self, *, client: WebTransportClient, url: URL, max_size: int) -> None`**: Initializes the session pool.
  - `client`: The client instance used to create new sessions.
  - `url`: The target WebTransport URL.
  - `max_size`: The maximum number of sessions allowed in the pool.

### Instance Methods

- **`async def acquire(self) -> WebTransportSession`**: Acquires a session from the pool. Creates a new one if necessary and limits allow.
- **`async def close(self) -> None`**: Closes the pool and disposes of all pooled sessions.
- **`def get(self) -> AsyncContextManager[WebTransportSession]`**: Returns an async context manager that acquires a session and automatically releases it back to the pool on exit.
- **`async def release(self, obj: WebTransportSession) -> None`**: Releases a session back to the pool for reuse.

## StreamPool Class

A robust pool for reusing and managing concurrent bidirectional `WebTransportStream` objects within a single session. This class implements the asynchronous context manager protocol (`async with`) to manage the pool lifecycle.

### Constructor

- **`def __init__(self, *, session: WebTransportSession, max_size: int) -> None`**: Initializes the stream pool.
  - `session`: The session used to create new bidirectional streams.
  - `max_size`: The maximum number of streams allowed in the pool.

### Instance Methods

- **`async def acquire(self) -> WebTransportStream`**: Acquires a stream from the pool. Creates a new one if necessary and limits allow.
- **`async def close(self) -> None`**: Closes the pool and disposes of all pooled streams.
- **`def get(self) -> AsyncContextManager[WebTransportStream]`**: Returns an async context manager that acquires a stream and automatically releases it back to the pool on exit.
- **`async def release(self, obj: WebTransportStream) -> None`**: Releases a stream back to the pool for reuse.

## See Also

- **[Client API](client.md)**: Learn how to create and manage client connections.
- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.
