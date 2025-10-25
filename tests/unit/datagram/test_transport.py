"""Unit tests for the pywebtransport.datagram.transport module."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from typing import Any, NoReturn, cast
from unittest.mock import MagicMock

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import DatagramError, TimeoutError, WebTransportDatagramTransport
from pywebtransport.datagram import DatagramMessage, DatagramStats, DatagramTransportDiagnostics
from pywebtransport.datagram.transport import _DatagramQueue
from pywebtransport.types import Data, EventType


@pytest.fixture
def mock_datagram_sender(mocker: MockerFixture) -> Callable[[bytes], None]:
    return cast(Callable[[bytes], None], mocker.Mock())


@asyncio_fixture
async def queue() -> AsyncGenerator[_DatagramQueue, None]:
    instance = _DatagramQueue(max_size=1000)
    await instance.initialize()
    yield instance
    await instance.close()


@asyncio_fixture
async def transport(
    mock_datagram_sender: Callable[[bytes], None],
) -> AsyncGenerator[WebTransportDatagramTransport, None]:
    instance = WebTransportDatagramTransport(
        session_id="test-session-id",
        datagram_sender=mock_datagram_sender,
        max_datagram_size=1200,
    )
    await instance.initialize()
    yield instance
    await instance.close()


class TestDatagramMessage:
    def test_age_and_is_expired(self, mocker: MockerFixture) -> None:
        mock_time = mocker.patch("pywebtransport.datagram.transport.get_timestamp")
        mock_time.return_value = 1000.0
        msg = DatagramMessage(data=b"ttl-test", ttl=10.0, timestamp=1000.0)

        assert msg.timestamp == 1000.0
        assert msg.age == 0.0
        assert not msg.is_expired

        mock_time.return_value = 1011.0
        assert msg.age == 11.0
        assert msg.is_expired

    def test_is_expired_no_ttl(self) -> None:
        msg = DatagramMessage(data=b"no-ttl")

        assert not msg.is_expired

    def test_post_init(self) -> None:
        msg = DatagramMessage(data=b"hello")

        assert msg.size == 5
        assert isinstance(msg.checksum, str)

    def test_post_init_with_checksum(self) -> None:
        msg = DatagramMessage(data=b"world", checksum="pre-computed")

        assert msg.checksum == "pre-computed"

    def test_to_dict(self) -> None:
        msg = DatagramMessage(data=b"data", ttl=60)

        data = msg.to_dict()

        expected_keys = [
            "size",
            "timestamp",
            "age",
            "checksum",
            "sequence",
            "priority",
            "ttl",
            "is_expired",
        ]
        assert all(key in data for key in expected_keys)


class TestDatagramQueue:
    @pytest.mark.asyncio
    async def test_clear(self, queue: _DatagramQueue) -> None:
        await queue.put(datagram=DatagramMessage(data=b"data"))
        assert not queue.empty()

        await queue.clear()

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_cleanup_loop_uninitialized(self) -> None:
        queue = _DatagramQueue(max_age=0.01)
        await queue._cleanup_loop()

    @pytest.mark.asyncio
    async def test_cleanup_multiple_priorities(self, mocker: MockerFixture) -> None:
        mock_time = mocker.patch("pywebtransport.datagram.transport.get_timestamp")
        queue = _DatagramQueue(max_age=10)
        await queue.initialize()

        await queue.put(datagram=DatagramMessage(data=b"stale_p0", priority=0, timestamp=980.0))
        await queue.put(datagram=DatagramMessage(data=b"stale_p2", priority=2, timestamp=980.0))
        await queue.put(datagram=DatagramMessage(data=b"also_stale_p1", priority=1, timestamp=1000.0))
        await queue.put(datagram=DatagramMessage(data=b"fresh_p0", priority=0, timestamp=1005.0))

        assert queue.qsize() == 4

        mock_time.return_value = 1011.0
        queue._cleanup_expired()

        assert queue.qsize() == 1
        assert (await queue.get()).data == b"fresh_p0"
        await queue.close()

    def test_cleanup_with_no_max_age(self) -> None:
        queue = _DatagramQueue()
        queue._cleanup_expired()

    @pytest.mark.asyncio
    async def test_close_cancels_cleanup_task(self) -> None:
        queue = _DatagramQueue(max_age=0.01)
        await queue.initialize()
        cleanup_task = queue._cleanup_task
        assert cleanup_task is not None
        assert not cleanup_task.done()

        await queue.close()

        assert cleanup_task.done()
        assert cleanup_task.cancelled()

    @pytest.mark.asyncio
    async def test_get_nowait(self, queue: _DatagramQueue) -> None:
        assert await queue.get_nowait() is None

        msg = DatagramMessage(data=b"data")
        await queue.put(datagram=msg)
        assert await queue.get_nowait() is msg

        assert await queue.get_nowait() is None

    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        queue = _DatagramQueue(max_size=5)
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
    async def test_get_timeout(self, queue: _DatagramQueue) -> None:
        with pytest.raises(TimeoutError):
            await queue.get(timeout=0.01)

    @pytest.mark.asyncio
    async def test_get_waits_for_item(self, queue: _DatagramQueue) -> None:
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
    async def test_init_start_tasks_runtime_error(self, mocker: MockerFixture) -> None:
        def cleanup_and_raise(coro: Coroutine[Any, Any, None]) -> NoReturn:
            coro.close()
            raise RuntimeError("no loop")

        queue = _DatagramQueue(max_age=10.0)
        mocker.patch("asyncio.create_task", side_effect=cleanup_and_raise)
        await queue.initialize()
        assert queue._cleanup_task is None
        await queue.close()

    @pytest.mark.asyncio
    async def test_max_size_limit_eviction(self) -> None:
        queue = _DatagramQueue(max_size=2)
        await queue.initialize()
        await queue.put(datagram=DatagramMessage(data=b"1"))
        await queue.put(datagram=DatagramMessage(data=b"2"))

        assert await queue.put(datagram=DatagramMessage(data=b"3")) is True
        datas = {(await queue.get()).data, (await queue.get()).data}

        assert datas == {b"2", b"3"}
        await queue.close()

    @pytest.mark.asyncio
    async def test_priority(self, queue: _DatagramQueue) -> None:
        await queue.put(datagram=DatagramMessage(data=b"low", priority=0))
        await queue.put(datagram=DatagramMessage(data=b"high", priority=2))
        await queue.put(datagram=DatagramMessage(data=b"mid", priority=1))

        assert (await queue.get()).data == b"high"
        assert (await queue.get()).data == b"mid"
        assert (await queue.get()).data == b"low"

    @pytest.mark.asyncio
    async def test_put_expired_datagram(self, mocker: MockerFixture, queue: _DatagramQueue) -> None:
        mock_time = mocker.patch("pywebtransport.datagram.transport.get_timestamp")
        mock_time.return_value = 1000.0
        expired_msg = DatagramMessage(data=b"expired", ttl=5, timestamp=990.0)

        assert await queue.put(datagram=expired_msg) is False
        assert queue.empty()
        assert await queue.put_nowait(datagram=expired_msg) is False
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_put_get(self, queue: _DatagramQueue) -> None:
        msg = DatagramMessage(data=b"data")

        assert await queue.put(datagram=msg) is True
        retrieved_msg = await queue.get()

        assert retrieved_msg is msg

    @pytest.mark.asyncio
    @pytest.mark.parametrize("put_method_name", ["put", "put_nowait"])
    async def test_queue_put_full_no_evict_candidate(self, put_method_name: str) -> None:
        queue = _DatagramQueue(max_size=1)
        await queue.initialize()
        await queue.put(datagram=DatagramMessage(data=b"p1", priority=1))

        put_method = cast(Callable[..., Coroutine[Any, Any, bool]], getattr(queue, put_method_name))
        assert await put_method(datagram=DatagramMessage(data=b"p2", priority=2)) is False
        assert queue.qsize() == 1
        assert (await queue.get_nowait()).data == b"p1"  # type: ignore[union-attr]
        await queue.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("get", {}),
            ("get_nowait", {}),
            ("put", {"datagram": DatagramMessage(data=b"d")}),
            ("put_nowait", {"datagram": DatagramMessage(data=b"d")}),
            ("clear", {}),
        ],
    )
    async def test_uninitialized_queue_raises_error(self, method_name: str, kwargs: dict[str, Any]) -> None:
        queue = _DatagramQueue()
        method = getattr(queue, method_name)
        with pytest.raises(DatagramError, match="not been initialized"):
            if asyncio.iscoroutinefunction(method):
                await method(**kwargs)
            else:
                method(**kwargs)


class TestDatagramStats:
    def test_avg_datagram_size(self) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        stats.datagrams_sent = 2
        stats.datagrams_received = 3
        stats.total_datagram_size = 500

        assert stats.avg_datagram_size == 100.0

        stats.datagrams_sent = 0
        stats.datagrams_received = 0
        stats.total_datagram_size = 500
        assert stats.avg_datagram_size == 500.0

    @pytest.mark.parametrize("received, total_time, expected", [(20, 5.0, 0.25), (0, 0.0, 0.0)])
    def test_avg_receive_time(self, received: int, total_time: float, expected: float) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        stats.datagrams_received = received
        stats.total_receive_time = total_time

        assert stats.avg_receive_time == expected

    @pytest.mark.parametrize("sent, total_time, expected", [(10, 2.0, 0.2), (0, 0.0, 0.0), (1, 0, 0)])
    def test_avg_send_time(self, sent: int, total_time: float, expected: float) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        stats.datagrams_sent = sent
        stats.total_send_time = total_time

        assert stats.avg_send_time == expected

    def test_initialization(self) -> None:
        stats = DatagramStats(session_id="sid", created_at=123.0)

        assert stats.session_id == "sid"
        assert stats.datagrams_sent == 0

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


class TestDatagramTransportDiagnostics:
    @pytest.mark.parametrize(
        "stats_kwargs, queue_kwargs, is_closed, expected_issue_part",
        [
            (
                {"send_failures": 20, "datagrams_sent": 80},
                {},
                False,
                "Low send success rate",
            ),
            ({"send_drops": 11, "datagrams_sent": 89}, {}, False, "High drop rate"),
            (
                {},
                {"outgoing": {"size": 95, "max_size": 100}},
                False,
                "Outgoing queue nearly full",
            ),
            (
                {},
                {"incoming": {"size": 95, "max_size": 100}},
                False,
                "Incoming queue nearly full",
            ),
            (
                {"total_send_time": 25.0, "datagrams_sent": 100},
                {},
                False,
                "High send latency",
            ),
            ({}, {}, True, "Datagram transport is closed"),
            ({}, {}, False, None),
        ],
    )
    def test_issues_property(
        self,
        stats_kwargs: dict[str, Any],
        queue_kwargs: dict[str, Any],
        is_closed: bool,
        expected_issue_part: str | None,
    ) -> None:
        stats = DatagramStats(session_id="sid", created_at=0, **stats_kwargs)
        diagnostics = DatagramTransportDiagnostics(stats=stats, queue_stats=queue_kwargs, is_closed=is_closed)

        issues = diagnostics.issues

        if expected_issue_part:
            assert any(expected_issue_part in issue for issue in issues)
        else:
            assert not issues

    def test_issues_property_zero_max_size_queues(self) -> None:
        stats = DatagramStats(session_id="sid", created_at=0)
        queue_stats = {
            "outgoing": {"size": 95, "max_size": 0},
            "incoming": {"size": 95, "max_size": 0},
        }
        diagnostics = DatagramTransportDiagnostics(stats=stats, queue_stats=queue_stats, is_closed=False)
        assert not diagnostics.issues


class TestWebTransportDatagramTransport:
    @pytest.mark.asyncio
    async def test_async_context_manager(self, mock_datagram_sender: Callable[[bytes], None]) -> None:
        transport = WebTransportDatagramTransport(
            session_id="sid", datagram_sender=mock_datagram_sender, max_datagram_size=1200
        )
        await transport.initialize()

        async with transport:
            assert not transport.is_closed

        assert transport.is_closed

    @pytest.mark.asyncio
    async def test_clear_and_get_buffer_size(self, transport: WebTransportDatagramTransport) -> None:
        uninitialized = WebTransportDatagramTransport(
            session_id="s", datagram_sender=lambda d: None, max_datagram_size=1
        )
        try:
            with pytest.raises(DatagramError):
                await uninitialized.clear_receive_buffer()
            with pytest.raises(DatagramError):
                await uninitialized.clear_send_buffer()
            assert uninitialized.get_receive_buffer_size() == 0
            assert uninitialized.get_send_buffer_size() == 0
        finally:
            await uninitialized.close()

        await transport.send(data=b"1")
        await transport.receive_from_protocol(data=b"2")
        await asyncio.sleep(0.01)
        assert transport.get_send_buffer_size() == 0
        assert transport.get_receive_buffer_size() == 1

        assert await transport.clear_send_buffer() == 0
        assert await transport.clear_receive_buffer() == 1
        assert transport.get_send_buffer_size() == 0
        assert transport.get_receive_buffer_size() == 0

    @pytest.mark.asyncio
    async def test_close_no_task(self, transport: WebTransportDatagramTransport) -> None:
        await transport.close()

    @pytest.mark.asyncio
    async def test_close_stops_background_tasks_and_is_idempotent(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        blocker = asyncio.Event()
        assert transport._outgoing_queue is not None
        mocker.patch.object(transport._outgoing_queue, "get", side_effect=blocker.wait)
        spy_disable_heartbeat = mocker.spy(transport, "disable_heartbeat")

        transport.enable_heartbeat(interval=10)
        await asyncio.sleep(0)

        sender_task = transport._sender_task
        heartbeat_task = transport._heartbeat_task
        assert sender_task is not None and not sender_task.done()
        assert heartbeat_task is not None and not heartbeat_task.done()

        await transport.close()
        await asyncio.sleep(0)

        assert sender_task.done()
        assert heartbeat_task.done()
        spy_disable_heartbeat.assert_called_once()

        await transport.close()
        spy_disable_heartbeat.assert_called_once()

    @pytest.mark.asyncio
    async def test_closed_transport_raises_error(self, transport: WebTransportDatagramTransport) -> None:
        await transport.close()
        with pytest.raises(DatagramError, match="transport is closed"):
            await transport.receive()
        with pytest.raises(DatagramError, match="transport is closed"):
            await transport.send(data=b"")
        with pytest.raises(DatagramError, match="transport is closed"):
            await transport.receive_with_metadata()
        assert await transport.try_receive() is None
        assert not await transport.try_send(data=b"")

    @pytest.mark.asyncio
    async def test_diagnostics(self, transport: WebTransportDatagramTransport) -> None:
        diagnostics = transport.diagnostics
        assert isinstance(diagnostics, DatagramTransportDiagnostics)
        assert diagnostics.stats is transport._stats
        assert "outgoing" in diagnostics.queue_stats

    @pytest.mark.asyncio
    async def test_heartbeat_api(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        spy_create_task = mocker.spy(asyncio, "create_task")
        transport.enable_heartbeat(interval=10)

        spy_create_task.assert_called_once()
        heartbeat_task = transport._heartbeat_task
        assert heartbeat_task is not None

        transport.enable_heartbeat(interval=20)
        assert transport._heartbeat_task is heartbeat_task

        await transport.disable_heartbeat()
        assert transport._heartbeat_task is None

    @pytest.mark.asyncio
    async def test_heartbeat_loop_errors(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        send_mock = mocker.patch.object(transport, "send", side_effect=DatagramError("send failed"))
        transport.enable_heartbeat(interval=0.01)
        with caplog.at_level(logging.WARNING):
            await asyncio.sleep(0.05)
            assert "Failed to send heartbeat" in caplog.text
        assert send_mock.call_count > 0
        await transport.disable_heartbeat()

        caplog.clear()
        send_mock = mocker.patch.object(transport, "send", side_effect=Exception("generic error"))
        transport.enable_heartbeat(interval=0.01)
        with caplog.at_level(logging.ERROR):
            await asyncio.sleep(0.05)
            assert "Heartbeat loop error" in caplog.text
        assert send_mock.call_count > 0

    @pytest.mark.asyncio
    async def test_init_start_tasks_runtime_error(
        self,
        mock_datagram_sender: Callable[[bytes], None],
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        def cleanup_and_raise(coro: Coroutine[Any, Any, None]) -> NoReturn:
            coro.close()
            raise RuntimeError("no loop")

        transport = WebTransportDatagramTransport(
            session_id="sid", datagram_sender=mock_datagram_sender, max_datagram_size=1200
        )
        try:
            mocker.patch("asyncio.create_task", side_effect=cleanup_and_raise)
            with caplog.at_level(logging.WARNING):
                await transport.initialize()
                assert "Could not start datagram background tasks" in caplog.text
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        spy_start_tasks = mocker.spy(transport, "_start_background_tasks")
        await transport.initialize()
        spy_start_tasks.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialization_and_defaults(self, mock_datagram_sender: Callable[[bytes], None]) -> None:
        transport = WebTransportDatagramTransport(
            session_id="sid",
            datagram_sender=mock_datagram_sender,
            max_datagram_size=1200,
            high_water_mark=50,
        )
        try:
            assert transport.session_id == "sid"
            assert transport.outgoing_high_water_mark == 50
        finally:
            await transport.close()

    def test_properties(self, transport: WebTransportDatagramTransport) -> None:
        assert transport.session_id == "test-session-id"
        assert transport.is_readable
        assert transport.is_writable
        assert transport.bytes_received == 0
        assert transport.bytes_sent == 0
        assert transport.datagrams_received == 0
        assert transport.datagrams_sent == 0
        assert transport.incoming_max_age is None
        assert transport.max_datagram_size == 1200
        assert transport.outgoing_high_water_mark == 100
        assert transport.outgoing_max_age is None
        assert transport.receive_sequence == 0
        assert transport.send_sequence == 0

    def test_get_queue_stats_uninitialized(self, mock_datagram_sender: Callable[[bytes], None]) -> None:
        transport = WebTransportDatagramTransport(
            session_id="sid", datagram_sender=mock_datagram_sender, max_datagram_size=1200
        )
        stats = transport.diagnostics.queue_stats
        assert stats == {"outgoing": {}, "incoming": {}}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload, exception",
        [
            (b'{"a":1}', None),
            (b"not-json", DatagramError),
            ("你好".encode("gbk"), DatagramError),
        ],
    )
    async def test_receive_json(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        payload: bytes,
        exception: type[Exception] | None,
    ) -> None:
        mocker.patch.object(transport, "receive", new_callable=mocker.AsyncMock, return_value=payload)

        if exception:
            with pytest.raises(exception, match="Failed to parse JSON datagram"):
                await transport.receive_json()
        else:
            assert await transport.receive_json() == {"a": 1}

    @pytest.mark.asyncio
    async def test_receive_json_raises_timeout_and_other_errors(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(transport, "receive", side_effect=TimeoutError("timeout"))
        with pytest.raises(TimeoutError):
            await transport.receive_json()

        mocker.patch.object(transport, "receive", side_effect=ValueError("other"))
        with pytest.raises(DatagramError, match="Failed to receive JSON datagram"):
            await transport.receive_json()

    @pytest.mark.asyncio
    async def test_receive_multiple(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        mock_receive = mocker.patch.object(transport, "receive", new_callable=mocker.AsyncMock, return_value=b"first")
        mock_try_receive = mocker.patch.object(
            transport,
            "try_receive",
            new_callable=mocker.AsyncMock,
            side_effect=[b"second", None],
        )

        results = await transport.receive_multiple(max_count=5)
        assert results == [b"first", b"second"]
        mock_receive.assert_called_once()
        assert mock_try_receive.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "side_effect, expected_result, should_raise",
        [
            ([b"first", TimeoutError("timeout")], [b"first"], False),
            (TimeoutError("timeout"), [], True),
        ],
    )
    async def test_receive_multiple_timeout_scenarios(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        side_effect: list[Any] | Exception,
        expected_result: list[bytes],
        should_raise: bool,
    ) -> None:
        mocker.patch.object(transport, "receive", side_effect=side_effect)

        if should_raise:
            with pytest.raises(TimeoutError):
                await transport.receive_multiple(max_count=5, timeout=0.1)
        else:
            results = await transport.receive_multiple(max_count=5, timeout=0.1)
            assert results == expected_result

    @pytest.mark.asyncio
    async def test_receive_with_metadata(self, transport: WebTransportDatagramTransport) -> None:
        await transport.receive_from_protocol(data=b"meta-test")
        result = await transport.receive_with_metadata()
        assert result["data"] == b"meta-test"
        assert result["metadata"]["size"] == 9

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "raised_exception, expected_exception",
        [
            (TimeoutError("timeout"), TimeoutError),
            (ValueError, DatagramError),
        ],
    )
    async def test_receive_with_metadata_exceptions(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        raised_exception: Exception,
        expected_exception: type[Exception],
    ) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._incoming_queue, "get", side_effect=raised_exception)
        with pytest.raises(expected_exception):
            await transport.receive_with_metadata()

    @pytest.mark.asyncio
    async def test_receive_from_protocol_and_receive(
        self, transport: WebTransportDatagramTransport, mocker: MockerFixture
    ) -> None:
        spy_emit = mocker.spy(transport, "emit")
        await transport.receive_from_protocol(data=b"incoming")

        data = await transport.receive()
        assert data == b"incoming"
        assert transport.datagrams_received == 1

        spy_emit.assert_called_once()
        assert spy_emit.call_args.kwargs["event_type"] == EventType.DATAGRAM_RECEIVED

    @pytest.mark.asyncio
    async def test_receive_from_protocol_drop_and_error(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        assert transport._incoming_queue is not None
        mocker.patch.object(transport._incoming_queue, "put", new_callable=mocker.AsyncMock, return_value=False)
        await transport.receive_from_protocol(data=b"dropped")
        assert transport.diagnostics.stats.receive_drops == 1

        mocker.patch.object(transport._incoming_queue, "put", side_effect=Exception("Queue error"))
        with caplog.at_level(logging.ERROR):
            await transport.receive_from_protocol(data=b"error")
            assert "Error handling received datagram" in caplog.text
            assert transport.diagnostics.stats.receive_errors == 1

    @pytest.mark.asyncio
    async def test_receive_from_protocol_uninitialized(
        self,
        mock_datagram_sender: Callable[[bytes], None],
    ) -> None:
        transport = WebTransportDatagramTransport(
            session_id="sid", datagram_sender=mock_datagram_sender, max_datagram_size=1200
        )
        try:
            await transport.receive_from_protocol(data=b"should-be-ignored")
            assert transport.get_receive_buffer_size() == 0
        finally:
            await transport.close()

    @pytest.mark.asyncio
    async def test_send_and_sender_loop(
        self,
        transport: WebTransportDatagramTransport,
        mock_datagram_sender: Callable[[bytes], None],
        mocker: MockerFixture,
    ) -> None:
        spy_emit = mocker.spy(transport, "emit")
        await transport.send(data=b"data")
        await asyncio.sleep(0.01)

        cast(MagicMock, mock_datagram_sender).assert_called_once_with(b"data")
        assert transport.datagrams_sent == 1
        assert transport.diagnostics.stats.max_send_time > 0.0
        spy_emit.assert_called_once()
        assert spy_emit.call_args.kwargs["event_type"] == EventType.DATAGRAM_SENT

    @pytest.mark.asyncio
    async def test_send_failures(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        with pytest.raises(DatagramError):
            await transport.send(data=b"a" * 2000)

        assert transport._outgoing_queue is not None
        mocker.patch.object(transport._outgoing_queue, "put", new_callable=mocker.AsyncMock, return_value=False)
        with pytest.raises(DatagramError, match="Outgoing datagram queue full"):
            await transport.send(data=b"dropped")
        assert transport.diagnostics.stats.send_drops == 1

    @pytest.mark.asyncio
    async def test_send_json_error(self, transport: WebTransportDatagramTransport) -> None:
        with pytest.raises(DatagramError, match="Failed to serialize JSON"):
            await transport.send_json(data=object())

    @pytest.mark.asyncio
    async def test_send_multiple_empty(self, transport: WebTransportDatagramTransport) -> None:
        sent_count = await transport.send_multiple(datagrams=[])
        assert sent_count == 0

    @pytest.mark.asyncio
    async def test_send_multiple_partial_failure(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        mocker.patch.object(transport, "send", side_effect=[None, DatagramError("send fail"), None])
        datagrams: list[Data] = [b"1", b"2", b"3"]
        with caplog.at_level(logging.WARNING):
            sent_count = await transport.send_multiple(datagrams=datagrams)
            assert sent_count == 1
            assert "Failed to send datagram 2" in caplog.text

    @pytest.mark.asyncio
    async def test_send_multiple_success(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        spy_send = mocker.spy(transport, "send")
        datagrams: list[Data] = [b"1", b"2", b"3"]
        sent_count = await transport.send_multiple(datagrams=datagrams)
        assert sent_count == len(datagrams)
        assert spy_send.call_count == len(datagrams)

    @pytest.mark.asyncio
    async def test_sender_loop_errors(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        assert transport._outgoing_queue is not None
        mocker.patch.object(transport._outgoing_queue, "get", side_effect=TimeoutError("timeout"))
        mocker.patch.object(transport, "_closed", side_effect=[False, True])
        await transport._sender_loop()

        mocker.patch.object(transport, "_closed", False)
        mocker.patch.object(transport._outgoing_queue, "get", side_effect=Exception("generic error"))
        with caplog.at_level(logging.ERROR):
            await transport._sender_loop()
            assert "Sender loop fatal error" in caplog.text

    @pytest.mark.asyncio
    async def test_sender_loop_send_error(
        self,
        transport: WebTransportDatagramTransport,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        assert transport._outgoing_queue is not None
        await transport._outgoing_queue.put(datagram=DatagramMessage(data=b"fail_send"))
        mocker.patch.object(transport, "_datagram_sender", side_effect=ValueError("Send Error"))

        with caplog.at_level(logging.WARNING):
            await asyncio.sleep(0.01)
            assert "Failed to send datagram" in caplog.text
            assert transport.diagnostics.stats.send_failures == 1

    def test_str_representation(self, transport: WebTransportDatagramTransport) -> None:
        assert str(transport).startswith("DatagramTransport(test-session...")

    @pytest.mark.asyncio
    async def test_str_with_data(self, transport: WebTransportDatagramTransport) -> None:
        await transport.send(data=b"data")
        await transport.receive_from_protocol(data=b"incoming")
        await transport.receive()
        await asyncio.sleep(0.01)
        summary = str(transport)
        assert "sent=1" in summary
        assert "received=1" in summary
        assert "avg_size=6B" in summary

    @pytest.mark.asyncio
    async def test_str_with_failures(self, transport: WebTransportDatagramTransport, mocker: MockerFixture) -> None:
        assert transport._outgoing_queue is not None
        mocker.patch.object(transport, "_datagram_sender", side_effect=ValueError)
        await transport._outgoing_queue.put(datagram=DatagramMessage(data=b"bad"))
        await asyncio.sleep(0.01)
        assert "success_rate=0.00%" in str(transport)

    @pytest.mark.asyncio
    async def test_try_send_and_receive(self, transport: WebTransportDatagramTransport) -> None:
        assert await transport.try_send(data=b"try-it")
        await asyncio.sleep(0.01)
        await transport.receive_from_protocol(data=b"receive-it")

        data = await transport.try_receive()
        assert data == b"receive-it"
        assert await transport.try_receive() is None

        assert not await transport.try_send(data=b"a" * 2000)
        assert transport.diagnostics.stats.send_drops == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs, is_async",
        [
            ("send", {"data": b""}, True),
            ("send_json", {"data": {}}, True),
            ("send_multiple", {"datagrams": []}, True),
            ("receive", {}, True),
            ("receive_json", {}, True),
            ("receive_multiple", {}, True),
            ("receive_with_metadata", {}, True),
            ("enable_heartbeat", {}, False),
            ("try_receive", {}, True),
            ("try_send", {"data": b"d"}, True),
            ("clear_receive_buffer", {}, True),
            ("clear_send_buffer", {}, True),
            ("_start_background_tasks", {}, False),
        ],
    )
    async def test_uninitialized_calls(
        self,
        mock_datagram_sender: Callable[[bytes], None],
        method_name: str,
        kwargs: dict[str, Any],
        is_async: bool,
    ) -> None:
        transport = WebTransportDatagramTransport(
            session_id="sid", datagram_sender=mock_datagram_sender, max_datagram_size=1200
        )
        method = getattr(transport, method_name)

        if method_name in ("_start_background_tasks",):
            assert method(**kwargs) is None
            return

        with pytest.raises(DatagramError, match="not initialized"):
            if is_async:
                await method(**kwargs)
            else:
                method(**kwargs)
