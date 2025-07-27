"""Unit tests for the pywebtransport.stream.stream module."""

import asyncio
from asyncio import IncompleteReadError
from typing import Any, Dict, List

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    Event,
    StreamDirection,
    StreamError,
    StreamState,
    TimeoutError,
    WebTransportReceiveStream,
    WebTransportSendStream,
    WebTransportStream,
)
from pywebtransport.stream import StreamBuffer, StreamStats
from pywebtransport.types import StreamId

TEST_STREAM_ID: StreamId = 123
DEFAULT_BUFFER_SIZE = 65536


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    session = mocker.MagicMock()
    session.connection = mocker.MagicMock()
    session.connection.config = mocker.MagicMock()
    session.connection.config.stream_buffer_size = DEFAULT_BUFFER_SIZE
    session.connection.config.read_timeout = 1.0
    session.connection.config.write_timeout = 1.0
    session.connection.config.max_stream_buffer_size = 1024 * 1024
    handler = mocker.MagicMock()
    handler.on = mocker.MagicMock()
    handler.off = mocker.MagicMock()
    handler.abort_stream = mocker.MagicMock()
    handler.send_webtransport_stream_data = mocker.MagicMock()
    session.protocol_handler = handler
    return session


class TestStreamStats:
    def test_stats_properties(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.get_timestamp", return_value=110.0)
        stats = StreamStats(stream_id=1, created_at=100.0)

        assert stats.avg_read_time == 0
        assert stats.avg_write_time == 0
        assert stats.uptime == 10.0

        stats.writes_count = 2
        stats.total_write_time = 5.0

        assert stats.avg_write_time == 2.5
        stats.closed_at = 120.0
        assert stats.uptime == 20.0

    def test_stats_to_dict(self) -> None:
        stats = StreamStats(stream_id=1, created_at=100.0, bytes_sent=50)

        stats_dict = stats.to_dict()

        assert isinstance(stats_dict, dict)
        assert stats_dict["stream_id"] == 1
        assert stats_dict["bytes_sent"] == 50


class TestStreamBuffer:
    @pytest.mark.asyncio
    async def test_feed_and_read_data(self) -> None:
        buffer = StreamBuffer()
        await buffer.feed_data(b"hello")

        data = await buffer.read(size=5)

        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_concurrent_read_and_feed(self) -> None:
        buffer = StreamBuffer()
        read_task = asyncio.create_task(buffer.read(size=4))

        await asyncio.sleep(0.01)
        assert not read_task.done()

        await buffer.feed_data(b"test")
        result = await read_task

        assert result == b"test"

    @pytest.mark.asyncio
    async def test_read_partial(self) -> None:
        buffer = StreamBuffer()
        await buffer.feed_data(b"hello world")

        data = await buffer.read(size=5)
        assert data == b"hello"

        remaining_data = await buffer.read(size=100)
        assert remaining_data == b" world"

    @pytest.mark.asyncio
    async def test_read_all_with_size_minus_one(self) -> None:
        buffer = StreamBuffer()
        await buffer.feed_data(b"part1")
        await buffer.feed_data(b"part2")

        data = await buffer.read(size=-1)

        assert data == b"part1part2"

    @pytest.mark.asyncio
    async def test_read_timeout(self, mocker: MockerFixture) -> None:
        buffer = StreamBuffer()
        mocker.patch.object(
            buffer._data_available, "wait", new_callable=mocker.AsyncMock, side_effect=asyncio.TimeoutError
        )

        with pytest.raises(TimeoutError):
            await buffer.read(size=1, timeout=0.1)

    @pytest.mark.asyncio
    async def test_eof_handling(self) -> None:
        buffer = StreamBuffer()
        await buffer.feed_data(b"final data", eof=True)

        data = await buffer.read(size=10)
        assert data == b"final data"
        assert buffer.at_eof

        extra_read = await buffer.read(size=10)
        assert extra_read == b""

    @pytest.mark.asyncio
    async def test_feed_data_after_eof(self) -> None:
        buffer = StreamBuffer()
        await buffer.feed_data(b"some", eof=True)
        await buffer.feed_data(b"more")

        content = await buffer.read(size=-1)

        assert content == b"some"

    @pytest.mark.asyncio
    async def test_feed_empty_data_with_eof(self) -> None:
        buffer = StreamBuffer()
        await buffer.feed_data(b"", eof=True)

        assert buffer.at_eof
        assert await buffer.read() == b""

    @pytest.mark.asyncio
    async def test_read_zero_size(self) -> None:
        buffer = StreamBuffer()
        await buffer.feed_data(b"hello")

        assert await buffer.read(size=0) == b""
        assert buffer.size == 5


class TestWebTransportReceiveStream:
    @pytest.mark.asyncio
    async def test_init(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)

        assert stream.stream_id == TEST_STREAM_ID
        expected_calls = [
            mocker.call(f"stream_data_received:{TEST_STREAM_ID}", stream._on_data_received),
            mocker.call(f"stream_closed:{TEST_STREAM_ID}", stream._on_stream_closed),
        ]
        mock_session.protocol_handler.on.assert_has_calls(expected_calls, any_order=True)

    @pytest.mark.asyncio
    async def test_init_no_handler(self, mock_session: Any) -> None:
        mock_session.protocol_handler = None
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream._session() is not None

    @pytest.mark.asyncio
    async def test_read_success(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.get_timestamp", return_value=100.0)
        mocker.patch("time.time", side_effect=[100.5, 101.0])
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream._buffer.feed_data(b"some data")

        data = await stream.read(size=9)

        assert data == b"some data"
        assert stream._stats.bytes_received == 9

    @pytest.mark.asyncio
    async def test_helper_read_methods(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream._buffer.feed_data(b"line1\nline2\nand more", eof=True)

        assert await stream.readline() == b"line1\n"
        assert await stream.readuntil(b"2") == b"line2"
        assert await stream.readexactly(3) == b"\nan"
        assert await stream.read_all() == b"d more"

    @pytest.mark.asyncio
    async def test_get_and_debug_summary(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)

        summary = stream.get_summary()
        debug_state = stream.debug_state()

        assert summary["stream_id"] == TEST_STREAM_ID
        assert "uptime" in summary
        assert debug_state["stream"]["id"] == TEST_STREAM_ID
        assert "statistics" in debug_state

    @pytest.mark.asyncio
    async def test_read_raises_timeout_error(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mocker.patch.object(stream._buffer, "read", side_effect=TimeoutError("test timeout"))

        with pytest.raises(TimeoutError, match="test timeout"):
            await stream.read()

    @pytest.mark.asyncio
    async def test_read_raises_stream_error_on_generic_exception(
        self, mock_session: Any, mocker: MockerFixture
    ) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mocker.patch.object(stream._buffer, "read", side_effect=ValueError("test error"))

        with pytest.raises(StreamError, match="Read operation failed: test error"):
            await stream.read()

        assert stream._stats.read_errors == 1

    @pytest.mark.asyncio
    async def test_read_all_exceeds_max_size(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream._buffer.feed_data(b"1234567890", eof=True)

        with pytest.raises(StreamError, match="Stream size exceeds maximum"):
            await stream.read_all(max_size=5)

    @pytest.mark.asyncio
    async def test_read_iter_and_break_on_error(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mocker.patch.object(stream, "read", side_effect=[b"chunk1", StreamError("read failed")])
        chunks = []

        async for chunk in stream.read_iter():
            chunks.append(chunk)

        assert chunks == [b"chunk1"]

    @pytest.mark.asyncio
    async def test_readexactly_incomplete_read(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream._buffer.feed_data(b"short", eof=True)

        with pytest.raises(IncompleteReadError):
            await stream.readexactly(10)

    @pytest.mark.asyncio
    async def test_readexactly_negative_n_raises_value_error(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        with pytest.raises(ValueError):
            await stream.readexactly(-1)

    @pytest.mark.asyncio
    async def test_readuntil_no_separator(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream._buffer.feed_data(b"no separator", eof=True)

        result = await stream.readuntil(b"Z")

        assert result == b"no separator"

    @pytest.mark.asyncio
    async def test_read_when_not_readable(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._set_state(StreamState.RESET_SENT)

        assert not stream.is_readable
        assert await stream.read() == b""

    @pytest.mark.asyncio
    async def test_on_data_received_empty_data(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream._buffer.feed_data(b"original")

        await stream._on_data_received(Event("test", None))

        assert stream._buffer.size == 8

    @pytest.mark.asyncio
    async def test_on_stream_closed_handler(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)

        await stream._on_stream_closed(Event("test", None))

        assert stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    async def test_abort(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)

        await stream.abort(code=99)

        mock_session.protocol_handler.abort_stream.assert_called_once_with(stream_id=TEST_STREAM_ID, error_code=99)
        assert stream.state == StreamState.RESET_SENT

    @pytest.mark.asyncio
    async def test_state_transition_on_end_stream(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream.state == StreamState.OPEN

        stream._set_state(StreamState.HALF_CLOSED_REMOTE)

        assert stream.state == StreamState.HALF_CLOSED_REMOTE

    @pytest.mark.asyncio
    async def test_set_state_no_change(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._teardown = mocker.MagicMock()

        stream._set_state(StreamState.OPEN)

        stream._teardown.assert_not_called()

    @pytest.mark.asyncio
    async def test_teardown(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._set_state(StreamState.CLOSED)

        await stream.wait_closed()

        expected_calls = [
            mocker.call(f"stream_data_received:{TEST_STREAM_ID}", stream._on_data_received),
            mocker.call(f"stream_closed:{TEST_STREAM_ID}", stream._on_stream_closed),
        ]
        mock_session.protocol_handler.off.assert_has_calls(expected_calls, any_order=True)


class TestWebTransportSendStream:
    @pytest.mark.asyncio
    async def test_init(self, mock_session: Any, mocker: MockerFixture) -> None:
        mock_ensure_writer = mocker.patch(
            "pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running"
        )

        WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)

        mock_ensure_writer.assert_called_once()

    @pytest.mark.asyncio
    async def test_populates_buffer(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)

        write_task = asyncio.create_task(stream.write(b"some payload"))
        await asyncio.sleep(0)

        assert len(stream._write_buffer) == 1
        assert stream._write_buffer[0]["data"] == b"some payload"
        write_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write_task

    @pytest.mark.asyncio
    async def test_write_chunking(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._WRITE_CHUNK_SIZE = 10

        write_task = asyncio.create_task(stream.write(b"a" * 25, end_stream=True))
        await asyncio.sleep(0)

        assert len(stream._write_buffer) == 3
        write_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write_task

    @pytest.mark.asyncio
    async def test_write_all(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream.write = mocker.AsyncMock()
        stream.close = mocker.AsyncMock()

        await stream.write_all(b"all the data", chunk_size=5)

        assert stream.write.call_count == 3
        stream.write.assert_has_calls([mocker.call(b"all t"), mocker.call(b"he da"), mocker.call(b"ta")])
        stream.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_empty_and_timeout(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._write_buffer.clear()

        await stream.flush()

        stream._write_buffer.append({"data": b"dummy", "future": asyncio.Future(), "end_stream": False})
        mocker.patch.object(
            stream._flushed_event, "wait", new_callable=mocker.AsyncMock, side_effect=asyncio.TimeoutError
        )

        with pytest.raises(TimeoutError, match="Flush timeout"):
            await stream.flush()

    @pytest.mark.asyncio
    async def test_write_all_error_handling(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream.write = mocker.AsyncMock(side_effect=StreamError("send failed"))
        stream.abort = mocker.AsyncMock()

        with pytest.raises(StreamError):
            await stream.write_all(b"some data")

        stream.abort.assert_called_once_with(code=1)

    @pytest.mark.asyncio
    async def test_write_backpressure_timeout(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._max_buffer_size = 10
        stream._backpressure_limit = 8
        mocker.patch.object(
            stream._backpressure_event, "wait", new_callable=mocker.AsyncMock, side_effect=asyncio.TimeoutError
        )

        with pytest.raises(TimeoutError, match="Write timeout due to backpressure"):
            await stream.write(b"123456789012345")

    @pytest.mark.asyncio
    async def test_write_not_writable(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._set_state(StreamState.CLOSED)

        with pytest.raises(StreamError):
            await stream.write(b"data")

    @pytest.mark.asyncio
    async def test_write_empty_data_no_end_stream(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)

        await stream.write(b"", end_stream=False)

        assert len(stream._write_buffer) == 0

    @pytest.mark.asyncio
    async def test_write_empty_data_with_end_stream(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)

        write_task = asyncio.create_task(stream.write(b"", end_stream=True))
        await asyncio.sleep(0)

        assert len(stream._write_buffer) == 1
        assert stream._write_buffer[0]["data"] == b""
        assert stream._write_buffer[0]["end_stream"]

        write_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write_task

    @pytest.mark.asyncio
    async def test_close_ignores_stream_error(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream.write = mocker.AsyncMock(side_effect=StreamError("write failed"))

        await stream.close()

        stream.write.assert_called_once_with(b"", end_stream=True)

    @pytest.mark.asyncio
    async def test_writer_loop_integration(self, mock_session: Any) -> None:
        send_called_event = asyncio.Event()

        def side_effect(*args, **kwargs):
            send_called_event.set()

        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = side_effect
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        asyncio.create_task(stream.write(b"data"))

        try:
            await asyncio.wait_for(send_called_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pytest.fail("The writer loop did not call send_webtransport_stream_data within the timeout.")

        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_once_with(
            stream_id=TEST_STREAM_ID, data=b"data", end_stream=False
        )
        assert stream._writer_task is not None
        stream._set_state(StreamState.CLOSED)
        stream._writer_task.cancel()
        await asyncio.sleep(0)
        assert stream._writer_task.done()

    @pytest.mark.asyncio
    async def test_writer_loop_handles_send_exception(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = ValueError("send failed")

        write_task = asyncio.create_task(stream.write(b"data"))

        with pytest.raises(ValueError):
            await write_task
        assert stream.state == StreamState.RESET_SENT
        assert stream._stats.write_errors == 1

    @pytest.mark.asyncio
    async def test_writer_loop_no_session(self, mock_session: Any, mocker: MockerFixture) -> None:
        mock_session.protocol_handler = None
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        sleep_called = asyncio.Event()
        original_sleep = asyncio.sleep

        async def sleep_side_effect(delay):
            sleep_called.set()
            await original_sleep(delay)

        mocker.patch("asyncio.sleep", side_effect=sleep_side_effect)
        try:
            await asyncio.wait_for(sleep_called.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pytest.fail("Writer loop did not enter sleep state when handler was missing.")

        assert stream._writer_task is not None
        stream._set_state(StreamState.CLOSED)
        stream._writer_task.cancel()
        await asyncio.sleep(0)
        assert stream._writer_task.done()


class TestWebTransportStream:
    @pytest.mark.asyncio
    async def test_init(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")

        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)

        assert stream.direction == StreamDirection.BIDIRECTIONAL.value
        assert hasattr(stream, "read") and hasattr(stream, "write")

    @pytest.mark.asyncio
    async def test_close_calls_sendstream_close(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        mock_send_close = mocker.patch(
            "pywebtransport.stream.stream.WebTransportSendStream.close", new_callable=mocker.AsyncMock
        )
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)

        await stream.close()

        mock_send_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_bidirectional_stream_closes_correctly(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)

        stream._state = StreamState.HALF_CLOSED_LOCAL
        stream._set_state(StreamState.CLOSED)

        assert stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    async def test_monitor_health(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mock_logger_warning = mocker.patch("pywebtransport.stream.stream.logger.warning")
        stream._stats.reads_count = 100
        stream._stats.read_errors = 20

        monitor_task = asyncio.create_task(stream.monitor_health(check_interval=0.01))
        await asyncio.sleep(0.05)

        mock_logger_warning.assert_called()
        stream._set_state(StreamState.CLOSED)
        monitor_task.cancel()
        await asyncio.sleep(0)
        assert monitor_task.done()

    @pytest.mark.asyncio
    async def test_monitor_health_handles_exceptions(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mock_logger_error = mocker.patch("pywebtransport.stream.stream.logger.error")
        mocker.patch("asyncio.sleep", side_effect=ValueError("test error"))

        await stream.monitor_health()

        mock_logger_error.assert_called_with("Stream health monitoring error: test error")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state, stats_attrs, expected_issues",
        [
            (StreamState.OPEN, {"reads_count": 20, "read_errors": 5}, ["High read error rate: 5/20"]),
            (StreamState.RESET_RECEIVED, {}, ["Stream was reset by remote peer"]),
            (StreamState.RESET_SENT, {}, ["Stream was reset locally"]),
            (StreamState.OPEN, {"writes_count": 20, "write_errors": 5}, ["High write error rate: 5/20"]),
            (StreamState.OPEN, {"reads_count": 15, "total_read_time": 37.5}, ["Slow read operations: 2.50s average"]),
            (
                StreamState.OPEN,
                {"writes_count": 15, "total_write_time": 37.5},
                ["Slow write operations: 2.50s average"],
            ),
            (
                StreamState.OPEN,
                {"created_at": 1000.0, "closed_at": None, "reads_count": 0, "writes_count": 0},
                ["Stream appears stale (long uptime with no activity)"],
            ),
        ],
    )
    async def test_diagnose_issues(
        self,
        mock_session: Any,
        mocker: MockerFixture,
        state: StreamState,
        stats_attrs: Dict[str, Any],
        expected_issues: List[str],
    ) -> None:
        mocker.patch("pywebtransport.stream.stream.WebTransportSendStream._ensure_writer_is_running")
        mocker.patch("pywebtransport.stream.stream.get_timestamp", return_value=5000.0)
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._state = state
        for key, value in stats_attrs.items():
            setattr(stream._stats, key, value)

        issues = await stream.diagnose_issues(latency_threshold=2.0, error_rate_threshold=0.2)

        assert issues == expected_issues
