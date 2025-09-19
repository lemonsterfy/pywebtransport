"""Unit tests for the pywebtransport.datagram.transport module."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, NoReturn

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_mock import MockerFixture

from pywebtransport import (
    DatagramError,
    Event,
    EventType,
    TimeoutError,
    WebTransportDatagramTransport,
    WebTransportSession,
)
from pywebtransport.datagram import DatagramMessage, DatagramQueue, DatagramStats


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    session = mocker.create_autospec(WebTransportSession, instance=True, spec_set=True)
    session.session_id = "test-session-id-1234567890abcdef"
    mock_protocol_handler = mocker.MagicMock()
    type(mock_protocol_handler).quic_connection = mocker.PropertyMock(return_value=mocker.MagicMock())
    mock_protocol_handler.quic_connection._max_datagram_size = 1200
    mock_protocol_handler.send_webtransport_datagram = mocker.MagicMock()
    session.protocol_handler = mock_protocol_handler
    session.on = mocker.MagicMock()
    type(session).is_ready = mocker.PropertyMock(return_value=True)
    return session


@pytest.fixture
async def queue() -> AsyncGenerator[DatagramQueue, None]:
    instance = DatagramQueue(max_size=1000)
    await instance.initialize()
    yield instance
    await instance.close()


@pytest.fixture
async def transport(mock_session: Any) -> AsyncGenerator[WebTransportDatagramTransport, None]:
    instance = WebTransportDatagramTransport(session=mock_session)
    await instance.initialize()
    yield instance
    await instance.close()


def _setup_high_drop_rate(*, transport: WebTransportDatagramTransport) -> None:
    transport._stats.send_drops = 11
    transport._stats.datagrams_sent = 89
    transport._stats.receive_drops = 11
    transport._stats.datagrams_received = 89


def _setup_queue_nearly_full(*, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
    mocker.patch.object(
        transport,
        "get_queue_stats",
        return_value={
            "outgoing": {"size": 95, "max_size": 100},
            "incoming": {"size": 91, "max_size": 100},
        },
    )


def _setup_incoming_queue_nearly_full(*, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
    mocker.patch.object(
        transport,
        "get_queue_stats",
        return_value={
            "outgoing": {"size": 5, "max_size": 100},
            "incoming": {"size": 91, "max_size": 100},
        },
    )


def _setup_high_send_latency(*, transport: WebTransportDatagramTransport) -> None:
    transport._stats.total_send_time = 2.0
    transport._stats.datagrams_sent = 10


def _setup_transport_closed(*, transport: WebTransportDatagramTransport) -> None:
    transport._closed = True


def _setup_session_not_ready(*, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
    if transport.session:
        setattr(type(transport.session), "is_ready", mocker.PropertyMock(return_value=False))


class TestDatagramStats:
    def test_initialization(self) -> None:
        stats = DatagramStats(session_id="sid", created_at=123.0)

        assert stats.session_id == "sid"
        assert stats.datagrams_sent == 0

    @pytest.mark.parametrize("sent, total_time, expected", [(10, 2.0, 0.2), (0, 0.0, 0.0), (1, 0, 0)])
    def test_avg_send_time(self, sent: int, total_time: float, expected: float) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        stats.datagrams_sent = sent
        stats.total_send_time = total_time

        assert stats.avg_send_time == expected

    @pytest.mark.parametrize("received, total_time, expected", [(20, 5.0, 0.25), (0, 0.0, 0.0)])
    def test_avg_receive_time(self, received: int, total_time: float, expected: float) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        stats.datagrams_received = received
        stats.total_receive_time = total_time

        assert stats.avg_receive_time == expected

    def test_avg_datagram_size(self) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        stats.datagrams_sent = 2
        stats.datagrams_received = 3
        stats.total_datagram_size = 500

        assert stats.avg_datagram_size == 100.0

        stats.datagrams_sent = 0
        stats.datagrams_received = 0
        stats.total_datagram_size = 0
        assert stats.avg_datagram_size == 0.0

    def test_success_rates(self) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        stats.datagrams_sent = 90
        stats.send_failures = 10
        stats.datagrams_received = 45
        stats.receive_errors = 5

        assert stats.send_success_rate == 0.9
        assert stats.receive_success_rate == 0.9

        stats.datagrams_sent = 0
        stats.send_failures = 0
        stats.datagrams_received = 0
        stats.receive_errors = 0
        assert stats.send_success_rate == 1.0
        assert stats.receive_success_rate == 1.0

    def test_to_dict(self) -> None:
        stats = DatagramStats(session_id="sid", created_at=123.0)
        stats.min_datagram_size = float("inf")

        data = stats.to_dict()

        assert data["min_datagram_size"] == 0


class TestDatagramMessage:
    def test_post_init(self) -> None:
        msg = DatagramMessage(data=b"hello")

        assert msg.size == 5
        assert isinstance(msg.checksum, str)

    def test_post_init_with_checksum(self) -> None:
        msg = DatagramMessage(data=b"world", checksum="pre-computed")

        assert msg.checksum == "pre-computed"

    def test_age_and_is_expired(self, mocker: MockerFixture) -> None:
        mock_time = mocker.patch("time.time")
        mock_time.return_value = 1000.0
        msg = DatagramMessage(data=b"ttl-test", ttl=10.0)

        assert msg.timestamp == 1000.0
        assert msg.age == 0.0
        assert not msg.is_expired

        mock_time.return_value = 1011.0
        assert msg.age == 11.0
        assert msg.is_expired

    def test_is_expired_no_ttl(self) -> None:
        msg = DatagramMessage(data=b"no-ttl")

        assert not msg.is_expired

    def test_to_dict(self) -> None:
        msg = DatagramMessage(data=b"data", ttl=60)

        data = msg.to_dict()

        expected_keys = ["size", "timestamp", "age", "checksum", "sequence", "priority", "ttl", "is_expired"]
        assert all(key in data for key in expected_keys)


class TestDatagramQueue:
    @pytest.mark.asyncio
    async def test_put_get(self, queue: DatagramQueue) -> None:
        msg = DatagramMessage(data=b"data")

        assert await queue.put(datagram=msg) is True
        retrieved_msg = await queue.get()

        assert retrieved_msg is msg

    @pytest.mark.asyncio
    async def test_get_waits_for_item(self, queue: DatagramQueue) -> None:
        item_retrieved = asyncio.Event()
        retrieved_msg = None

        async def getter() -> None:
            nonlocal retrieved_msg
            retrieved_msg = await queue.get(timeout=1)
            item_retrieved.set()

        task = asyncio.create_task(getter())
        await asyncio.sleep(0.01)
        assert not item_retrieved.is_set()

        msg_to_put = DatagramMessage(data=b"waited-for")
        await queue.put(datagram=msg_to_put)
        await asyncio.wait_for(item_retrieved.wait(), timeout=1)

        assert retrieved_msg is msg_to_put
        await task

    @pytest.mark.asyncio
    async def test_get_nowait(self, queue: DatagramQueue) -> None:
        assert await queue.get_nowait() is None

        msg = DatagramMessage(data=b"data")
        await queue.put(datagram=msg)
        assert await queue.get_nowait() is msg

        assert await queue.get_nowait() is None

    @pytest.mark.asyncio
    async def test_priority(self, queue: DatagramQueue) -> None:
        await queue.put(datagram=DatagramMessage(data=b"low", priority=0))
        await queue.put(datagram=DatagramMessage(data=b"high", priority=2))
        await queue.put(datagram=DatagramMessage(data=b"mid", priority=1))

        assert (await queue.get()).data == b"high"
        assert (await queue.get()).data == b"mid"

    @pytest.mark.asyncio
    async def test_clear(self, queue: DatagramQueue) -> None:
        await queue.put(datagram=DatagramMessage(data=b"data"))
        assert not queue.empty()

        await queue.clear()

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        queue = DatagramQueue(max_size=5)
        await queue.initialize()
        await queue.put_nowait(datagram=DatagramMessage(data=b"p0", priority=0))
        await queue.put_nowait(datagram=DatagramMessage(data=b"p2", priority=2))

        stats = queue.get_stats()

        assert stats["size"] == 2
        assert stats["max_size"] == 5
        assert stats["priority_0"] == 1
        assert stats["priority_2"] == 1
        await queue.close()

    @pytest.mark.asyncio
    async def test_max_size_limit_eviction(self) -> None:
        queue = DatagramQueue(max_size=2)
        await queue.initialize()
        await queue.put(datagram=DatagramMessage(data=b"1"))
        await queue.put(datagram=DatagramMessage(data=b"2"))

        assert await queue.put(datagram=DatagramMessage(data=b"3")) is True
        datas = {(await queue.get()).data, (await queue.get()).data}

        assert datas == {b"2", b"3"}
        await queue.close()

    @pytest.mark.asyncio
    async def test_put_full_queue_no_eviction(self) -> None:
        queue = DatagramQueue(max_size=1)
        await queue.initialize()
        await queue.put(datagram=DatagramMessage(data=b"p1", priority=1))

        assert await queue.put(datagram=DatagramMessage(data=b"p0", priority=0)) is False
        await queue.close()

    @pytest.mark.asyncio
    async def test_put_full_queue_no_low_priority_eviction(self) -> None:
        queue = DatagramQueue(max_size=2)
        await queue.initialize()
        await queue.put(datagram=DatagramMessage(data=b"p1", priority=1))
        await queue.put(datagram=DatagramMessage(data=b"p2", priority=2))

        assert await queue.put(datagram=DatagramMessage(data=b"p0", priority=0)) is False
        assert queue.qsize() == 2
        await queue.close()

    @pytest.mark.asyncio
    async def test_put_nowait_full_queue_no_eviction(self) -> None:
        queue = DatagramQueue(max_size=1)
        await queue.initialize()
        await queue.put_nowait(datagram=DatagramMessage(data=b"p1", priority=1))

        assert await queue.put_nowait(datagram=DatagramMessage(data=b"p0", priority=0)) is False
        await queue.close()

    @pytest.mark.asyncio
    async def test_put_nowait_full_queue_eviction(self) -> None:
        queue = DatagramQueue(max_size=2)
        await queue.initialize()
        await queue.put_nowait(datagram=DatagramMessage(data=b"1", priority=0))
        await queue.put_nowait(datagram=DatagramMessage(data=b"2", priority=1))

        assert await queue.put_nowait(datagram=DatagramMessage(data=b"3", priority=0)) is True
        assert queue.qsize() == 2

        high_prio_msg = await queue.get_nowait()
        assert high_prio_msg and high_prio_msg.data == b"2"

        low_prio_msg = await queue.get_nowait()
        assert low_prio_msg and low_prio_msg.data == b"3"

        await queue.close()

    @pytest.mark.asyncio
    async def test_get_timeout(self, queue: DatagramQueue) -> None:
        with pytest.raises(TimeoutError):
            await queue.get(timeout=0.01)

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, mocker: MockerFixture) -> None:
        mock_time = mocker.patch("time.time")
        queue = DatagramQueue(max_age=10)
        await queue.initialize()
        mock_time.return_value = 980.0
        await queue.put(datagram=DatagramMessage(data=b"stale"))
        mock_time.return_value = 1000.0
        await queue.put(datagram=DatagramMessage(data=b"fresh"))

        mock_time.return_value = 1005.0
        queue._cleanup_expired()

        assert queue.qsize() == 1
        assert (await queue.get()).data == b"fresh"
        await queue.close()

    @pytest.mark.asyncio
    async def test_cleanup_expired_no_max_age(self) -> None:
        queue = DatagramQueue(max_age=None)
        await queue.initialize()
        await queue.put(datagram=DatagramMessage(data=b"some-data"))
        queue._cleanup_expired()
        assert queue.qsize() == 1
        await queue.close()

    @pytest.mark.asyncio
    async def test_put_expired_datagram(self, mocker: MockerFixture, queue: DatagramQueue) -> None:
        mock_time = mocker.patch("time.time")
        mock_time.return_value = 1000.0
        expired_msg = DatagramMessage(data=b"expired", ttl=5, timestamp=990.0)

        assert await queue.put(datagram=expired_msg) is False
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_put_nowait_expired_datagram(self, mocker: MockerFixture, queue: DatagramQueue) -> None:
        mock_time = mocker.patch("time.time")
        mock_time.return_value = 1000.0
        expired_msg = DatagramMessage(data=b"expired", ttl=5, timestamp=990.0)

        assert await queue.put_nowait(datagram=expired_msg) is False
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_background_cleanup_task(self, mocker: MockerFixture) -> None:
        queue = DatagramQueue(max_age=5)
        mocker.patch.object(queue, "_start_cleanup", return_value=None)
        await queue.initialize()
        mocker.stopall()
        spy_create_task = mocker.spy(asyncio, "create_task")

        queue._start_cleanup()

        spy_create_task.assert_called_once()
        cleanup_task = spy_create_task.spy_return
        cleanup_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cleanup_task

    @pytest.mark.asyncio
    async def test_cleanup_loop_runs_once(self, mocker: MockerFixture) -> None:
        queue = DatagramQueue(max_age=0.01)
        await queue.initialize()

        spy_cleanup = mocker.spy(queue, "_cleanup_expired")
        await asyncio.sleep(0.05)
        spy_cleanup.assert_called()
        await queue.close()

    @pytest.mark.asyncio
    async def test_close_cancels_task(self, mocker: MockerFixture) -> None:
        queue = DatagramQueue(max_age=5)
        mocker.patch.object(queue, "_start_cleanup", return_value=None)
        await queue.initialize()
        mocker.stopall()
        create_task_spy = mocker.spy(asyncio, "create_task")

        queue._start_cleanup()

        create_task_spy.assert_called_once()
        real_task = create_task_spy.spy_return
        await queue.close()
        assert real_task.cancelled()
        await asyncio.sleep(0)
        with pytest.raises(asyncio.CancelledError):
            await real_task

    @pytest.mark.asyncio
    async def test_start_cleanup_conditions(self, mocker: MockerFixture) -> None:
        queue_no_age = DatagramQueue(max_age=None)
        await queue_no_age.initialize()
        spy_create_task = mocker.spy(asyncio, "create_task")
        queue_no_age._start_cleanup()
        spy_create_task.assert_not_called()
        assert queue_no_age._cleanup_task is None
        await queue_no_age.close()

        queue_with_age = DatagramQueue(max_age=5)
        await queue_with_age.initialize()
        assert queue_with_age._cleanup_task is not None
        first_task = queue_with_age._cleanup_task
        spy_create_task.reset_mock()

        queue_with_age._start_cleanup()
        spy_create_task.assert_not_called()
        assert queue_with_age._cleanup_task is first_task
        await queue_with_age.close()

    def test_start_cleanup_no_loop(self, mocker: MockerFixture) -> None:
        def mock_create_task_with_error(coro: Coroutine[Any, Any, None]) -> NoReturn:
            coro.close()
            raise RuntimeError("no loop")

        mocker.patch("asyncio.create_task", side_effect=mock_create_task_with_error)
        queue = DatagramQueue(max_age=5)

        queue._start_cleanup()

        assert queue._cleanup_task is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["get", "get_nowait", "put", "put_nowait", "clear"])
    async def test_uninitialized_queue_raises_error(self, method_name: str) -> None:
        queue = DatagramQueue()
        method = getattr(queue, method_name)

        with pytest.raises(DatagramError, match="not been initialized"):
            if "put" in method_name:
                await method(datagram=DatagramMessage(data=b""))
            else:
                await method()


class TestWebTransportDatagramTransport:
    def test_initialization_and_defaults(self, mock_session: Any) -> None:
        transport = WebTransportDatagramTransport(session=mock_session, high_water_mark=50)

        assert transport.session_id == mock_session.session_id
        assert transport.outgoing_high_water_mark == 50
        assert transport.outgoing_max_age is None
        assert transport.incoming_max_age is None
        mock_session.on.assert_not_called()

        transport._outgoing_max_age = 10.0
        assert transport.outgoing_max_age == 10.0

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        spy_start_tasks = mocker.spy(transport, "_start_background_tasks")
        await transport.initialize()
        spy_start_tasks.assert_not_called()

    @pytest.mark.asyncio
    async def test_init_start_tasks_runtime_error(
        self, mock_session: Any, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        transport = WebTransportDatagramTransport(session=mock_session)

        def mock_create_task_with_error(coro: Coroutine[Any, Any, None]) -> NoReturn:
            coro.close()
            raise RuntimeError("no loop")

        mocker.patch("asyncio.create_task", side_effect=mock_create_task_with_error)

        with caplog.at_level(logging.WARNING):
            await transport.initialize()
            assert "Could not start datagram background tasks" in caplog.text

    @pytest.mark.asyncio
    async def test_start_background_tasks_idempotent(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        assert transport._sender_task is not None
        first_task = transport._sender_task
        spy_create_task = mocker.spy(asyncio, "create_task")

        transport._start_background_tasks()

        spy_create_task.assert_not_called()
        assert transport._sender_task is first_task

    @pytest.mark.asyncio
    async def test_properties_no_session(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        transport._session = mocker.MagicMock(return_value=None)

        assert transport.session is None
        assert transport.max_datagram_size == 1200

    def test_max_datagram_size_no_protocol_handler(self, mock_session: Any) -> None:
        mock_session.protocol_handler = None
        transport = WebTransportDatagramTransport(session=mock_session)
        assert transport.max_datagram_size == 1200

    def test_str_representation(self, transport: WebTransportDatagramTransport) -> None:
        transport._stats.datagrams_sent = 10
        transport._stats.datagrams_received = 5

        representation = str(transport)
        assert "DatagramTransport" in representation
        assert "sent=10" in representation
        assert "received=5" in representation
        assert "success_rate" in representation

    @pytest.mark.asyncio
    async def test_close_stops_sender_loop(self, transport: WebTransportDatagramTransport) -> None:
        assert transport._sender_task is not None
        sender_task = transport._sender_task
        assert not sender_task.done()

        await transport.close()
        await asyncio.sleep(0)

        assert sender_task.done()

    @pytest.mark.asyncio
    async def test_close_idempotent(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._outgoing_queue is not None
        close_spy = mocker.spy(transport._outgoing_queue, "close")

        await transport.close()
        assert transport.is_closed
        close_spy.assert_awaited_once()

        await transport.close()
        close_spy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_session: Any) -> None:
        transport = WebTransportDatagramTransport(session=mock_session)
        await transport.initialize()

        async with transport:
            assert not transport.is_closed

        assert transport.is_closed

    @pytest.mark.asyncio
    async def test_send_normal(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._outgoing_queue is not None
        mock_put = mocker.patch.object(transport._outgoing_queue, "put", new_callable=mocker.AsyncMock)
        mock_put.return_value = True

        await transport.send(data=b"data")

        mock_put.assert_awaited_once()
        assert transport.datagrams_sent == 1

    @pytest.mark.asyncio
    async def test_send_multiple(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(transport, "send", new_callable=mocker.AsyncMock)

        count = await transport.send_multiple(datagrams=[b"a", b"b", "c"])

        assert count == 3
        assert mock_send.await_count == 3

    @pytest.mark.asyncio
    async def test_send_json_and_framed_data(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(transport, "send", new_callable=mocker.AsyncMock)

        await transport.send_json(data={"key": "value"})
        mock_send.assert_awaited_with(data=b'{"key":"value"}', priority=0, ttl=None)

        await transport._send_framed_data(message_type="my-type", payload=b"payload")
        mock_send.assert_awaited_with(data=b"\x07my-typepayload", priority=0, ttl=None)

    @pytest.mark.asyncio
    async def test_try_send(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._outgoing_queue is not None
        mock_put = mocker.patch.object(transport._outgoing_queue, "put_nowait", new_callable=mocker.AsyncMock)
        mock_put.return_value = True

        result = await transport.try_send(data=b"data")

        assert result is True
        mock_put.assert_awaited_once()
        assert transport.datagrams_sent == 1

    @pytest.mark.asyncio
    async def test_receive_normal(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._incoming_queue is not None
        datagram = DatagramMessage(data=b"incoming")
        mocker.patch.object(transport._incoming_queue, "get", new_callable=mocker.AsyncMock, return_value=datagram)

        data = await transport.receive()

        assert data == b"incoming"
        assert transport.datagrams_received == 1

    @pytest.mark.asyncio
    async def test_receive_when_closed(self, transport: WebTransportDatagramTransport) -> None:
        await transport.close()
        with pytest.raises(DatagramError, match="transport is closed"):
            await transport.receive()

    @pytest.mark.asyncio
    async def test_receive_updates_stats_correctly(self, transport: WebTransportDatagramTransport) -> None:
        assert transport._incoming_queue is not None
        await transport._incoming_queue.put(datagram=DatagramMessage(data=b"a-bit-longer"))
        await transport._incoming_queue.put(datagram=DatagramMessage(data=b"short"))

        await transport.receive()
        assert transport.stats["min_datagram_size"] == len(b"a-bit-longer")
        assert transport.stats["max_datagram_size"] == len(b"a-bit-longer")

        await transport.receive()
        assert transport.stats["min_datagram_size"] == len(b"short")
        assert transport.stats["max_datagram_size"] == len(b"a-bit-longer")

    @pytest.mark.asyncio
    async def test_receive_multiple(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        mocker.patch.object(transport, "receive", new_callable=mocker.AsyncMock, side_effect=[b"one"])
        mocker.patch.object(
            transport, "try_receive", new_callable=mocker.AsyncMock, side_effect=[b"two", b"three", None]
        )

        datagrams = await transport.receive_multiple(max_count=5)

        assert datagrams == [b"one", b"two", b"three"]

    @pytest.mark.asyncio
    async def test_receive_with_metadata(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._incoming_queue is not None
        datagram = DatagramMessage(data=b"meta", sequence=42)
        mocker.patch.object(transport._incoming_queue, "get", new_callable=mocker.AsyncMock, return_value=datagram)

        result = await transport.receive_with_metadata()

        assert result["data"] == b"meta"
        assert result["metadata"]["sequence"] == 42

    @pytest.mark.asyncio
    async def test_receive_with_metadata_when_closed(self, transport: WebTransportDatagramTransport) -> None:
        await transport.close()
        with pytest.raises(DatagramError, match="transport is closed"):
            await transport.receive_with_metadata()

    @pytest.mark.asyncio
    async def test_receive_with_metadata_generic_error(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._incoming_queue, "get", side_effect=ValueError("generic error"))
        with pytest.raises(DatagramError, match="generic error"):
            await transport.receive_with_metadata()

    @pytest.mark.asyncio
    async def test_receive_helpers(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        mock_receive = mocker.patch.object(transport, "receive", new_callable=mocker.AsyncMock)

        mock_receive.return_value = b'{"a":1}'
        assert await transport.receive_json() == {"a": 1}

        mock_receive.return_value = b"\x04typepayload"
        msg_type, payload = await transport._receive_framed_data()
        assert msg_type == "type"
        assert payload == b"payload"

    @pytest.mark.asyncio
    async def test_try_receive(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._incoming_queue is not None
        mock_get_nowait = mocker.patch.object(transport._incoming_queue, "get_nowait", new_callable=mocker.AsyncMock)

        mock_get_nowait.return_value = None
        assert await transport.try_receive() is None

        datagram = DatagramMessage(data=b"buffered")
        mock_get_nowait.return_value = datagram
        assert await transport.try_receive() == b"buffered"

    @pytest.mark.asyncio
    async def test_try_receive_when_closed(self, transport: WebTransportDatagramTransport) -> None:
        await transport.close()
        assert await transport.try_receive() is None

    @pytest.mark.asyncio
    async def test_buffer_management(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._outgoing_queue is not None
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._outgoing_queue, "qsize", return_value=5)
        mocker.patch.object(transport._incoming_queue, "qsize", return_value=3)
        mock_clear_out = mocker.patch.object(transport._outgoing_queue, "clear", new_callable=mocker.AsyncMock)
        mock_clear_in = mocker.patch.object(transport._incoming_queue, "clear", new_callable=mocker.AsyncMock)

        assert transport.get_send_buffer_size() == 5
        assert transport.get_receive_buffer_size() == 3
        await transport.clear_send_buffer()
        await transport.clear_receive_buffer()

        mock_clear_out.assert_awaited_once()
        mock_clear_in.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_heartbeat(self, transport: WebTransportDatagramTransport) -> None:
        task = transport.start_heartbeat(interval=0.01)

        assert isinstance(task, asyncio.Task)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    def test_debug_state(self, transport: WebTransportDatagramTransport) -> None:
        state = transport.debug_state()

        assert "transport" in state
        assert "statistics" in state
        assert "queues" in state
        assert "configuration" in state
        assert "sequences" in state

    def test_get_queue_stats_uninitialized(self, mock_session: Any) -> None:
        transport = WebTransportDatagramTransport(session=mock_session)
        stats = transport.get_queue_stats()
        assert stats == {"outgoing": {}, "incoming": {}}

    @pytest.mark.asyncio
    async def test_diagnose_issues_no_issues(self, transport: WebTransportDatagramTransport) -> None:
        transport._stats.send_failures = 0
        transport._stats.datagrams_sent = 100
        transport._stats.send_drops = 0
        transport._stats.receive_drops = 0
        transport._stats.datagrams_received = 100
        transport._stats.total_send_time = 0.1
        assert not await transport.diagnose_issues()

    @pytest.mark.asyncio
    async def test_send_too_large(self, transport: WebTransportDatagramTransport) -> None:
        large_data = b"a" * (transport.max_datagram_size + 1)

        with pytest.raises(DatagramError, match="exceeds maximum"):
            await transport.send(data=large_data)

    @pytest.mark.asyncio
    async def test_send_when_closed(self, transport: WebTransportDatagramTransport) -> None:
        await transport.close()

        with pytest.raises(DatagramError, match="transport is closed"):
            await transport.send(data=b"data")

    @pytest.mark.asyncio
    async def test_send_queue_full(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._outgoing_queue is not None
        mocker.patch.object(transport._outgoing_queue, "put", new_callable=mocker.AsyncMock, return_value=False)

        with pytest.raises(DatagramError, match="queue full"):
            await transport.send(data=b"data")

        assert transport.stats["send_drops"] == 1

    @pytest.mark.asyncio
    async def test_send_multiple_with_error(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mock_send = mocker.patch.object(transport, "send", new_callable=mocker.AsyncMock)
        mock_send.side_effect = [None, DatagramError("fail"), None]

        with caplog.at_level(logging.WARNING):
            count = await transport.send_multiple(datagrams=[b"a", b"b", b"c"])

        assert count == 1
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert "Failed to send datagram 2" in record.message
        assert "fail" in record.message

    @pytest.mark.asyncio
    async def test_send_json_serialization_error(self, transport: WebTransportDatagramTransport) -> None:
        with pytest.raises(DatagramError, match="Failed to serialize JSON datagram"):
            await transport.send_json(data={b"bytes are not serializable"})

    @pytest.mark.asyncio
    async def test_send_framed_data_type_too_long(self, transport: WebTransportDatagramTransport) -> None:
        with pytest.raises(DatagramError, match="Message type too long"):
            await transport._send_framed_data(message_type="a" * 256, payload=b"")

    @pytest.mark.asyncio
    async def test_try_send_failures(self, transport: WebTransportDatagramTransport) -> None:
        large_data = b"a" * (transport.max_datagram_size + 1)

        assert await transport.try_send(data=large_data) is False
        assert transport.stats["send_drops"] == 1

        await transport.close()
        assert await transport.try_send(data=b"data") is False

    @pytest.mark.asyncio
    async def test_receive_timeout(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._incoming_queue, "get", side_effect=TimeoutError("timeout"))

        with pytest.raises(TimeoutError):
            await transport.receive(timeout=0.1)

    @pytest.mark.asyncio
    async def test_receive_with_metadata_timeout(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._incoming_queue, "get", side_effect=TimeoutError("timeout"))

        with pytest.raises(TimeoutError):
            await transport.receive_with_metadata(timeout=0.1)

    @pytest.mark.asyncio
    async def test_receive_multiple_timeout_on_first(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._incoming_queue, "get", side_effect=TimeoutError("timeout"))

        with pytest.raises(TimeoutError):
            await transport.receive_multiple(max_count=5)

    @pytest.mark.asyncio
    async def test_receive_multiple_timeout_after_first(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(
            transport._incoming_queue, "get", side_effect=[DatagramMessage(data=b"one"), TimeoutError("timeout")]
        )
        mocker.patch.object(transport._incoming_queue, "get_nowait", return_value=None)
        datagrams = await transport.receive_multiple(max_count=5)

        assert datagrams == [b"one"]

    @pytest.mark.asyncio
    async def test_framed_data_errors(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        mock_receive = mocker.patch.object(transport, "receive", new_callable=mocker.AsyncMock)

        mock_receive.return_value = b"\xff"
        with pytest.raises(DatagramError, match="Failed to receive framed datagram"):
            await transport._receive_framed_data()

        mock_receive.return_value = b"\x01"
        with pytest.raises(DatagramError, match="too short for type header"):
            await transport._receive_framed_data()

        mock_receive.return_value = b""
        with pytest.raises(DatagramError, match="too short for frame header"):
            await transport._receive_framed_data()

        mock_receive.return_value = b"\x02\x80\x81payload"
        with pytest.raises(DatagramError, match="Failed to parse framed datagram"):
            await transport._receive_framed_data()

    @pytest.mark.asyncio
    async def test_receive_framed_data_generic_error(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(transport, "receive", side_effect=ValueError("generic"))
        with pytest.raises(DatagramError, match="Failed to receive framed datagram"):
            await transport._receive_framed_data()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload, error_type", [(b"{'invalid'}", json.JSONDecodeError), (b"\x80", UnicodeDecodeError)]
    )
    async def test_receive_json_errors(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        payload: bytes,
        error_type: type[Exception],
    ) -> None:
        mocker.patch.object(transport, "receive", new_callable=mocker.AsyncMock, return_value=payload)
        with pytest.raises(DatagramError, match="Failed to parse JSON datagram"):
            await transport.receive_json()

    @pytest.mark.asyncio
    async def test_receive_json_generic_error(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(transport, "receive", side_effect=ValueError("generic"))
        with pytest.raises(DatagramError, match="Failed to receive JSON datagram"):
            await transport.receive_json()

    @pytest.mark.asyncio
    async def test_receive_json_and_framed_data_timeout(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(transport, "receive", side_effect=TimeoutError("timeout"))

        with pytest.raises(TimeoutError):
            await transport.receive_json()

        with pytest.raises(TimeoutError):
            await transport._receive_framed_data()

    @pytest.mark.asyncio
    async def test_on_datagram_received(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._incoming_queue is not None
        mock_put = mocker.patch.object(transport._incoming_queue, "put", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"from-event"})

        await transport._on_datagram_received(event=event)

        mock_put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_datagram_received_uninitialized(self, mock_session: Any) -> None:
        transport = WebTransportDatagramTransport(session=mock_session)
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"from-event"})
        await transport._on_datagram_received(event=event)
        assert transport.stats["datagrams_received"] == 0

    @pytest.mark.asyncio
    async def test_on_datagram_received_failures(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._incoming_queue, "put", new_callable=mocker.AsyncMock, return_value=False)
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"dropped"})

        await transport._on_datagram_received(event=event)
        assert transport.stats["receive_drops"] == 1

        mocker.patch.object(transport._incoming_queue, "put", side_effect=ValueError("test error"))
        transport._stats.receive_errors = 0
        await transport._on_datagram_received(event=event)
        assert transport.stats["receive_errors"] == 1

        await transport._on_datagram_received(event=Event(type=EventType.DATAGRAM_RECEIVED, data={"no-data": True}))
        assert transport.stats["receive_errors"] == 1

    @pytest.mark.asyncio
    async def test_sender_loop(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        datagram_to_send = DatagramMessage(data=b"loop-data")
        assert transport._outgoing_queue is not None
        assert transport.session is not None
        assert transport.session.protocol_handler is not None
        mock_send_dgram = mocker.patch.object(transport.session.protocol_handler, "send_webtransport_datagram")
        mock_get = mocker.patch.object(transport._outgoing_queue, "get", new_callable=mocker.AsyncMock)

        async def get_side_effect(*args: Any, **kwargs: Any) -> DatagramMessage:
            if mock_get.call_count == 1:
                return datagram_to_send
            transport._closed = True
            raise TimeoutError("stop loop")

        mock_get.side_effect = get_side_effect

        await transport._sender_loop()

        mock_send_dgram.assert_called_once_with(session_id=transport.session_id, data=datagram_to_send.data)

    @pytest.mark.asyncio
    async def test_sender_loop_failures(
        self,
        transport: WebTransportDatagramTransport,
        caplog: LogCaptureFixture,
        mocker: MockerFixture,
        mock_session: Any,
    ) -> None:
        assert transport._outgoing_queue is not None
        datagram = DatagramMessage(data=b"data")
        transport._session = mocker.MagicMock(return_value=None)
        mock_get = mocker.patch.object(transport._outgoing_queue, "get", new_callable=mocker.AsyncMock)

        async def get_side_effect_1(*args: Any, **kwargs: Any) -> DatagramMessage:
            transport._closed = True
            return datagram

        mock_get.side_effect = get_side_effect_1
        with caplog.at_level(logging.WARNING):
            await transport._sender_loop()
            assert "session is gone" in caplog.text

        transport._closed = False
        caplog.clear()
        mock_get.side_effect = ValueError("Fatal Error")
        with caplog.at_level(logging.ERROR):
            await transport._sender_loop()
            assert "Sender loop fatal error" in caplog.text

        transport._closed = False
        caplog.clear()
        transport._session = mocker.MagicMock(return_value=mock_session)
        mock_session.protocol_handler.send_webtransport_datagram.side_effect = ValueError("Send Error")
        mock_get.side_effect = get_side_effect_1
        with caplog.at_level(logging.WARNING):
            await transport._sender_loop()
            assert "Failed to send datagram" in caplog.text

    @pytest.mark.asyncio
    async def test_heartbeat_loop(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        mock_send = mocker.patch.object(transport, "send", new_callable=mocker.AsyncMock)
        asyncio_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

        async def sleep_side_effect(*args: Any, **kwargs: Any) -> None:
            if mock_send.call_count >= 2:
                transport._closed = True

        asyncio_sleep.side_effect = sleep_side_effect

        await transport._heartbeat_loop(interval=0.01)

        assert mock_send.call_count == 2

    @pytest.mark.asyncio
    async def test_heartbeat_loop_cancellation(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        mock_send = mocker.patch.object(transport, "send", new_callable=mocker.AsyncMock)
        asyncio_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        asyncio_sleep.side_effect = asyncio.CancelledError

        await transport._heartbeat_loop(interval=10)
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_send_error(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch.object(transport, "send", side_effect=DatagramError("send failed"))
        asyncio_sleep = mocker.patch.object(asyncio, "sleep", new_callable=mocker.AsyncMock)
        asyncio_sleep.side_effect = asyncio.CancelledError

        with caplog.at_level(logging.WARNING):
            await transport._heartbeat_loop(interval=10)
            assert "Failed to send heartbeat" in caplog.text

    @pytest.mark.asyncio
    async def test_heartbeat_loop_generic_error(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch.object(transport, "send", side_effect=Exception("generic error"))
        asyncio_sleep = mocker.patch.object(asyncio, "sleep", new_callable=mocker.AsyncMock)
        asyncio_sleep.side_effect = asyncio.CancelledError

        with caplog.at_level(logging.ERROR):
            await transport._heartbeat_loop(interval=10)
            assert "Heartbeat loop error" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("send", {"data": b""}),
            ("receive", {}),
            ("try_send", {"data": b""}),
            ("try_receive", {}),
            ("start_heartbeat", {}),
            ("clear_send_buffer", {}),
            ("clear_receive_buffer", {}),
            ("receive_json", {}),
            ("receive_with_metadata", {}),
            ("send_json", {"data": {}}),
            ("send_multiple", {"datagrams": [b"a"]}),
        ],
    )
    async def test_uninitialized_transport_raises_error(
        self, mock_session: Any, method_name: str, kwargs: dict[str, Any]
    ) -> None:
        transport = WebTransportDatagramTransport(session=mock_session)
        method = getattr(transport, method_name)
        with pytest.raises(DatagramError, match="not initialized"):
            if asyncio.iscoroutinefunction(method):
                await method(**kwargs)
            else:
                method(**kwargs)

    def test_buffer_size_uninitialized(self, mock_session: Any) -> None:
        transport = WebTransportDatagramTransport(session=mock_session)
        assert transport.get_send_buffer_size() == 0
        assert transport.get_receive_buffer_size() == 0

    @pytest.mark.parametrize(
        "setup_func, expected_issue",
        [
            (_setup_high_drop_rate, "High drop rate"),
            (_setup_queue_nearly_full, "Outgoing queue nearly full"),
            (_setup_incoming_queue_nearly_full, "Incoming queue nearly full"),
            (_setup_high_send_latency, "High send latency"),
            (_setup_transport_closed, "Datagram transport is closed"),
            (_setup_session_not_ready, "Session not available or not ready"),
        ],
    )
    @pytest.mark.asyncio
    async def test_diagnose_issues_comprehensive(
        self,
        transport: WebTransportDatagramTransport,
        setup_func: Callable[..., None],
        expected_issue: str,
        mocker: MockerFixture,
    ) -> None:
        if "session_not_ready" in setup_func.__name__ or "queue_nearly_full" in setup_func.__name__:
            setup_func(transport=transport, mocker=mocker)
        else:
            setup_func(transport=transport)

        issues = await transport.diagnose_issues()

        assert any(expected_issue in issue for issue in issues)
