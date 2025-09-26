# API Reference: events

This module provides a powerful, asynchronous, event-driven framework.

---

## Event Class

The base data class for all events within the system.

**Note on Usage**: The constructor for `Event` requires all parameters to be passed as keyword arguments.

### Constructor

- **`def __init__(self, *, type: EventType | str, timestamp: float = <factory>, data: EventData | None = None, source: Any | None = None, event_id: str = <factory>) -> None`**: Initializes a new event object.

### Attributes

- `type` (`EventType | str`): The type of the event.
- `timestamp` (`float`): The timestamp of event creation.
- `data` (`EventData | None`): The payload associated with the event.
- `source` (`Any | None`): The object that originated the event.
- `event_id` (`str`): A unique identifier for the event instance.

### Properties

- `is_connection_event` (`bool`): `True` if the event type starts with `"connection_"`.
- `is_datagram_event` (`bool`): `True` if the event type starts with `"datagram_"`.
- `is_error_event` (`bool`): `True` if the event type name contains `"error"`.
- `is_session_event` (`bool`): `True` if the event type starts with `"session_"`.
- `is_stream_event` (`bool`): `True` if the event type starts with `"stream_"`.

### Class Methods

- **`def for_connection(cls, *, event_type: EventType, connection_info: dict[str, Any]) -> Self`**: Creates a new connection-related event.
- **`def for_datagram(cls, *, event_type: EventType, datagram_info: dict[str, Any]) -> Self`**: Creates a new datagram-related event.
- **`def for_error(cls, *, error: Exception, source: Any = None) -> Self`**: Creates a new error event from an exception.
- **`def for_session(cls, *, event_type: EventType, session_info: dict[str, Any]) -> Self`**: Creates a new session-related event.
- **`def for_stream(cls, *, event_type: EventType, stream_info: dict[str, Any]) -> Self`**: Creates a new stream-related event.

### Instance Methods

- **`def to_dict(self) -> dict[str, Any]`**: Converts the event instance to a dictionary for serialization.

## EventEmitter Class

The core class for managing and dispatching events.

### Constructor

- **`def __init__(self, *, max_listeners: int = 100) -> None`**: Initializes the event emitter.

### Instance Methods

- **`async def close(self) -> None`**: Cancels running tasks and clears all listeners.
- **`def clear_history(self) -> None`**: Clears the event history.
- **`async def emit(self, *, event_type: EventType | str, data: EventData | None = None, source: Any = None) -> None`**: Asynchronously creates and dispatches an event.
- **`def get_event_history(self, *, event_type: EventType | str | None = None, limit: int = 100) -> list[Event]`**: Retrieves the history of recorded events.
- **`def get_stats(self) -> dict[str, Any]`**: Returns a dictionary of statistics about the emitter.
- **`def listener_count(self, *, event_type: EventType | str) -> int`**: Returns the number of listeners for a given event type.
- **`def listeners(self, *, event_type: EventType | str) -> list[EventHandler]`**: Returns a list of all listeners for a given event type.
- **`def off(self, *, event_type: EventType | str, handler: EventHandler | None = None) -> None`**: Removes a handler or all handlers for an event type.
- **`def off_any(self, *, handler: EventHandler | None = None) -> None`**: Removes a specific or all wildcard handlers.
- **`def on(self, *, event_type: EventType | str, handler: EventHandler) -> None`**: Registers a persistent handler for an event type.
- **`def on_any(self, *, handler: EventHandler) -> None`**: Registers a wildcard handler that receives all events.
- **`def once(self, *, event_type: EventType | str, handler: EventHandler) -> None`**: Registers a handler that will be invoked only once.
- **`def pause(self) -> None`**: Pauses event processing, queuing any new events.
- **`def remove_all_listeners(self, *, event_type: EventType | str | None = None) -> None`**: Removes all listeners for a specific or all event types.
- **`def resume(self) -> asyncio.Task | None`**: Resumes processing and dispatches all queued events.
- **`def set_max_listeners(self, *, max_listeners: int) -> None`**: Sets the maximum number of listeners allowed per event type.
- **`async def wait_for(self, *, event_type: EventType | str, timeout: Timeout | None = None, condition: Callable[[Event], bool] | None = None) -> Event`**: Waits for a specific event that matches an optional condition.

## EventBus Class

A global, singleton event bus for decoupled, application-wide communication.

**Note on Usage**: The `EventBus` is a singleton and should be accessed via `EventBus.get_instance()` or the `create_event_bus()` factory function.

### Class Methods

- **`async def get_instance(cls) -> EventBus`**: Asynchronously retrieves the singleton instance of the bus.

### Instance Methods

- **`async def close(self) -> None`**: Closes the event bus and its underlying emitter.
- **`def clear_all_subscriptions(self) -> None`**: Clears all subscriptions on the bus.
- **`async def emit(self, *, event_type: EventType | str, data: EventData | None = None, source: Any = None) -> None`**: Creates and dispatches an event on the global bus.
- **`def get_subscription_count(self) -> int`**: Returns the number of active subscriptions.
- **`async def publish(self, *, event: Event) -> None`**: Publishes a pre-constructed `Event` object to all subscribers.
- **`def subscribe(self, *, event_type: EventType | str, handler: EventHandler, once: bool = False) -> str`**: Subscribes a handler and returns a unique subscription ID.
- **`def unsubscribe(self, *, subscription_id: str) -> None`**: Removes a subscription using its ID.

## Module-Level Functions and Decorators

### Functions

- **`async def create_event_bus() -> EventBus`**: An async factory function that returns the global `EventBus` instance.
- **`def create_event_emitter(*, max_listeners: int = 100) -> EventEmitter`**: A factory function that creates a new, standalone `EventEmitter` instance.

### Decorators

- **`@event_handler(*, event_type: EventType | str)`**: A decorator to mark a function as a handler for a specific event type.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Types API](types.md)**: Review type definitions and enumerations.
