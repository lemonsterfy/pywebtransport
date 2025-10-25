# API Reference: pubsub

This document provides a reference for the `pywebtransport.pubsub` subpackage, which provides a high-level Publish-Subscribe messaging pattern.

---

## PubSubManager Class

Manages the Pub/Sub lifecycle over a single `WebTransportStream`.

**Note on Usage**: `PubSubManager` must be used as an asynchronous context manager (`async with ...`).

### Constructor

- **`def __init__(self, *, stream: WebTransportStream) -> None`**: Initializes the Pub/Sub manager over a specific bidirectional stream.

### Properties

- `stats` (`PubSubStats`): A data object with detailed statistics for the manager.

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context, initializing internal resources and starting the background message processing task.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context, closing the manager and its underlying resources.
- **`async def close(self) -> None`**: Closes the manager, aborts the underlying stream, and cancels all pending operations.
- **`async def publish(self, *, topic: str, data: Data) -> None`**: Publishes a message to a specific topic.
- **`async def subscribe(self, *, topic: str, max_queue_size: int = 16, timeout: float = 10.0) -> Subscription`**: Subscribes to a topic and returns a `Subscription` object upon successful confirmation from the server.
- **`async def unsubscribe(self, *, topic: str) -> None`**: Unsubscribes from a topic, terminating all related local subscriptions.

## Subscription Class

Represents a subscription to a single topic, acting as an async iterator for messages.

**Note on Usage**: A `Subscription` object is typically obtained via `PubSubManager.subscribe()`. It must be used as an asynchronous context manager (`async with subscription: ...`) to initialize its internal message queue before iteration (`async for message in subscription:`).

### Instance Methods

- **`async def __aenter__(self) -> Self`**: Enters the async context and initializes the internal message queue.
- **`async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None`**: Exits the async context and automatically unsubscribes from the topic.
- **`async def __aiter__(self) -> AsyncIterator[bytes]`**: Returns an async iterator to receive messages from the topic.
- **`async def unsubscribe(self) -> None`**: Manually unsubscribes from the topic.

## PubSubStats Class

A dataclass holding statistics and information about a `PubSubManager`.

### Attributes

- `created_at` (`float`): Timestamp when the manager was created. `Default: <factory>`.
- `topics_subscribed` (`int`): The current number of active topic subscriptions. `Default: 0`.
- `messages_published` (`int`): Total number of messages published. `Default: 0`.
- `messages_received` (`int`): Total number of messages received across all subscriptions. `Default: 0`.
- `subscription_errors` (`int`): Total number of failed subscription attempts. `Default: 0`.

### Instance Methods

- **`def to_dict(self) -> dict[str, float | int]`**: Converts the statistics to a dictionary.

## Pub/Sub Exceptions

These exceptions are available directly from the `pywebtransport.pubsub` module.

- `PubSubError`: The base exception for all Pub/Sub related errors. Inherits from `WebTransportError`.
- `NotSubscribedError`: Raised when trying to operate on a topic without being subscribed.
- `SubscriptionFailedError`: Raised when subscribing to a topic fails (e.g., due to a server error or timeout).

## See Also

- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.
