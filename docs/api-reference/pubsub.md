# API Reference: pubsub

This document provides a reference for the `pywebtransport.pubsub` subpackage, which provides a high-level Publish-Subscribe messaging pattern.

---

## PubSubManager Class

Manages the Pub/Sub lifecycle over a single `WebTransportStream`. This class implements the asynchronous context manager protocol (`async with`) to manage background message processing.

### Constructor

- **`def __init__(self, *, stream: WebTransportStream, max_queue_size: int) -> None`**: Initializes the Pub/Sub manager.
  - `stream`: The bidirectional stream used for Pub/Sub control and data messages.
  - `max_queue_size`: The default maximum size for subscription message queues.

### Properties

- `stats` (`PubSubStats`): A data object with detailed statistics for the manager.

### Instance Methods

- **`async def close(self) -> None`**: Closes the manager, aborts the underlying stream, and cancels all pending operations.
- **`async def publish(self, *, topic: str, data: Data) -> None`**: Publishes a message to a specific topic.
- **`async def subscribe(self, *, topic: str, timeout: float = 10.0, max_queue_size: int | None = None) -> Subscription`**: Subscribes to a topic and returns a `Subscription` object upon successful confirmation. Raises `SubscriptionFailedError` or `TimeoutError` on failure.
- **`async def unsubscribe(self, *, topic: str) -> None`**: Unsubscribes from a topic, terminating all related local subscriptions.

## Subscription Class

Represents a subscription to a single topic. This class implements the asynchronous context manager protocol (`async with`) to manage its message queue lifecycle and supports asynchronous iteration (`async for message in subscription`) to receive messages.

### Constructor

- **`def __init__(self, *, topic: str, manager: PubSubManager, max_queue_size: int) -> None`**: Initializes the Subscription.

### Instance Methods

- **`async def unsubscribe(self) -> None`**: Manually unsubscribes from the topic.

## PubSubStats Class

A dataclass holding statistics and information about a `PubSubManager`.

### Attributes

- `created_at` (`float`): Timestamp when the manager was created.
- `topics_subscribed` (`int`): The current number of active topic subscriptions.
- `messages_published` (`int`): Total number of messages published.
- `messages_received` (`int`): Total number of messages received across all subscriptions.
- `subscription_errors` (`int`): Total number of failed subscription attempts.

### Instance Methods

- **`def to_dict(self) -> dict[str, float | int]`**: Converts the statistics to a dictionary.

## Pub/Sub Exceptions

These exceptions are available directly from the `pywebtransport.pubsub` module.

- `PubSubError`: The base exception for all Pub/Sub related errors. Inherits from `WebTransportError`.
- `NotSubscribedError`: Raised when trying to operate on a topic without being subscribed.
- `SubscriptionFailedError`: Raised when subscribing to a topic fails.

## See Also

- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
- **[Stream API](stream.md)**: Read from and write to WebTransport streams.
