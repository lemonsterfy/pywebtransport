"""
Asynchronous Event System.
"""

import asyncio
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple, TypeVar, Union

from .types import EventData, EventHandler, EventType, Timeout
from .utils import get_logger, get_timestamp

__all__ = [
    "Event",
    "EventBus",
    "EventEmitter",
    "create_event_bus",
    "create_event_emitter",
    "event_handler",
]

logger = get_logger("events")
F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class Event:
    """A versatile base class for all system events."""

    type: Union[EventType, str]
    timestamp: float = field(default_factory=get_timestamp)
    data: Optional[EventData] = None
    source: Optional[Any] = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        """Handle string-based event types after initialization."""
        if isinstance(self.type, str):
            try:
                self.type = EventType(self.type)
            except ValueError:
                pass

    @classmethod
    def for_connection(cls, event_type: EventType, connection_info: Dict[str, Any]) -> "Event":
        """Factory method to create a new connection event."""
        return cls(type=event_type, data=connection_info)

    @classmethod
    def for_datagram(cls, event_type: EventType, datagram_info: Dict[str, Any]) -> "Event":
        """Factory method to create a new datagram event."""
        return cls(type=event_type, data=datagram_info)

    @classmethod
    def for_error(cls, error: Exception, *, source: Any = None) -> "Event":
        """Factory method to create a new error event from an exception."""
        to_dict_method: Callable[[], Dict[str, Any]] = getattr(error, "to_dict", lambda: {})
        details = to_dict_method() if callable(to_dict_method) else {}
        return cls(
            type=EventType.PROTOCOL_ERROR,
            data={"error_type": type(error).__name__, "error_message": str(error), "error_details": details},
            source=source,
        )

    @classmethod
    def for_session(cls, event_type: EventType, session_info: Dict[str, Any]) -> "Event":
        """Factory method to create a new session event."""
        return cls(type=event_type, data=session_info)

    @classmethod
    def for_stream(cls, event_type: EventType, stream_info: Dict[str, Any]) -> "Event":
        """Factory method to create a new stream event."""
        return cls(type=event_type, data=stream_info)

    @property
    def is_connection_event(self) -> bool:
        """Check if this event is connection-related."""
        return self._get_event_value().startswith("connection_")

    @property
    def is_datagram_event(self) -> bool:
        """Check if this event is datagram-related."""
        return self._get_event_value().startswith("datagram_")

    @property
    def is_error_event(self) -> bool:
        """Check if this event is error-related."""
        return "error" in self._get_event_value().lower()

    @property
    def is_session_event(self) -> bool:
        """Check if this event is session-related."""
        return self._get_event_value().startswith("session_")

    @property
    def is_stream_event(self) -> bool:
        """Check if this event is stream-related."""
        return self._get_event_value().startswith("stream_")

    def to_dict(self) -> Dict[str, Any]:
        """Convert the event to a dictionary."""
        return {
            "id": self.event_id,
            "type": self._get_event_value(),
            "timestamp": self.timestamp,
            "data": self.data,
            "source": str(self.source) if self.source else None,
        }

    def _get_event_value(self) -> str:
        """Get the string value from an EventType enum or a string."""
        return self.type.value if isinstance(self.type, EventType) else self.type

    def __repr__(self) -> str:
        """Return a detailed string representation of the event."""
        return f"Event(type={self._get_event_value()}, id={self.event_id}, timestamp={self.timestamp})"

    def __str__(self) -> str:
        """Return a simple string representation of the event."""
        return f"Event({self._get_event_value()}, {self.event_id[:8]})"


