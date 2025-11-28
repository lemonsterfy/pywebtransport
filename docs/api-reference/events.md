# API Reference: events

This module provides the core components for the library's event-driven architecture.

---

## Event Class

A versatile base class for all system events.

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

An emitter for handling and dispatching events asynchronously.

### Constructor

- **`def __init__(self, *, max_listeners: int = 100) -> None`**: Initializes the event emitter.

### Instance Methods

- **`async def close(self) -> None`**: Cancels running tasks and clears all listeners.
- **`def clear_history(self) -> None`**: Clears the event history.
- **`async def emit(self, *, event_type: EventType | str, data: EventData | None = None, source: Any = None) -> None`**: Asynchronously creates and dispatches an event.
- **`def emit_nowait(self, *, event_type: EventType | str, data: EventData | None = None, source: Any = None) -> None`**: Schedules an event emission synchronously without blocking (fire-and-forget).
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
- **`def resume(self) -> asyncio.Task[None] | None`**: Resumes processing and dispatches all queued events.
- **`def set_max_listeners(self, *, max_listeners: int) -> None`**: Sets the maximum number of listeners allowed per event type.
- **`async def wait_for(self, *, event_type: EventType | str, timeout: Timeout | None = None, condition: Callable[[Event], bool] | None = None) -> Event`**: Waits for a specific event that matches an optional condition.

## Type Aliases

- `EventHandler` (`Callable[[Event], Awaitable[None] | None]`): A callable that handles an `Event`. Can be a coroutine or a regular function.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Types API](types.md)**: Review type definitions and enumerations.
