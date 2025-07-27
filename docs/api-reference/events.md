# API Reference: Events

This document provides a comprehensive reference for the `pywebtransport.events` module, which offers a powerful, asynchronous, event-driven framework.

---

## `Event` Class

The base data class for all events within the system.

- **Constructor**: `Event(type: Union[EventType, str], timestamp: float = ..., data: Optional[EventData] = None, source: Optional[Any] = None, event_id: str = ...)`
- **Attributes**:
  - `type` (Union[EventType, str]): The type of the event.
  - `timestamp` (float): The timestamp of event creation.
  - `data` (Optional[EventData]): The payload associated with the event.
  - `source` (Optional[Any]): The object that originated the event.
  - `event_id` (str): A unique identifier for the event instance.

### Boolean Properties

These read-only properties help categorize an event instance based on its type.

- `is_connection_event` (bool): `True` if the event type starts with `"connection_"`.
- `is_datagram_event` (bool): `True` if the event type starts with `"datagram_"`.
- `is_error_event` (bool): `True` if the event type name contains `"error"`.
- `is_session_event` (bool): `True` if the event type starts with `"session_"`.
- `is_stream_event` (bool): `True` if the event type starts with `"stream_"`.

### Class Method Factories

These factory methods provide a convenient way to create specialized `Event` objects.

- `for_connection(event_type: EventType, connection_info: Dict[str, Any]) -> Event`
- `for_datagram(event_type: EventType, datagram_info: Dict[str, Any]) -> Event`
- `for_error(error: Exception, *, source: Any = None) -> Event`
- `for_session(event_type: EventType, session_info: Dict[str, Any]) -> Event`
- `for_stream(event_type: EventType, stream_info: Dict[str, Any]) -> Event`

### Instance Methods

- `to_dict() -> Dict[str, Any]`: Converts the event instance to a dictionary for serialization.

---

## `EventEmitter` Class

The core class for managing and dispatching events.

### Methods

- `on(event_type: Union[EventType, str], handler: EventHandler) -> None`: Registers a persistent handler for an event type.
- `once(event_type: Union[EventType, str], handler: EventHandler) -> None`: Registers a handler that will be invoked only once.
- `off(event_type: Union[EventType, str], handler: Optional[EventHandler] = None) -> None`: Removes a specific handler or all handlers for an event type.
- `on_any(handler: EventHandler) -> None`: Registers a wildcard handler that receives all events.
- `off_any(handler: Optional[EventHandler] = None) -> None`: Removes a specific or all wildcard handlers.
- `emit(event_type: Union[EventType, str], *, data: Optional[EventData] = None, source: Any = None) -> None`: Asynchronously creates and dispatches an event.
- `wait_for(event_type: Union[EventType, str], *, timeout: Optional[Timeout] = None, condition: Optional[Callable[[Event], bool]] = None) -> Event`: Waits for a specific event to be emitted that matches an optional condition.
- `listeners(event_type: Union[EventType, str]) -> List[EventHandler]`: Returns a list of all listeners for a given event type.
- `listener_count(event_type: Union[EventType, str]) -> int`: Returns the number of listeners for a given event type.
- `pause() -> None`: Pauses event processing, queuing any new events.
- `resume() -> Optional[asyncio.Task]`: Resumes processing and dispatches all queued events.
- `get_event_history(event_type: Optional[Union[EventType, str]] = None, limit: int = 100) -> List[Event]`: Retrieves the history of recorded events.
- `clear_history() -> None`: Clears the event history.
- `remove_all_listeners(event_type: Optional[Union[EventType, str]] = None) -> None`: Removes all listeners for a specific event or for all events.
- `set_max_listeners(max_listeners: int) -> None`: Sets the maximum number of listeners allowed per event type.
- `get_stats() -> Dict[str, Any]`: Returns a dictionary of statistics about the emitter.
- `close() -> None`: Cancels any running tasks and clears all listeners, preparing the emitter for garbage collection.

---

## `EventBus` Class

A global, singleton event bus for decoupled, application-wide communication.

- `get_instance() -> EventBus` (classmethod): Asynchronously retrieves the singleton instance of the bus.
- `publish(event: Event) -> None`: Publishes a pre-constructed `Event` object to all subscribers.
- `emit(...)`: Same signature as `EventEmitter.emit`, but publishes on the global bus.
- `subscribe(event_type: Union[EventType, str], handler: EventHandler, *, once: bool = False) -> str`: Subscribes a handler to an event type and returns a unique subscription ID.
- `unsubscribe(subscription_id: str) -> None`: Removes a subscription using its ID.
- `get_subscription_count() -> int`: Returns the number of active subscriptions.
- `clear_all_subscriptions() -> None`: Clears all subscriptions on the bus.
- `close() -> None`: Closes the event bus and its underlying emitter.

---

## Module-Level Functions & Decorators

- **`create_event_bus() -> EventBus`**: An async factory function that returns the global `EventBus` instance.
- **`create_event_emitter(max_listeners: int = 100) -> EventEmitter`**: A factory function that creates a new, standalone `EventEmitter` instance.
- **`@event_handler(event_type: Union[EventType, str])`**: A decorator to mark a function as a handler for a specific event type. This is primarily for organizational purposes and does not automatically register the handler.

---

## See Also

- [**Protocol API**](protocol.md): Protocol implementation details.
- [**Types API**](types.md): Review type definitions, including `EventType` and `EventHandler`.
- [**Exceptions API**](exceptions.md): Understand the library's error and exception hierarchy.
- [**Constants API**](constants.md): Review default values and protocol-level constants.
