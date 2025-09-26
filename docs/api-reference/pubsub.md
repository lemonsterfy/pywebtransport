# API Reference: pubsub

This document provides a reference for the `pywebtransport.pubsub` subpackage, which offers a high-level publish/subscribe messaging framework.

---

## PubSubManager Class

Manages the Pub/Sub lifecycle over a single `WebTransportSession`.

**Note on Usage**: `PubSubManager` must be used as an asynchronous context manager (`async with ...`). It lazily creates a dedicated bidirectional stream for Pub/Sub communication on first use.

### Constructor

- **`def __init__(self, *, session: WebTransportSession) -> None`**: Initializes the Pub/Sub manager for a given session.

### Instance Methods

- **`async def publish(self, *, topic: str, data: Data) -> None`**: Publishes a message to a specific topic.
- **`async def subscribe(self, *, topic: str, max_queue_size: int = 16, timeout: float = 10.0) -> Subscription`**: Subscribes to a topic and returns a `Subscription` object.
- **`async def unsubscribe(self, *, topic: str) -> None`**: Unsubscribes from a topic, terminating all related local subscriptions.
- **`async def close(self) -> None`**: Closes the manager, aborts the underlying stream, and cancels all pending operations.

### Properties

- `stats` (`PubSubStats`): A data object with detailed statistics for the manager.

## Subscription Class

Represents a subscription to a single topic, acting as an async iterator for messages.

**Note on Usage**: A `Subscription` object must be used as an asynchronous context manager (`async with ...`) to initialize its internal message queue. It can then be iterated over using `async for`.

### Instance Methods

- **`async def unsubscribe(self) -> None`**: Unsubscribes from the topic. This is equivalent to calling `manager.unsubscribe()`.

## PubSubStats Class

A dataclass holding statistics and information about a `PubSubManager`.

### Attributes

- `created_at` (`float`): Timestamp when the manager was created.
- `topics_subscribed` (`int`): The current number of active topic subscriptions. `Default: 0`.
- `messages_published` (`int`): Total number of messages published. `Default: 0`.
- `messages_received` (`int`): Total number of messages received across all subscriptions. `Default: 0`.
- `subscription_errors` (`int`): Total number of failed subscription attempts. `Default: 0`.

## Pub/Sub Exceptions

These exceptions are available in the `pywebtransport.pubsub.exceptions` module.

- `PubSubError`: The base exception for all Pub/Sub related errors. Inherits from `WebTransportError`.
- `NotSubscribedError`: Raised when trying to operate on a topic without being subscribed.
- `SubscriptionFailedError`: Raised when subscribing to a topic fails (e.g., due to a server error or timeout).

## See Also

- **[Session API](session.md)**: Understand the `WebTransportSession` which this manager is built upon.
- **[Stream API](stream.md)**: Learn about the underlying stream abstractions.
- **[Exceptions API](exceptions.md)**: Understand the library's complete error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values used by the Pub/Sub manager.
