# API Reference: pool

This document provides a reference for the `pywebtransport.pool` subpackage, which provides robust, reusable object pooling implementations.

---

## ConnectionPool Class

A robust pool for reusing and managing concurrent `WebTransportConnection` objects, typically used by clients connecting to the same endpoint.

**Note on Usage**: `ConnectionPool` must be used as an asynchronous context manager (`async with pool: ...`) to ensure proper resource management. Individual connections are acquired using `pool.get()` within another `async with` block.

### Constructor

- **`def __init__(self, *, config: ClientConfig, host: str, port: int, path: str = "/", max_size: int) -> None`**: Initializes the connection pool.
  - `config` (`ClientConfig`): The client configuration to use when creating new connections.
  - `host` (`str`): The target server host.
  - `port` (`int`): The target server port.
  - `path` (`str`): The default URL path for new connections. `Default: "/"`.
  - `max_size` (`int`): The maximum number of connections allowed in the pool (both idle and active).

### Instance Methods

- **`async def acquire(self) -> WebTransportConnection`**: Acquires a connection from the pool. If the pool has an idle connection available, it's returned. Otherwise, if the pool is not full, a new connection is created using the provided configuration. If the pool is full, this method waits until a connection is released.
- **`async def close(self) -> None`**: Closes the pool and gracefully closes all idle connections currently held within it. Does not affect connections currently acquired from the pool.
- **`def get(self) -> AsyncContextManager[WebTransportConnection]`**: Returns an asynchronous context manager. Using `async with pool.get() as conn:` acquires a connection and automatically releases it back to the pool upon exiting the block.
- **`async def release(self, conn: WebTransportConnection) -> None`**: Releases a previously acquired connection back to the pool, making it available for reuse.

## SessionPool Class

A robust pool for reusing and managing concurrent `WebTransportSession` objects, typically used by clients maintaining multiple logical sessions to the same URL.

**Note on Usage**: `SessionPool` must be used as an asynchronous context manager (`async with pool: ...`). Individual sessions are acquired using `pool.get()` within another `async with` block.

### Constructor

- **`def __init__(self, *, client: WebTransportClient, url: URL, max_size: int) -> None`**: Initializes the session pool.
  - `client` (`WebTransportClient`): The client instance used to create new sessions.
  - `url` (`URL`): The target WebTransport URL for new sessions.
  - `max_size` (`int`): The maximum number of sessions allowed in the pool (both idle and active).

### Instance Methods

- **`async def acquire(self) -> WebTransportSession`**: Acquires a session from the pool. If the pool has an idle session available, it's returned. Otherwise, if the pool is not full, a new session is created by connecting to the specified URL. If the pool is full, this method waits until a session is released.
- **`async def close(self) -> None`**: Closes the pool and gracefully closes all idle sessions currently held within it. Does not affect sessions currently acquired from the pool.
- **`def get(self) -> AsyncContextManager[WebTransportSession]`**: Returns an asynchronous context manager. Using `async with pool.get() as session:` acquires a session and automatically releases it back to the pool upon exiting the block.
- **`async def release(self, session: WebTransportSession) -> None`**: Releases a previously acquired session back to the pool, making it available for reuse.

## StreamPool Class

A robust pool for reusing and managing concurrent bidirectional `WebTransportStream` objects within a single session or connection context.

**Note on Usage**: `StreamPool` must be used as an asynchronous context manager (`async with pool: ...`). Individual streams are acquired using `pool.get()` within another `async with` block.

### Constructor

- **`def __init__(self, *, stream_manager: StreamManager, max_size: int) -> None`**: Initializes the stream pool.
  - `stream_manager` (`StreamManager`): The manager responsible for creating new streams (e.g., associated with a `WebTransportSession`).
  - `max_size` (`int`): The maximum number of streams allowed in the pool (both idle and active).

### Instance Methods

- **`async def acquire(self) -> WebTransportStream`**: Acquires a stream from the pool. If the pool has an idle stream available, it's returned. Otherwise, if the pool is not full, a new bidirectional stream is created using the provided `stream_manager`. If the pool is full, this method waits until a stream is released.
- **`async def close(self) -> None`**: Closes the pool and gracefully closes all idle streams currently held within it. Does not affect streams currently acquired from the pool.
- **`def get(self) -> AsyncContextManager[WebTransportStream]`**: Returns an asynchronous context manager. Using `async with pool.get() as stream:` acquires a stream and automatically releases it back to the pool upon exiting the block.
- **`async def release(self, stream: WebTransportStream) -> None`**: Releases a previously acquired stream back to the pool, making it available for reuse.

## See Also

- **[Client API](client.md)**: Learn how to create and manage client connections.
- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.