class EventEmitter:
    """An emitter for handling and dispatching events asynchronously."""

    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize the event emitter."""
        if getattr(self, "_emitter_initialized", False):
            return
        self._handlers: Dict[Union[EventType, str], List[EventHandler]] = defaultdict(list)
        self._once_handlers: Dict[Union[EventType, str], List[EventHandler]] = defaultdict(list)
        self._max_listeners = kwargs.get("max_listeners", 100)
        self._event_history: List[Event] = []
        self._max_history = 1000
        self._wildcard_handlers: List[EventHandler] = []
        self._paused = False
        self._event_queue: Deque[Event] = deque()
        self._processing_task: Optional[asyncio.Task] = None
        self._emitter_initialized = True

    async def close(self) -> None:
        """Cancel running event processing tasks and clear all listeners."""
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass
        self.remove_all_listeners()
        logger.debug("EventEmitter closed and listeners cleared.")

    async def emit(
        self,
        event_type: Union[EventType, str],
        *,
        data: Optional[EventData] = None,
        source: Any = None,
    ) -> None:
        """Emit an event to all corresponding listeners."""
        event = Event(type=event_type, data=data, source=source)
        self._add_to_history(event)
        if self._paused:
            self._event_queue.append(event)
            return
        await self._process_event(event)

    async def wait_for(
        self,
        event_type: Union[EventType, str],
        *,
        timeout: Optional[Timeout] = None,
        condition: Optional[Callable[[Event], bool]] = None,
    ) -> Event:
        """Wait for a specific event to be emitted."""
        future: asyncio.Future[Event] = asyncio.Future()

        async def handler(event: Event) -> None:
            try:
                if condition is None or condition(event):
                    if not future.done():
                        future.set_result(event)
            except Exception as e:
                if not future.done():
                    future.set_exception(e)

        self.on(event_type, handler)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.off(event_type, handler)

    def on(self, event_type: Union[EventType, str], handler: EventHandler) -> None:
        """Register a persistent event handler."""
        handlers = self._handlers[event_type]
        if len(handlers) >= self._max_listeners:
            logger.warning(f"Maximum listeners ({self._max_listeners}) exceeded for event {event_type}")
        if handler not in handlers:
            handlers.append(handler)
            logger.debug(f"Registered handler for event {event_type}")
        else:
            logger.warning(f"Handler already registered for event {event_type}")

    def once(self, event_type: Union[EventType, str], handler: EventHandler) -> None:
        """Register a one-time event handler."""
        once_handlers = self._once_handlers[event_type]
        if handler not in once_handlers:
            once_handlers.append(handler)
            logger.debug(f"Registered once handler for event {event_type}")

    def off(self, event_type: Union[EventType, str], handler: Optional[EventHandler] = None) -> None:
        """Unregister a specific event handler or all handlers for an event."""
        if handler is None:
            self._handlers[event_type].clear()
            self._once_handlers[event_type].clear()
            logger.debug(f"Removed all handlers for event {event_type}")
        else:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)
                logger.debug(f"Removed handler for event {event_type}")
            if handler in self._once_handlers[event_type]:
                self._once_handlers[event_type].remove(handler)
                logger.debug(f"Removed once handler for event {event_type}")

    def on_any(self, handler: EventHandler) -> None:
        """Register a wildcard handler for all events."""
        if handler not in self._wildcard_handlers:
            self._wildcard_handlers.append(handler)
            logger.debug("Registered wildcard handler")

    def off_any(self, handler: Optional[EventHandler] = None) -> None:
        """Unregister a specific wildcard handler or all wildcard handlers."""
        if handler is None:
            self._wildcard_handlers.clear()
            logger.debug("Removed all wildcard handlers")
        elif handler in self._wildcard_handlers:
            self._wildcard_handlers.remove(handler)
            logger.debug("Removed wildcard handler")

    def remove_all_listeners(self, event_type: Optional[Union[EventType, str]] = None) -> None:
        """Remove all listeners for a specific event or for all events."""
        if event_type is None:
            self._handlers.clear()
            self._once_handlers.clear()
            self._wildcard_handlers.clear()
            logger.debug("Removed all event listeners")
        else:
            self._handlers[event_type].clear()
            self._once_handlers[event_type].clear()
            logger.debug(f"Removed all listeners for event {event_type}")

    def pause(self) -> None:
        """Pause event processing and queue subsequent events."""
        self._paused = True
        logger.debug("Event processing paused")

    def resume(self) -> Optional[asyncio.Task]:
        """Resume event processing and handle all queued events."""
        self._paused = False
        logger.debug("Event processing resumed")
        if self._event_queue and (self._processing_task is None or self._processing_task.done()):
            self._processing_task = asyncio.create_task(self._process_queued_events())
            return self._processing_task
        return None

    def listeners(self, event_type: Union[EventType, str]) -> List[EventHandler]:
        """Get all listeners for a specific event type."""
        return self._handlers[event_type][:] + self._once_handlers[event_type][:]

    def listener_count(self, event_type: Union[EventType, str]) -> int:
        """Get the number of listeners for a specific event type."""
        return len(self.listeners(event_type))

    def get_event_history(self, event_type: Optional[Union[EventType, str]] = None, limit: int = 100) -> List[Event]:
        """Get the recorded history of events."""
        if event_type is None:
            return self._event_history[-limit:]

        event_value = event_type.value if isinstance(event_type, EventType) else event_type
        filtered_events = [event for event in self._event_history if event._get_event_value() == event_value]
        return filtered_events[-limit:]

    def clear_history(self) -> None:
        """Clear the entire event history."""
        self._event_history.clear()
        logger.debug("Event history cleared")

    def set_max_listeners(self, max_listeners: int) -> None:
        """Set the maximum number of listeners per event."""
        self._max_listeners = max_listeners

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the event emitter."""
        total_handlers = sum(len(handlers) for handlers in self._handlers.values())
        total_once_handlers = sum(len(handlers) for handlers in self._once_handlers.values())
        return {
            "total_handlers": total_handlers,
            "total_once_handlers": total_once_handlers,
            "wildcard_handlers": len(self._wildcard_handlers),
            "event_types": len(self._handlers),
            "history_size": len(self._event_history),
            "queued_events": len(self._event_queue),
            "paused": self._paused,
        }

    def _add_to_history(self, event: Event) -> None:
        """Add an event to the history buffer."""
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)

    async def _process_event(self, event: Event) -> None:
        """Process a single event by invoking all relevant handlers."""
        handlers_to_call: List[EventHandler] = self._handlers[event.type][:]
        once_handlers_to_call: List[EventHandler] = self._once_handlers[event.type][:]
        if once_handlers_to_call:
            self._once_handlers[event.type].clear()
        all_handlers = handlers_to_call + once_handlers_to_call + self._wildcard_handlers
        if not all_handlers:
            return
        logger.debug(f"Emitting event {event.type} to {len(all_handlers)} handlers")
        for handler in all_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Error in handler for event {event.type}: {e}", exc_info=e)

    async def _process_queued_events(self) -> None:
        """Process all events in the queue until it is empty."""
        while self._event_queue and not self._paused:
            event = self._event_queue.popleft()
            await self._process_event(event)


