"""Unit tests for the pywebtransport.events module."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import Event, EventEmitter, EventType
from pywebtransport.events import EventBus, create_event_bus, create_event_emitter, event_handler


@pytest.fixture
def mock_logger(mocker: MockerFixture) -> Any:
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
        "factory_method, event_type, data_key",
        [
            ("for_connection", EventType.CONNECTION_ESTABLISHED, "connection_info"),
            ("for_datagram", EventType.DATAGRAM_RECEIVED, "datagram_info"),
            ("for_session", EventType.SESSION_READY, "session_info"),
            ("for_stream", EventType.STREAM_OPENED, "stream_info"),
        ],
    )
    def test_factory_methods(self, factory_method: str, event_type: EventType, data_key: str) -> None:
        data = {"key": "value"}
        kwargs = {"event_type": event_type, data_key: data}

        method = getattr(Event, factory_method)
        event = method(**kwargs)

        assert event.type == event_type
        assert event.data == data

    def test_for_error_factory(self) -> None:
        error = ValueError("Something went wrong")

        event = Event.for_error(error=error, source="test")

        assert event.type == EventType.PROTOCOL_ERROR
        assert event.source == "test"
        assert event.data
        assert event.data["error_type"] == "ValueError"
        assert event.data["error_message"] == "Something went wrong"
        assert event.data["error_details"] == {}

    def test_for_error_factory_with_custom_dict(self) -> None:
        class CustomError(Exception):
            def to_dict(self) -> dict[str, Any]:
                return {"code": 123, "reason": "custom"}

        error = CustomError("A custom error occurred")
        event = Event.for_error(error=error)

        assert event.data
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
            "type": EventType.SESSION_READY,
            "timestamp": 12345.6789,
            "data": {"id": 1},
            "source": "test_source",
        }
        event_dict = event.to_dict()

        assert event_dict == expected_dict

    def test_to_dict_with_none_source(self) -> None:
        event = Event(type=EventType.SESSION_READY, data={"id": 1}, source=None)

        event_dict = event.to_dict()

        assert event_dict["source"] is None

    def test_repr_and_str(self) -> None:
        event = Event(type=EventType.CONNECTION_FAILED)

        assert repr(event) == "Event(type=connection_failed, id=mock-uuid-1234, timestamp=12345.6789)"
        assert str(event) == "Event(connection_failed, mock-uui)"

    def test_for_error_factory_with_non_callable_to_dict(self) -> None:
        class BadError(Exception):
            to_dict = "not a callable"

        error = BadError("Bad to_dict")
        event = Event.for_error(error=error)

        assert event.data and event.data["error_details"] == {}


class TestEventEmitter:
    @pytest.fixture
    def emitter(self) -> EventEmitter:
        return EventEmitter(max_listeners=3)

    def test_init_is_idempotent(self, emitter: EventEmitter) -> None:
        assert getattr(emitter, "_emitter_initialized", False) is True

        emitter.__init__()  # type: ignore[misc]

        assert emitter._max_listeners == 3

    @pytest.mark.asyncio
    async def test_on_and_emit(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.AsyncMock()
        emitter.on(event_type=EventType.SESSION_READY, handler=handler)

        await emitter.emit(event_type=EventType.SESSION_READY, data={"test": 1})

        handler.assert_awaited_once()
        call_arg = handler.call_args[0][0]
        assert isinstance(call_arg, Event)
        assert call_arg.type == EventType.SESSION_READY
        assert call_arg.data == {"test": 1}

    @pytest.mark.asyncio
    async def test_emit_with_sync_handler(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.Mock()
        emitter.on(event_type=EventType.SESSION_READY, handler=handler)

        await emitter.emit(event_type=EventType.SESSION_READY)

        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_once(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.AsyncMock()
        emitter.once(event_type=EventType.STREAM_OPENED, handler=handler)
        assert emitter.listener_count(event_type=EventType.STREAM_OPENED) == 1

        await emitter.emit(event_type=EventType.STREAM_OPENED)
        await emitter.emit(event_type=EventType.STREAM_OPENED)

        handler.assert_awaited_once()
        assert emitter.listener_count(event_type=EventType.STREAM_OPENED) == 0

    @pytest.mark.asyncio
    async def test_off(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.Mock()
        emitter.on(event_type=EventType.CONNECTION_LOST, handler=handler)

        emitter.off(event_type=EventType.CONNECTION_LOST, handler=handler)
        await emitter.emit(event_type=EventType.CONNECTION_LOST)

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_off_removes_once_handler(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.Mock()
        emitter.once(event_type=EventType.CONNECTION_LOST, handler=handler)

        emitter.off(event_type=EventType.CONNECTION_LOST, handler=handler)
        await emitter.emit(event_type=EventType.CONNECTION_LOST)

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_off_all_handlers_for_event(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler1 = mocker.AsyncMock()
        handler2 = mocker.AsyncMock()
        emitter.on(event_type=EventType.SESSION_READY, handler=handler1)
        emitter.on(event_type=EventType.SESSION_READY, handler=handler2)
        assert emitter.listener_count(event_type=EventType.SESSION_READY) == 2

        emitter.off(event_type=EventType.SESSION_READY, handler=None)

        assert emitter.listener_count(event_type=EventType.SESSION_READY) == 0

    @pytest.mark.asyncio
    async def test_on_any_and_off_any(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        wildcard_handler = mocker.AsyncMock()
        emitter.on_any(handler=wildcard_handler)

        await emitter.emit(event_type=EventType.CONNECTION_ESTABLISHED)
        emitter.off_any(handler=wildcard_handler)
        await emitter.emit(event_type=EventType.DATAGRAM_RECEIVED)

        wildcard_handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_any_duplicate_handler(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.Mock()
        emitter.on_any(handler=handler)
        emitter.on_any(handler=handler)

        await emitter.emit(event_type="test")

        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_off_any_removes_all_wildcard_handlers(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.Mock()
        emitter.on_any(handler=handler)

        emitter.off_any(handler=None)
        await emitter.emit(event_type="test")

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_pause_and_resume(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        handler = mocker.AsyncMock()
        mock_create_task = mocker.patch("pywebtransport.events.asyncio.create_task")
        emitter.on(event_type=EventType.SESSION_READY, handler=handler)

        emitter.pause()
        await emitter.emit(event_type=EventType.SESSION_READY)
        handler.assert_not_awaited()
        task = emitter.resume()

        assert task is not None
        mock_create_task.assert_called_once()
        await mock_create_task.call_args[0][0]
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        real_task = asyncio.create_task(asyncio.sleep(10))
        cancel_spy = mocker.spy(real_task, "cancel")
        emitter._processing_task = real_task
        emitter.on(event_type=EventType.SESSION_READY, handler=mocker.Mock())

        await emitter.close()

        cancel_spy.assert_called_once()
        assert real_task.cancelled()
        assert emitter.get_stats()["total_handlers"] == 0

    @pytest.mark.asyncio
    async def test_wait_for_success(self, emitter: EventEmitter) -> None:
        wait_task = asyncio.create_task(emitter.wait_for(event_type=EventType.SESSION_READY))
        await asyncio.sleep(0.01)

        await emitter.emit(event_type=EventType.SESSION_READY, data={"id": "abc"})
        result = await asyncio.wait_for(wait_task, timeout=1)

        assert result.data == {"id": "abc"}

    @pytest.mark.asyncio
    async def test_wait_for_condition(self, emitter: EventEmitter) -> None:
        wait_task = asyncio.create_task(
            emitter.wait_for(
                event_type=EventType.STREAM_DATA_RECEIVED,
                condition=lambda e: bool(e.data and e.data["stream_id"] == 3),
            )
        )
        await asyncio.sleep(0.01)

        await emitter.emit(event_type=EventType.STREAM_DATA_RECEIVED, data={"stream_id": 1})
        assert not wait_task.done()
        await emitter.emit(event_type=EventType.STREAM_DATA_RECEIVED, data={"stream_id": 3})
        result = await asyncio.wait_for(wait_task, timeout=1)

        assert result.data
        assert result.data["stream_id"] == 3

    @pytest.mark.asyncio
    async def test_event_history_and_filtering(self, emitter: EventEmitter) -> None:
        emitter._max_history = 2

        await emitter.emit(event_type="event1")
        await emitter.emit(event_type="event2")
        await emitter.emit(event_type="event3")

        history = emitter.get_event_history()
        assert len(history) == 2
        assert history[0].type == "event2"
        assert history[1].type == "event3"
        limited_history = emitter.get_event_history(limit=1)
        assert len(limited_history) == 1
        assert limited_history[0].type == "event3"
        filtered_history = emitter.get_event_history(event_type="event2")
        assert len(filtered_history) == 1
        assert filtered_history[0].type == "event2"

    @pytest.mark.asyncio
    async def test_clear_history(self, emitter: EventEmitter) -> None:
        await emitter.emit(event_type="event1")
        assert len(emitter.get_event_history()) == 1

        emitter.clear_history()

        assert len(emitter.get_event_history()) == 0

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self, emitter: EventEmitter) -> None:
        with pytest.raises(asyncio.TimeoutError):
            await emitter.wait_for(event_type=EventType.SESSION_READY, timeout=0.01)

    @pytest.mark.asyncio
    async def test_wait_for_condition_raises_exception(self, emitter: EventEmitter) -> None:
        class ConditionError(Exception):
            pass

        def faulty_condition(event: Event) -> bool:
            raise ConditionError("Condition failed")

        wait_task = asyncio.create_task(
            emitter.wait_for(event_type=EventType.SESSION_READY, condition=faulty_condition)
        )
        await asyncio.sleep(0.01)

        await emitter.emit(event_type=EventType.SESSION_READY)

        with pytest.raises(ConditionError):
            await wait_task

    @pytest.mark.asyncio
    @pytest.mark.parametrize("queue_empty, task_running", [(True, False), (False, True)])
    async def test_resume_returns_none(
        self, emitter: EventEmitter, mocker: MockerFixture, queue_empty: bool, task_running: bool
    ) -> None:
        if not queue_empty:
            emitter._event_queue.append(Event(type="dummy"))
        if task_running:
            emitter._processing_task = mocker.Mock(done=lambda: False)

        task = emitter.resume()

        assert task is None

    @pytest.mark.asyncio
    async def test_close_with_done_task(self, emitter: EventEmitter, mocker: MockerFixture) -> None:
        mock_task = mocker.Mock(done=lambda: True)
        emitter._processing_task = mock_task

        await emitter.close()

        mock_task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_raises_exception(
        self, emitter: EventEmitter, mocker: MockerFixture, mock_logger: Any
    ) -> None:
        handler1 = mocker.AsyncMock(side_effect=ValueError("Handler failed"))
        handler2 = mocker.AsyncMock()
        emitter.on(event_type=EventType.SESSION_READY, handler=handler1)
        emitter.on(event_type=EventType.SESSION_READY, handler=handler2)

        await emitter.emit(event_type=EventType.SESSION_READY)

        mock_logger.error.assert_called_once()
        handler1.assert_awaited_once()
        handler2.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_max_listeners_warning(self, emitter: EventEmitter, mocker: MockerFixture, mock_logger: Any) -> None:
        emitter.set_max_listeners(max_listeners=1)
        emitter.on(event_type=EventType.SESSION_READY, handler=mocker.AsyncMock())

        emitter.on(event_type=EventType.SESSION_READY, handler=mocker.AsyncMock())

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_registering_same_handler_twice_warning(
        self, emitter: EventEmitter, mocker: MockerFixture, mock_logger: Any
    ) -> None:
        handler = mocker.AsyncMock()

        emitter.on(event_type=EventType.SESSION_READY, handler=handler)
        emitter.on(event_type=EventType.SESSION_READY, handler=handler)

        assert emitter.listener_count(event_type=EventType.SESSION_READY) == 1
        mock_logger.warning.assert_called_once()


class TestEventBusAndHelpers:
    @pytest.fixture(autouse=True)
    def reset_event_bus_singleton(self) -> Iterator[None]:
        EventBus._instance = None
        EventBus._lock = None
        yield
        EventBus._instance = None
        EventBus._lock = None

    def test_create_event_emitter_factory(self) -> None:
        emitter1 = create_event_emitter()
        emitter2 = create_event_emitter()

        assert isinstance(emitter1, EventEmitter)
        assert emitter1 is not emitter2

    def test_event_handler_decorator(self) -> None:
        @event_handler(event_type=EventType.CONNECTION_LOST)
        def my_handler(event: Event) -> None:
            pass

        assert getattr(my_handler, "_is_event_handler", False) is True
        assert getattr(my_handler, "_event_type", None) == EventType.CONNECTION_LOST

    @pytest.mark.asyncio
    async def test_event_bus_is_singleton(self) -> None:
        bus1 = await EventBus.get_instance()
        bus2 = await create_event_bus()

        assert bus1 is bus2
        await bus1.close()

    @pytest.mark.asyncio
    async def test_publish(self, mocker: MockerFixture) -> None:
        bus = await create_event_bus()
        handler = mocker.AsyncMock()
        bus.subscribe(event_type=EventType.SESSION_READY, handler=handler)
        event = Event(type=EventType.SESSION_READY, data={"id": 123})

        await bus.publish(event=event)

        handler.assert_awaited_once()
        call_arg = handler.call_args[0][0]
        assert call_arg.data == {"id": 123}
        await bus.close()

    @pytest.mark.asyncio
    async def test_subscribe_and_unsubscribe(self, mocker: MockerFixture) -> None:
        bus = await create_event_bus()
        handler = mocker.AsyncMock()

        sub_id = bus.subscribe(event_type=EventType.SESSION_READY, handler=handler)
        assert bus.get_subscription_count() == 1
        await bus.emit(event_type=EventType.SESSION_READY)
        handler.assert_awaited_once()
        bus.unsubscribe(subscription_id=sub_id)

        assert bus.get_subscription_count() == 0
        await bus.emit(event_type=EventType.SESSION_READY)
        handler.assert_awaited_once()
        await bus.close()

    @pytest.mark.asyncio
    async def test_subscribe_once(self, mocker: MockerFixture) -> None:
        bus = await create_event_bus()
        handler = mocker.AsyncMock()
        bus.subscribe(event_type=EventType.SESSION_READY, handler=handler, once=True)

        await bus.emit(event_type=EventType.SESSION_READY)
        await bus.emit(event_type=EventType.SESSION_READY)

        handler.assert_awaited_once()
        await bus.close()

    @pytest.mark.asyncio
    async def test_clear_all_subscriptions(self, mocker: MockerFixture) -> None:
        bus = await create_event_bus()
        bus.subscribe(event_type=EventType.SESSION_READY, handler=mocker.Mock())
        assert bus.get_subscription_count() == 1

        bus.clear_all_subscriptions()

        assert bus.get_subscription_count() == 0
        await bus.close()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_id(self, mock_logger: Any) -> None:
        bus = await create_event_bus()

        bus.unsubscribe(subscription_id="sub_fake_id")

        mock_logger.warning.assert_called_once()
        await bus.close()
