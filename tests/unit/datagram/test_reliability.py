"""Unit tests for the pywebtransport.datagram.reliability module."""

import asyncio
import logging
import struct
from collections import deque
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, NoReturn

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import DatagramError, Event, EventType, TimeoutError, WebTransportDatagramTransport
from pywebtransport.datagram import DatagramReliabilityLayer
from pywebtransport.datagram.reliability import _ReliableDatagram

TEST_START_SEQ = 100


class TestDatagramReliabilityLayer:
    @pytest.fixture
    def mock_transport(self, mocker: MockerFixture) -> Any:
        transport = mocker.create_autospec(WebTransportDatagramTransport, instance=True, spec_set=True)
        transport.on = mocker.MagicMock()
        transport.off = mocker.MagicMock()
        transport._send_framed_data = mocker.AsyncMock()
        transport.is_closed = False
        return transport

    @pytest.fixture
    async def reliability_layer(self, mock_transport: Any) -> AsyncGenerator[DatagramReliabilityLayer, None]:
        layer = DatagramReliabilityLayer(datagram_transport=mock_transport, ack_timeout=0.1, max_retries=2)
        async with layer as activated_layer:
            yield activated_layer

    def test_initialization(self, mock_transport: Any) -> None:
        reliability_layer = DatagramReliabilityLayer(datagram_transport=mock_transport, ack_timeout=0.1, max_retries=2)

        assert isinstance(reliability_layer._transport(), WebTransportDatagramTransport)
        assert reliability_layer._ack_timeout == 0.1
        assert reliability_layer._max_retries == 2
        assert not reliability_layer._closed
        assert reliability_layer._send_sequence == 0
        assert reliability_layer._receive_sequence == 0
        assert isinstance(reliability_layer._pending_acks, dict)
        assert isinstance(reliability_layer._received_sequences, deque)
        assert reliability_layer._incoming_queue is None
        assert reliability_layer._retry_task is None
        mock_transport.on.assert_not_called()

    def test_create_factory_method(self, mock_transport: Any) -> None:
        layer = DatagramReliabilityLayer.create(datagram_transport=mock_transport, ack_timeout=5.0, max_retries=10)

        assert isinstance(layer, DatagramReliabilityLayer)
        assert layer._ack_timeout == 5.0
        assert layer._max_retries == 10
        mock_transport.on.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_manager(self, mocker: MockerFixture, mock_transport: Any) -> None:
        reliability_layer = DatagramReliabilityLayer(datagram_transport=mock_transport, ack_timeout=0.1, max_retries=2)
        mock_start = mocker.patch.object(reliability_layer, "_start_background_tasks", autospec=True)
        mock_close = mocker.patch.object(reliability_layer, "close", new_callable=mocker.AsyncMock)

        async with reliability_layer as layer_instance:
            assert layer_instance is reliability_layer
            mock_start.assert_called_once()
            mock_transport.on.assert_called_once_with(
                event_type=EventType.DATAGRAM_RECEIVED, handler=reliability_layer._on_datagram_received
            )

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager_with_exception(self, mocker: MockerFixture, mock_transport: Any) -> None:
        reliability_layer = DatagramReliabilityLayer(datagram_transport=mock_transport)
        mock_close = mocker.patch.object(reliability_layer, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(ValueError, match="test exception"):
            async with reliability_layer:
                raise ValueError("test exception")

        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close(self, mock_transport: Any, reliability_layer: DatagramReliabilityLayer) -> None:
        async def dummy_task_coro() -> None:
            await asyncio.sleep(30)

        background_task = asyncio.create_task(dummy_task_coro())
        reliability_layer._retry_task = background_task
        reliability_layer._pending_acks[1] = _ReliableDatagram(data=b"test")
        reliability_layer._received_sequences.append(1)

        await reliability_layer.close()

        assert reliability_layer._closed
        mock_transport.off.assert_called_once_with(
            event_type=EventType.DATAGRAM_RECEIVED, handler=reliability_layer._on_datagram_received
        )
        assert background_task.cancelled()
        assert not reliability_layer._pending_acks
        assert not reliability_layer._received_sequences

        mock_transport.off.reset_mock()
        await reliability_layer.close()
        mock_transport.off.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_when_transport_is_gone(
        self, reliability_layer: DatagramReliabilityLayer, mocker: MockerFixture
    ) -> None:
        reliability_layer._transport = mocker.MagicMock(return_value=None)

        await reliability_layer.close()

        assert reliability_layer._closed

    @pytest.mark.asyncio
    async def test_send_successful(self, mock_transport: Any, reliability_layer: DatagramReliabilityLayer) -> None:
        test_data = b"hello world"

        await reliability_layer.send(data=test_data)

        expected_payload = struct.pack("!I", 0) + test_data
        mock_transport._send_framed_data.assert_awaited_once_with(message_type="DATA", payload=expected_payload)
        assert reliability_layer._send_sequence == 1
        assert 0 in reliability_layer._pending_acks
        datagram = reliability_layer._pending_acks[0]
        assert isinstance(datagram, _ReliableDatagram)
        assert datagram.data == expected_payload
        assert datagram.sequence == 0

    @pytest.mark.asyncio
    async def test_receive_successful(self, reliability_layer: DatagramReliabilityLayer) -> None:
        test_data = b"message received"
        assert reliability_layer._incoming_queue is not None
        await reliability_layer._incoming_queue.put(test_data)

        received_data = await reliability_layer.receive()

        assert received_data == test_data

    @pytest.mark.asyncio
    async def test_send_on_closed_layer_raises_error(self, reliability_layer: DatagramReliabilityLayer) -> None:
        await reliability_layer.close()

        with pytest.raises(DatagramError, match="layer or underlying transport is closed"):
            await reliability_layer.send(data=b"test")

    @pytest.mark.asyncio
    async def test_send_before_activation_raises_error(self, mock_transport: Any) -> None:
        layer = DatagramReliabilityLayer(datagram_transport=mock_transport)

        with pytest.raises(DatagramError, match="has not been activated"):
            await layer.send(data=b"test")

    @pytest.mark.asyncio
    async def test_receive_timeout(self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer) -> None:
        async def mock_wait_for(coro: Coroutine[Any, Any, None], timeout: float) -> NoReturn:
            coro.close()
            raise asyncio.TimeoutError

        mocker.patch("asyncio.wait_for", side_effect=mock_wait_for)

        with pytest.raises(TimeoutError, match="Receive timeout after 5s"):
            await reliability_layer.receive(timeout=5)

    @pytest.mark.asyncio
    async def test_receive_on_closed_layer_raises_error(self, reliability_layer: DatagramReliabilityLayer) -> None:
        await reliability_layer.close()

        with pytest.raises(DatagramError, match="Reliability layer is closed"):
            await reliability_layer.receive()

    @pytest.mark.asyncio
    async def test_receive_before_activation_raises_error(self, mock_transport: Any) -> None:
        layer = DatagramReliabilityLayer(datagram_transport=mock_transport)

        with pytest.raises(DatagramError, match="has not been activated"):
            await layer.receive()

    def test_get_transport(self, mock_transport: Any, reliability_layer: DatagramReliabilityLayer) -> None:
        assert reliability_layer._get_transport() is mock_transport

    @pytest.mark.parametrize(
        "is_layer_closed, is_transport_present, is_transport_closed",
        [(True, True, False), (False, False, False), (False, True, True)],
    )
    def test_get_transport_raises_error(
        self,
        reliability_layer: DatagramReliabilityLayer,
        is_layer_closed: bool,
        is_transport_present: bool,
        is_transport_closed: bool,
        mocker: MockerFixture,
    ) -> None:
        reliability_layer._closed = is_layer_closed
        if not is_transport_present:
            reliability_layer._transport = mocker.MagicMock(return_value=None)
        if is_transport_present:
            _transport: Any = reliability_layer._transport()
            if _transport:
                _transport.configure_mock(is_closed=is_transport_closed)

        with pytest.raises(DatagramError, match="layer or underlying transport is closed"):
            reliability_layer._get_transport()

    def test_start_background_tasks(self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer) -> None:
        transport = reliability_layer._transport()
        assert transport is not None
        layer = DatagramReliabilityLayer(datagram_transport=transport, ack_timeout=0.1, max_retries=2)
        created_coroutines = []

        def capture_coro_and_return_mock_task(coro: Coroutine[Any, Any, None]) -> Any:
            created_coroutines.append(coro)
            return mocker.MagicMock(spec=asyncio.Task)

        mock_create_task = mocker.patch("asyncio.create_task", side_effect=capture_coro_and_return_mock_task)

        layer._start_background_tasks()

        mock_create_task.assert_called_once()
        assert asyncio.iscoroutine(created_coroutines[0])
        assert layer._retry_task is not None
        for coro in created_coroutines:
            coro.close()

        mock_create_task.reset_mock()
        layer._start_background_tasks()
        mock_create_task.assert_not_called()

    def test_start_background_tasks_no_running_loop(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        transport = reliability_layer._transport()
        assert transport is not None
        layer = DatagramReliabilityLayer(datagram_transport=transport, ack_timeout=0.1, max_retries=2)

        def mock_create_task_and_raise(coro: Coroutine[Any, Any, None]) -> NoReturn:
            coro.close()
            raise RuntimeError("No loop")

        mocker.patch("asyncio.create_task", side_effect=mock_create_task_and_raise)

        layer._start_background_tasks()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("_handle_ack_message", {"payload": b"123"}),
            ("_handle_data_message", {"payload": b"\x00\x00\x00\x01data"}),
            ("_on_datagram_received", {"event": Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"data"})}),
        ],
    )
    async def test_internal_handlers_do_nothing_before_activation(
        self, mock_transport: Any, method_name: str, kwargs: dict[str, Any]
    ) -> None:
        layer = DatagramReliabilityLayer(datagram_transport=mock_transport)
        method = getattr(layer, method_name)
        await method(**kwargs)

    @pytest.mark.asyncio
    async def test_on_datagram_received_routes_correctly(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mock_handle_ack = mocker.patch.object(reliability_layer, "_handle_ack_message", new_callable=mocker.AsyncMock)
        mock_handle_data = mocker.patch.object(reliability_layer, "_handle_data_message", new_callable=mocker.AsyncMock)
        ack_payload = b"123"
        ack_event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"\x03ACK" + ack_payload})

        await reliability_layer._on_datagram_received(event=ack_event)
        mock_handle_ack.assert_awaited_once_with(payload=ack_payload)
        mock_handle_data.assert_not_called()

        mock_handle_ack.reset_mock()
        data_payload = struct.pack("!I", 456) + b"payload"
        data_event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"\x04DATA" + data_payload})
        await reliability_layer._on_datagram_received(event=data_event)
        mock_handle_data.assert_awaited_once_with(payload=data_payload)
        mock_handle_ack.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_data",
        ["not a dict", {"key": "value"}, {"data": "not bytes"}, {"data": b"\x0aINVALID-TYPE"}],
    )
    async def test_on_datagram_received_ignores_invalid_events(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer, event_data: Any
    ) -> None:
        mock_handle_ack = mocker.patch.object(reliability_layer, "_handle_ack_message")
        mock_handle_data = mocker.patch.object(reliability_layer, "_handle_data_message")
        event = Event(type=EventType.DATAGRAM_RECEIVED, data=event_data)

        await reliability_layer._on_datagram_received(event=event)

        mock_handle_ack.assert_not_called()
        mock_handle_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_datagram_received_parsing_error(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mock_handle_ack = mocker.patch.object(reliability_layer, "_handle_ack_message")
        malformed_event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"\xff"})

        await reliability_layer._on_datagram_received(event=malformed_event)

        mock_handle_ack.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_datagram_received_general_exception(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch.object(reliability_layer, "_handle_ack_message", side_effect=Exception("test error"))
        ack_payload = b"123"
        ack_event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"\x03ACK" + ack_payload})

        await reliability_layer._on_datagram_received(event=ack_event)

    @pytest.mark.asyncio
    async def test_handle_data_message_new(
        self, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        seq = TEST_START_SEQ
        data = b"new data"
        payload = struct.pack("!I", seq) + data

        await reliability_layer._handle_data_message(payload=payload)

        mock_transport._send_framed_data.assert_awaited_once_with(message_type="ACK", payload=str(seq).encode("utf-8"))
        assert seq in reliability_layer._received_sequences
        assert reliability_layer._incoming_queue is not None
        assert await reliability_layer._incoming_queue.get() == data

    @pytest.mark.asyncio
    async def test_handle_data_message_duplicate(
        self, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        seq = TEST_START_SEQ
        data = b"duplicate data"
        payload = struct.pack("!I", seq) + data
        reliability_layer._received_sequences.append(seq)

        await reliability_layer._handle_data_message(payload=payload)

        mock_transport._send_framed_data.assert_awaited_once_with(message_type="ACK", payload=str(seq).encode("utf-8"))
        assert reliability_layer._incoming_queue is not None
        assert reliability_layer._incoming_queue.empty()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [b"\x00\x00"])
    async def test_handle_data_message_malformed(
        self, mock_transport: Any, reliability_layer: DatagramReliabilityLayer, payload: bytes
    ) -> None:
        await reliability_layer._handle_data_message(payload=payload)

        mock_transport._send_framed_data.assert_not_called()
        assert reliability_layer._incoming_queue is not None
        assert reliability_layer._incoming_queue.empty()

    @pytest.mark.asyncio
    async def test_handle_data_message_ack_send_fails(
        self, mocker: MockerFixture, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mock_transport._send_framed_data.side_effect = DatagramError("Cannot send ACK")
        seq = TEST_START_SEQ
        data = b"new data"
        payload = struct.pack("!I", seq) + data

        await reliability_layer._handle_data_message(payload=payload)

        mock_transport._send_framed_data.assert_awaited_once_with(message_type="ACK", payload=str(seq).encode("utf-8"))
        assert reliability_layer._incoming_queue is not None
        assert reliability_layer._incoming_queue.empty()

    @pytest.mark.asyncio
    async def test_handle_ack_message(self, reliability_layer: DatagramReliabilityLayer) -> None:
        seq = TEST_START_SEQ
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = _ReliableDatagram(data=b"data")

        await reliability_layer._handle_ack_message(payload=str(seq).encode("utf-8"))
        assert seq not in reliability_layer._pending_acks

        await reliability_layer._handle_ack_message(payload=b"not-a-number")
        await reliability_layer._handle_ack_message(payload=str(seq + 1).encode("utf-8"))
        assert not reliability_layer._pending_acks

    @pytest.mark.asyncio
    async def test_retry_loop_continues_on_no_work(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        assert not reliability_layer._pending_acks

        await reliability_layer._retry_loop()

    @pytest.mark.asyncio
    async def test_retry_loop_retries_unacked_message(
        self, mocker: MockerFixture, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-data", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1

        await reliability_layer._retry_loop()

        mock_transport._send_framed_data.assert_awaited_once_with(message_type="DATA", payload=datagram.data)
        assert reliability_layer._pending_acks[seq].retry_count == 1

    @pytest.mark.asyncio
    async def test_retry_loop_gives_up_after_max_retries(
        self, mocker: MockerFixture, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"give-up-data", sequence=seq)
        datagram.retry_count = reliability_layer._max_retries
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1

        await reliability_layer._retry_loop()

        mock_transport._send_framed_data.assert_not_called()
        assert seq not in reliability_layer._pending_acks

    @pytest.mark.asyncio
    async def test_retry_loop_no_timeout(
        self, mocker: MockerFixture, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"not-timed-out", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout - 0.05

        await reliability_layer._retry_loop()

        mock_transport._send_framed_data.assert_not_called()
        assert seq in reliability_layer._pending_acks

    @pytest.mark.asyncio
    async def test_retry_loop_transport_closes_during_retry(
        self, mocker: MockerFixture, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-fail", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1
        mock_get_transport = mocker.patch.object(
            reliability_layer, "_get_transport", side_effect=DatagramError("Transport is gone")
        )

        await reliability_layer._retry_loop()

        mock_get_transport.assert_called_once()
        assert reliability_layer._closed is True

    @pytest.mark.asyncio
    async def test_retry_loop_unexpected_exception(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer, caplog: LogCaptureFixture
    ) -> None:
        error = ValueError("Unexpected error")
        mocker.patch("asyncio.sleep", side_effect=error)

        with caplog.at_level(logging.ERROR):
            await reliability_layer._retry_loop()
            assert "Reliability retry loop crashed: Unexpected error" in caplog.text

    @pytest.mark.asyncio
    async def test_retry_loop_taskgroup_exception(
        self, mocker: MockerFixture, mock_transport: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-data", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1
        mock_transport._send_framed_data.side_effect = Exception("TaskGroup error")

        await reliability_layer._retry_loop()

        assert reliability_layer._pending_acks[seq].retry_count == 1
