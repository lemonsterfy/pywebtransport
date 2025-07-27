"""Unit tests for the pywebtransport.events module."""

import asyncio
from typing import Any, Dict

import pytest
from pytest_mock import MockerFixture

from pywebtransport import Event, EventEmitter, EventType
from pywebtransport.events import EventBus, create_event_bus, create_event_emitter, event_handler


@pytest.fixture
def mock_logger(mocker: MockerFixture):
    return mocker.patch("pywebtransport.events.logger")


@pytest.fixture(autouse=True)
def mock_other_dependencies(mocker: MockerFixture) -> None:
    mocker.patch("time.time", return_value=12345.6789)
    mock_uuid = mocker.MagicMock()
    mock_uuid.__str__.return_value = "mock-uuid-1234"
    mocker.patch("pywebtransport.events.uuid.uuid4", return_value=mock_uuid)


class TestEvent:
    def test_initialization_with_enum(self) -> None:
        event = Event(type=EventType.CONNECTION_ESTABLISHED)
        assert event.type == EventType.CONNECTION_ESTABLISHED
        assert event.timestamp == 12345.6789
        assert event.event_id == "mock-uuid-1234"
        assert event.data is None

    def test_post_init_str_to_enum_conversion(self) -> None:
        event = Event(type="connection_established")
        assert event.type == EventType.CONNECTION_ESTABLISHED

    def test_post_init_unknown_str_remains_str(self) -> None:
        event = Event(type="custom_event")
        assert event.type == "custom_event"

    @pytest.mark.parametrize(
        "factory_method, event_type",
        [
            ("for_connection", EventType.CONNECTION_ESTABLISHED),
            ("for_datagram", EventType.DATAGRAM_RECEIVED),
            ("for_session", EventType.SESSION_READY),
            ("for_stream", EventType.STREAM_OPENED),
        ],
    )
    def test_factory_methods(self, factory_method: str, event_type: EventType) -> None:
        data = {"key": "value"}
        method = getattr(Event, factory_method)
        event = method(event_type, data)
        assert event.type == event_type
        assert event.data == data

    def test_for_error_factory(self) -> None:
        error = ValueError("Something went wrong")
        event = Event.for_error(error, source="test")
        assert event.type == EventType.PROTOCOL_ERROR
        assert event.source == "test"
        assert event.data
        assert event.data["error_type"] == "ValueError"
        assert event.data["error_message"] == "Something went wrong"
        assert event.data["error_details"] == {}

    def test_for_error_factory_with_custom_dict(self) -> None:
        class CustomError(Exception):
            def to_dict(self) -> Dict[str, Any]:
                return {"code": 123, "reason": "custom"}

        error = CustomError("A custom error occurred")
        event = Event.for_error(error)
        assert event.data["error_details"] == {"code": 123, "reason": "custom"}

    @pytest.mark.parametrize(
        "event_type, property_name, expected",
        [
            (EventType.CONNECTION_ESTABLISHED, "is_connection_event", True),
            (EventType.SESSION_READY, "is_connection_event", False),
            (EventType.DATAGRAM_RECEIVED, "is_datagram_event", True),
            (EventType.PROTOCOL_ERROR, "is_error_event", True),
            (EventType.SESSION_CLOSED, "is_session_event", True),
            (EventType.STREAM_OPENED, "is_stream_event", True),
            ("custom_error", "is_error_event", True),
        ],
    )
    def test_boolean_properties(self, event_type: Any, property_name: str, expected: bool) -> None:
        event = Event(type=event_type)
        assert getattr(event, property_name) is expected

    def test_to_dict(self) -> None:
        event = Event(type=EventType.SESSION_READY, data={"id": 1}, source="test_source")
        expected_dict = {
            "id": "mock-uuid-1234",
            "type": "session_ready",
            "timestamp": 12345.6789,
            "data": {"id": 1},
            "source": str("test_source"),
        }
        assert event.to_dict() == expected_dict

    def test_repr_and_str(self) -> None:
        event = Event(type=EventType.CONNECTION_FAILED)
        assert repr(event) == "Event(type=connection_failed, id=mock-uuid-1234, timestamp=12345.6789)"
        assert str(event) == "Event(connection_failed, mock-uui)"


