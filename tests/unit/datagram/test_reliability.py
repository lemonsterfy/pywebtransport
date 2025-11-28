"""Unit tests for the pywebtransport.datagram.reliability module."""

import asyncio
import logging
import struct
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import DatagramError, Event, TimeoutError, WebTransportSession
from pywebtransport.datagram import DatagramReliabilityLayer
from pywebtransport.datagram.reliability import _ReliableDatagram
from pywebtransport.types import EventType

TEST_START_SEQ = 100


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    session = mocker.create_autospec(WebTransportSession, instance=True)
    session.events = mocker.MagicMock()
    session.send_datagram = mocker.AsyncMock()
    session.is_closed = False
    return session


@pytest_asyncio.fixture
async def reliability_layer(
    mock_session: Any,
) -> AsyncGenerator[DatagramReliabilityLayer, None]:
    layer = DatagramReliabilityLayer(session=mock_session, ack_timeout=0.1, max_retries=2)
    async with layer as activated_layer:
        yield activated_layer


@pytest.mark.asyncio
class TestDatagramReliabilityLayer:

    async def test_api_calls_before_activation(self, mock_session: Any) -> None:
        layer = DatagramReliabilityLayer(session=mock_session)
        with pytest.raises(DatagramError, match="Reliability layer has not been activated"):
            await layer.send(data=b"test")

        with pytest.raises(DatagramError, match="has not been activated"):
            await layer.receive()

    async def test_calls_on_unactivated_layer(self, mock_session: Any) -> None:
        layer = DatagramReliabilityLayer(session=mock_session)
        await layer.close()
        await layer._handle_ack_message(payload=b"")
        await layer._handle_data_message(payload=b"")
        await layer._on_datagram_received(Event(type=EventType.DATAGRAM_RECEIVED, data=[]))
        await layer._retry_loop()

    async def test_close(self, mock_session: Any, reliability_layer: DatagramReliabilityLayer) -> None:
        background_task = asyncio.create_task(coro=asyncio.sleep(delay=30))
        reliability_layer._retry_task = background_task
        reliability_layer._pending_acks[1] = _ReliableDatagram(data=b"test", sequence=1)
        reliability_layer._received_sequences.append(1)

        await reliability_layer.close()

        assert reliability_layer._closed
        mock_session.events.off.assert_called_once_with(
            event_type=EventType.DATAGRAM_RECEIVED,
            handler=reliability_layer._on_datagram_received,
        )
        assert background_task.cancelled()
        assert not reliability_layer._pending_acks
        assert not reliability_layer._received_sequences

        mock_session.events.off.reset_mock()
        await reliability_layer.close()
        mock_session.events.off.assert_not_called()
        background_task.cancel()

    async def test_close_without_retry_task_or_session(self, mocker: MockerFixture, mock_session: Any) -> None:
        layer = DatagramReliabilityLayer(session=mock_session)
        async with layer:
            if layer._retry_task:
                layer._retry_task.cancel()
                await asyncio.sleep(delay=0)
            layer._retry_task = None
            mocker.patch.object(layer, "_session", return_value=None)

        await layer.close()
        mock_session.events.off.assert_not_called()

    async def test_context_manager(self, mocker: MockerFixture, mock_session: Any) -> None:
        reliability_layer = DatagramReliabilityLayer(session=mock_session, ack_timeout=0.1, max_retries=2)
        mock_start = mocker.patch.object(reliability_layer, "_start_background_tasks", autospec=True)
        mock_close = mocker.patch.object(reliability_layer, "close", new_callable=mocker.AsyncMock)

        async with reliability_layer as layer_instance:
            assert layer_instance is reliability_layer
            mock_start.assert_called_once()
            mock_session.events.on.assert_called_once_with(
                event_type=EventType.DATAGRAM_RECEIVED,
                handler=reliability_layer._on_datagram_received,
            )
        mock_close.assert_awaited_once()

    async def test_context_manager_no_session(self, mocker: MockerFixture, mock_session: Any) -> None:
        reliability_layer = DatagramReliabilityLayer(session=mock_session, ack_timeout=0.1, max_retries=2)
        mocker.patch.object(reliability_layer, "_session", return_value=None)
        async with reliability_layer:
            mock_session.events.on.assert_not_called()

    async def test_handle_ack_message(self, reliability_layer: DatagramReliabilityLayer) -> None:
        seq = TEST_START_SEQ
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = _ReliableDatagram(data=b"data", sequence=seq)

        await reliability_layer._handle_ack_message(payload=str(seq).encode("utf-8"))
        assert seq not in reliability_layer._pending_acks

    async def test_handle_ack_message_malformed(
        self, reliability_layer: DatagramReliabilityLayer, caplog: LogCaptureFixture
    ) -> None:
        reliability_layer._pending_acks[123] = _ReliableDatagram(data=b"data", sequence=123)
        with caplog.at_level(logging.WARNING):
            await reliability_layer._handle_ack_message(payload=b"not-a-seq")
            assert "Received malformed ACK" in caplog.text
        assert 123 in reliability_layer._pending_acks

    async def test_handle_ack_message_unicode_error(
        self, reliability_layer: DatagramReliabilityLayer, caplog: LogCaptureFixture
    ) -> None:
        reliability_layer._pending_acks[123] = _ReliableDatagram(data=b"data", sequence=123)
        with caplog.at_level(logging.WARNING):
            await reliability_layer._handle_ack_message(payload=b"\xff\xff")
            assert "Received malformed ACK" in caplog.text
        assert 123 in reliability_layer._pending_acks

    async def test_handle_data_message_ack_send_fails(
        self,
        mock_session: Any,
        reliability_layer: DatagramReliabilityLayer,
        caplog: LogCaptureFixture,
    ) -> None:
        mock_session.send_datagram.side_effect = DatagramError("Transport is closed")
        payload = struct.pack("!I", TEST_START_SEQ) + b"data"
        with caplog.at_level(logging.WARNING):
            await reliability_layer._handle_data_message(payload=payload)
            assert "Failed to send ACK for sequence 100" in caplog.text
        assert reliability_layer._incoming_queue is not None
        assert reliability_layer._incoming_queue.empty()

    async def test_handle_data_message_duplicate(
        self, mock_session: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        seq = TEST_START_SEQ
        data = b"duplicate data"
        payload = struct.pack("!I", seq) + data
        reliability_layer._received_sequences.append(seq)
        await reliability_layer._handle_data_message(payload=payload)
        expected_ack_frame = b"\x03ACK" + str(seq).encode("utf-8")

        mock_session.send_datagram.assert_awaited_once_with(data=expected_ack_frame)
        assert reliability_layer._incoming_queue is not None
        assert reliability_layer._incoming_queue.empty()

    async def test_handle_data_message_new(
        self, mock_session: Any, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        seq = TEST_START_SEQ
        data = b"new data"
        payload = struct.pack("!I", seq) + data
        await reliability_layer._handle_data_message(payload=payload)
        expected_ack_frame = b"\x03ACK" + str(seq).encode("utf-8")

        mock_session.send_datagram.assert_awaited_once_with(data=expected_ack_frame)
        assert seq in reliability_layer._received_sequences
        assert reliability_layer._incoming_queue is not None
        assert await reliability_layer._incoming_queue.get() == data

    async def test_handle_data_message_short_payload(self, reliability_layer: DatagramReliabilityLayer) -> None:
        await reliability_layer._handle_data_message(payload=b"abc")
        assert reliability_layer._incoming_queue is not None
        assert reliability_layer._incoming_queue.empty()

    @pytest.mark.parametrize(
        "event_data",
        [None, {"foo": "bar"}, {"data": "not bytes"}],
    )
    async def test_on_datagram_received_invalid_event_data(
        self, reliability_layer: DatagramReliabilityLayer, event_data: Any
    ) -> None:
        event = Event(type=EventType.DATAGRAM_RECEIVED, data=event_data)
        await reliability_layer._on_datagram_received(event=event)

    async def test_on_datagram_received_processing_error(
        self,
        reliability_layer: DatagramReliabilityLayer,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        mocker.patch.object(reliability_layer, "_handle_data_message", side_effect=ValueError("boom"))
        data_payload = struct.pack("!I", 456) + b"payload"
        data_frame = b"\x04DATA" + data_payload
        data_event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": data_frame})

        with caplog.at_level(logging.ERROR):
            await reliability_layer._on_datagram_received(event=data_event)
            assert "Error processing received datagram" in caplog.text
            assert "boom" in caplog.text

    async def test_on_datagram_received_routes_correctly(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mock_handle_ack = mocker.patch.object(reliability_layer, "_handle_ack_message", new_callable=mocker.AsyncMock)
        mock_handle_data = mocker.patch.object(reliability_layer, "_handle_data_message", new_callable=mocker.AsyncMock)
        ack_frame = b"\x03ACK123"
        ack_event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": ack_frame})

        await reliability_layer._on_datagram_received(event=ack_event)
        mock_handle_ack.assert_awaited_once_with(payload=b"123")
        mock_handle_data.assert_not_called()

        mock_handle_ack.reset_mock()
        data_payload = struct.pack("!I", 456) + b"payload"
        data_frame = b"\x04DATA" + data_payload
        data_event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": data_frame})
        await reliability_layer._on_datagram_received(event=data_event)
        mock_handle_data.assert_awaited_once_with(payload=data_payload)
        mock_handle_ack.assert_not_called()

    async def test_on_datagram_received_unknown_type(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        spy_handle_ack = mocker.spy(reliability_layer, "_handle_ack_message")
        spy_handle_data = mocker.spy(reliability_layer, "_handle_data_message")
        unknown_frame = b"\x07UNKNOWNpayload"
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": unknown_frame})

        await reliability_layer._on_datagram_received(event=event)

        spy_handle_ack.assert_not_called()
        spy_handle_data.assert_not_called()

    async def test_on_datagram_received_unpacked_none(self, reliability_layer: DatagramReliabilityLayer) -> None:
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b""})
        await reliability_layer._on_datagram_received(event=event)

    async def test_receive_on_closed_layer_raises_error(self, reliability_layer: DatagramReliabilityLayer) -> None:
        await reliability_layer.close()
        with pytest.raises(DatagramError, match="Reliability layer is closed"):
            await reliability_layer.receive()

    async def test_receive_successful(self, reliability_layer: DatagramReliabilityLayer) -> None:
        test_data = b"message received"
        assert reliability_layer._incoming_queue is not None
        await reliability_layer._incoming_queue.put(test_data)

        received_data = await reliability_layer.receive()
        assert received_data == test_data

    async def test_receive_timeout(self, reliability_layer: DatagramReliabilityLayer) -> None:
        with pytest.raises(TimeoutError, match="Receive timeout after 0.01s"):
            await reliability_layer.receive(timeout=0.01)

    async def test_retry_loop_crashes(
        self,
        mocker: MockerFixture,
        reliability_layer: DatagramReliabilityLayer,
        caplog: LogCaptureFixture,
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=ValueError("boom"))
        with caplog.at_level(logging.ERROR):
            await reliability_layer._retry_loop()
            assert "Reliability retry loop crashed: boom" in caplog.text

    async def test_retry_loop_gives_up_after_max_retries(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        reliability_layer: DatagramReliabilityLayer,
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

        mock_session.send_datagram.assert_not_called()
        assert seq not in reliability_layer._pending_acks

    async def test_retry_loop_natural_exit(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        call_count = 0

        async def sleep_then_close(*args: Any, **kwargs: Any) -> None:
            nonlocal call_count
            if call_count > 0:
                reliability_layer._closed = True
            call_count += 1
            await asyncio.sleep(delay=0)

        mocker.patch("asyncio.sleep", side_effect=sleep_then_close)
        await reliability_layer._retry_loop()
        assert call_count > 1

    async def test_retry_loop_no_retry_needed(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        reliability_layer: DatagramReliabilityLayer,
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-frame", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout - 0.1

        await reliability_layer._retry_loop()

        mock_session.send_datagram.assert_not_called()

    async def test_retry_loop_retries_multiple_messages(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        reliability_layer: DatagramReliabilityLayer,
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-data", sequence=seq)
        datagram2 = _ReliableDatagram(data=b"retry-data-2", sequence=seq + 1)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
            reliability_layer._pending_acks[seq + 1] = datagram2
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1

        await reliability_layer._retry_loop()

        assert mock_session.send_datagram.await_count == 2

    async def test_retry_loop_retries_unacked_message(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        reliability_layer: DatagramReliabilityLayer,
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-frame", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1

        await reliability_layer._retry_loop()

        mock_session.send_datagram.assert_awaited_once_with(data=datagram.data)
        assert reliability_layer._pending_acks[seq].retry_count == 1

    async def test_retry_loop_taskgroup_exception(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        reliability_layer: DatagramReliabilityLayer,
        caplog: LogCaptureFixture,
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-data", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1
        mock_session.send_datagram.side_effect = Exception("TaskGroup error")

        with caplog.at_level(logging.WARNING):
            await reliability_layer._retry_loop()
            assert "Errors occurred during datagram retry" in caplog.text

        assert reliability_layer._pending_acks[seq].retry_count == 1

    async def test_retry_loop_transport_closed(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        mock_time = mocker.patch("pywebtransport.datagram.reliability.get_timestamp")
        mocker.patch.object(reliability_layer, "_get_session", side_effect=DatagramError("closed"))
        seq = TEST_START_SEQ
        datagram = _ReliableDatagram(data=b"retry-frame", sequence=seq)
        assert reliability_layer._lock is not None
        async with reliability_layer._lock:
            reliability_layer._pending_acks[seq] = datagram
        mock_time.return_value = datagram.timestamp + reliability_layer._ack_timeout + 0.1

        await reliability_layer._retry_loop()
        assert reliability_layer._closed

    async def test_retry_loop_with_no_pending_acks(
        self, mocker: MockerFixture, reliability_layer: DatagramReliabilityLayer
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError])
        await reliability_layer._retry_loop()

    async def test_send_on_closed_layer_raises_error(self, reliability_layer: DatagramReliabilityLayer) -> None:
        await reliability_layer.close()
        with pytest.raises(DatagramError, match="closed"):
            await reliability_layer.send(data=b"test")

    async def test_send_successful(self, mock_session: Any, reliability_layer: DatagramReliabilityLayer) -> None:
        test_data = b"hello world"
        await reliability_layer.send(data=test_data)
        expected_frame = b"\x04DATA" + struct.pack("!I", 0) + test_data

        mock_session.send_datagram.assert_awaited_once_with(data=expected_frame)
        assert 0 in reliability_layer._pending_acks
        datagram = reliability_layer._pending_acks[0]
        assert datagram.data == expected_frame

    async def test_start_background_tasks_idempotent(self, reliability_layer: DatagramReliabilityLayer) -> None:
        assert reliability_layer._retry_task is not None
        initial_task = reliability_layer._retry_task
        reliability_layer._start_background_tasks()
        assert reliability_layer._retry_task is initial_task


class TestReliabilityLayerInternals:

    def test_pack_frame(self) -> None:
        session = MagicMock()
        layer = DatagramReliabilityLayer(session=session)
        frame = layer._pack_frame(message_type="DATA", payload=b"payload")
        assert frame == b"\x04DATApayload"

    def test_pack_frame_type_too_long(self) -> None:
        session = MagicMock()
        layer = DatagramReliabilityLayer(session=session)
        with pytest.raises(DatagramError, match="Message type too long"):
            layer._pack_frame(message_type="A" * 256, payload=b"")

    @pytest.mark.parametrize(
        "malformed_data",
        [b"", b"\x05DATA", b"\x01\xff", b"\x03AB"],
    )
    def test_unpack_frame_malformed(self, malformed_data: bytes) -> None:
        session = MagicMock()
        layer = DatagramReliabilityLayer(session=session)
        assert layer._unpack_frame(raw_data=malformed_data) is None

    @pytest.mark.parametrize(
        "raw_data, expected",
        [
            (b"\x04DATApayload", ("DATA", b"payload")),
            (b"\x03ACK123", ("ACK", b"123")),
            (b"\x00", ("", b"")),
            (b"\x01A", ("A", b"")),
        ],
    )
    def test_unpack_frame(self, raw_data: bytes, expected: tuple[str, bytes] | None) -> None:
        session = MagicMock()
        layer = DatagramReliabilityLayer(session=session)
        assert layer._unpack_frame(raw_data=raw_data) == expected