class EventBus:
    """A global, singleton event bus for cross-component communication."""

    _instance: Optional["EventBus"] = None
    _lock = asyncio.Lock()

    def __init__(self) -> None:
        """Initialize the event bus."""
        self._emitter = EventEmitter(max_listeners=1000)
        self._subscriptions: Dict[str, Tuple[Union[EventType, str], EventHandler]] = {}
        self._subscription_counter = 0

    @classmethod
    async def get_instance(cls) -> "EventBus":
        """Get the singleton instance of the EventBus."""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def close(self) -> None:
        """Close the event bus and its underlying emitter."""
        await self._emitter.close()
        self.clear_all_subscriptions()
        logger.debug("Event bus closed.")

    async def publish(self, event: Event) -> None:
        """Publish a pre-constructed event to all subscribers."""
        await self._emitter.emit(event_type=event.type, data=event.data, source=event.source)

    async def emit(
        self,
        event_type: Union[EventType, str],
        *,
        data: Optional[EventData] = None,
        source: Any = None,
    ) -> None:
        """Create and emit an event on the bus."""
        await self._emitter.emit(event_type, data=data, source=source)

    def subscribe(self, event_type: Union[EventType, str], handler: EventHandler, *, once: bool = False) -> str:
        """Subscribe to an event, returning a unique subscription ID."""
        subscription_id = f"sub_{self._subscription_counter}"
        self._subscription_counter += 1
        self._subscriptions[subscription_id] = (event_type, handler)
        if once:
            self._emitter.once(event_type, handler)
        else:
            self._emitter.on(event_type, handler)
        logger.debug(f"Created subscription {subscription_id} for event {event_type}")
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from an event using its subscription ID."""
        if subscription_id not in self._subscriptions:
            logger.warning(f"Subscription {subscription_id} not found")
            return
        event_type, handler = self._subscriptions.pop(subscription_id)
        self._emitter.off(event_type, handler)
        event_value = event_type.value if isinstance(event_type, EventType) else event_type
        logger.debug(f"Removed subscription {subscription_id} for event {event_value}")

    def get_subscription_count(self) -> int:
        """Get the number of active subscriptions."""
        return len(self._subscriptions)

    def clear_all_subscriptions(self) -> None:
        """Clear all subscriptions from the bus."""
        self._subscriptions.clear()
        self._emitter.remove_all_listeners()
        logger.debug("Cleared all event bus subscriptions")


async def create_event_bus() -> EventBus:
    """Create or get the global event bus instance."""
    return await EventBus.get_instance()


def create_event_emitter(max_listeners: int = 100) -> EventEmitter:
    """Create a new, standalone event emitter."""
    return EventEmitter(max_listeners=max_listeners)


def event_handler(event_type: Union[EventType, str]) -> Callable[[F], F]:
    """Decorate a function as a handler for a specific event type."""

    def decorator(func: F) -> F:
        setattr(func, "_event_type", event_type)
        setattr(func, "_is_event_handler", True)
        return func

    return decorator