@pytest.mark.asyncio
class TestEventEmitter:
    @pytest.fixture
    def emitter(self) -> EventEmitter:
        return EventEmitter(max_listeners=3)

    async def test_on_and_emit(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.AsyncMock()
        emitter.on(EventType.SESSION_READY, handler)
        await emitter.emit(EventType.SESSION_READY, data={"test": 1})

        handler.assert_awaited_once()
        call_arg = handler.call_args[0][0]
        assert isinstance(call_arg, Event)
        assert call_arg.type == EventType.SESSION_READY
        assert call_arg.data == {"test": 1}

    async def test_once(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.AsyncMock()
        emitter.once(EventType.STREAM_OPENED, handler)
        assert emitter.listener_count(EventType.STREAM_OPENED) == 1

        await emitter.emit(EventType.STREAM_OPENED)
        await emitter.emit(EventType.STREAM_OPENED)

        handler.assert_awaited_once()
        assert emitter.listener_count(EventType.STREAM_OPENED) == 0

    async def test_off(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.Mock()
        emitter.on(EventType.CONNECTION_LOST, handler)
        emitter.off(EventType.CONNECTION_LOST, handler)
        await emitter.emit(EventType.CONNECTION_LOST)
        handler.assert_not_called()

    async def test_off_all_handlers_for_event(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler1 = mocker.AsyncMock()
        handler2 = mocker.AsyncMock()
        emitter.on(EventType.SESSION_READY, handler1)
        emitter.on(EventType.SESSION_READY, handler2)
        assert emitter.listener_count(EventType.SESSION_READY) == 2
        emitter.off(EventType.SESSION_READY, handler=None)
        assert emitter.listener_count(EventType.SESSION_READY) == 0

    async def test_on_any_and_off_any(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        wildcard_handler = mocker.AsyncMock()
        emitter.on_any(wildcard_handler)
        await emitter.emit(EventType.CONNECTION_ESTABLISHED)
        emitter.off_any(wildcard_handler)
        await emitter.emit(EventType.DATAGRAM_RECEIVED)
        wildcard_handler.assert_awaited_once()

    async def test_pause_and_resume(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.AsyncMock()
        mock_create_task = mocker.patch("pywebtransport.events.asyncio.create_task")
        emitter.on(EventType.SESSION_READY, handler)
        emitter.pause()
        await emitter.emit(EventType.SESSION_READY)
        handler.assert_not_awaited()
        emitter.resume()
        mock_create_task.assert_called_once()
        await mock_create_task.call_args[0][0]
        handler.assert_awaited_once()

    async def test_close(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        async def endless_coro() -> None:
            await asyncio.sleep(3600)

        task = asyncio.create_task(endless_coro())
        emitter._processing_task = task
        emitter.on(EventType.SESSION_READY, mocker.Mock())
        await emitter.close()
        assert task.cancelled()
        assert emitter.get_stats()["total_handlers"] == 0

    async def test_wait_for_success(self, emitter: EventEmitter) -> None:
        wait_task = asyncio.create_task(emitter.wait_for(EventType.SESSION_READY))
        await asyncio.sleep(0.01)
        await emitter.emit(EventType.SESSION_READY, data={"id": "abc"})
        result = await asyncio.wait_for(wait_task, timeout=1)
        assert result.data == {"id": "abc"}

    async def test_wait_for_timeout(self, emitter: EventEmitter) -> None:
        with pytest.raises(asyncio.TimeoutError):
            await emitter.wait_for(EventType.SESSION_READY, timeout=0.01)

    async def test_wait_for_condition(self, emitter: EventEmitter) -> None:
        wait_task = asyncio.create_task(
            emitter.wait_for(
                EventType.STREAM_DATA_RECEIVED,
                condition=lambda e: e.data and e.data["stream_id"] == 3,
            )
        )
        await asyncio.sleep(0.01)
        await emitter.emit(EventType.STREAM_DATA_RECEIVED, data={"stream_id": 1})
        assert not wait_task.done()
        await emitter.emit(EventType.STREAM_DATA_RECEIVED, data={"stream_id": 3})
        result = await asyncio.wait_for(wait_task, timeout=1)
        assert result.data["stream_id"] == 3

    async def test_wait_for_condition_raises_exception(self, emitter: EventEmitter) -> None:
        class ConditionError(Exception):
            pass

        def faulty_condition(event: Event) -> bool:
            raise ConditionError("Condition failed")

        wait_task = asyncio.create_task(emitter.wait_for(EventType.SESSION_READY, condition=faulty_condition))
        await asyncio.sleep(0.01)
        await emitter.emit(EventType.SESSION_READY)
        with pytest.raises(ConditionError):
            await wait_task

    async def test_event_history_limit_and_rollover(self, emitter: EventEmitter) -> None:
        emitter._max_history = 2
        await emitter.emit("event1")
        await emitter.emit("event2")
        await emitter.emit("event3")
        history = emitter.get_event_history()
        assert len(history) == 2
        assert history[0].type == "event2"
        assert history[1].type == "event3"
        limited_history = emitter.get_event_history(limit=1)
        assert len(limited_history) == 1
        assert limited_history[0].type == "event3"

    async def test_clear_history(self, emitter: EventEmitter) -> None:
        await emitter.emit("event1")
        assert len(emitter.get_event_history()) == 1
        emitter.clear_history()
        assert len(emitter.get_event_history()) == 0

    async def test_handler_raises_exception(self, emitter: EventEmitter, mocker: MockerFixture, mock_logger) -> None:
        handler1 = mocker.AsyncMock(side_effect=ValueError("Handler failed"))
        handler2 = mocker.AsyncMock()
        emitter.on(EventType.SESSION_READY, handler1)
        emitter.on(EventType.SESSION_READY, handler2)

        await emitter.emit(EventType.SESSION_READY)

        mock_logger.error.assert_called_once()
        handler1.assert_awaited_once()
        handler2.assert_awaited_once()

    async def test_max_listeners_warning(self, emitter: EventEmitter, mocker: MockerFixture, mock_logger) -> None:
        emitter.set_max_listeners(1)
        emitter.on(EventType.SESSION_READY, mocker.AsyncMock())
        emitter.on(EventType.SESSION_READY, mocker.AsyncMock())

        mock_logger.warning.assert_called_once()

    async def test_registering_same_handler_twice_warning(
        self, emitter: EventEmitter, mocker: MockerFixture, mock_logger
    ) -> None:
        handler = mocker.AsyncMock()
        emitter.on(EventType.SESSION_READY, handler)
        emitter.on(EventType.SESSION_READY, handler)
        assert emitter.listener_count(EventType.SESSION_READY) == 1

        mock_logger.warning.assert_called_once()


class TestEventBusAndHelpers:
    def test_create_event_emitter_factory(self) -> None:
        emitter1 = create_event_emitter()
        emitter2 = create_event_emitter()
        assert isinstance(emitter1, EventEmitter)
        assert emitter1 is not emitter2

    def test_event_handler_decorator(self) -> None:
        @event_handler(EventType.CONNECTION_LOST)
        def my_handler(event: Event) -> None:
            pass

        assert getattr(my_handler, "_is_event_handler", False) is True
        assert getattr(my_handler, "_event_type", None) == EventType.CONNECTION_LOST

    @pytest.mark.asyncio
    async def test_event_bus_is_singleton(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.events.EventBus._instance", None)
        bus1 = await EventBus.get_instance()
        bus2 = await create_event_bus()
        assert bus1 is bus2
        await bus1.close()

    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.events.EventBus._instance", None)
        bus = await create_event_bus()
        handler = mocker.AsyncMock()
        sub_id = bus.subscribe(EventType.SESSION_READY, handler)
        await bus.emit(EventType.SESSION_READY)
        handler.assert_awaited_once()
        bus.unsubscribe(sub_id)
        await bus.emit(EventType.SESSION_READY)
        handler.assert_awaited_once()
        await bus.close()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_id(self, mocker: MockerFixture, mock_logger) -> None:
        mocker.patch("pywebtransport.events.EventBus._instance", None)
        bus = await create_event_bus()
        bus.unsubscribe("sub_fake_id")

        mock_logger.warning.assert_called_once()
        await bus.close()
