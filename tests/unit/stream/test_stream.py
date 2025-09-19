"""Unit tests for the pywebtransport.stream.stream module."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import suppress
from typing import Any, Type

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    Event,
    FlowControlError,
    StreamDirection,
    StreamError,
    StreamId,
    StreamState,
    TimeoutError,
    WebTransportReceiveStream,
    WebTransportSendStream,
    WebTransportStream,
)
from pywebtransport.stream import StreamBuffer, StreamStats

DEFAULT_BUFFER_SIZE = 65536
TEST_STREAM_ID: StreamId = 123


@pytest.fixture
async def bidirectional_stream(mock_session: Any) -> AsyncGenerator[WebTransportStream, None]:
    stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
    await stream.initialize()
    yield stream
    if stream._writer_task and not stream._writer_task.done():
        stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream._writer_task


@pytest.fixture
async def buffer() -> AsyncGenerator[StreamBuffer, None]:
    buf = StreamBuffer(max_size=DEFAULT_BUFFER_SIZE)
    await buf.initialize()
    yield buf


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
    session.protocol_handler = handler
    session.is_closed = False
    session._data_credit_event = asyncio.Event()
    return session


@pytest.fixture
async def receive_stream(mock_session: Any) -> AsyncGenerator[WebTransportReceiveStream, None]:
    stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
    await stream.initialize()
    yield stream


@pytest.fixture
async def send_stream(mock_session: Any) -> AsyncGenerator[WebTransportSendStream, None]:
    stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
    await stream.initialize()
    yield stream
    if stream._writer_task and not stream._writer_task.done():
        stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream._writer_task


class TestStreamStats:
    def test_stats_properties(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.get_timestamp", return_value=110.0)
        stats = StreamStats(stream_id=1, created_at=100.0)

        assert stats.avg_read_time == 0
        assert stats.avg_write_time == 0
        assert stats.uptime == 10.0

        stats.reads_count = 1
        stats.total_read_time = 0.5
        stats.writes_count = 2
        stats.total_write_time = 5.0
        assert stats.avg_read_time == 0.5
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
    async def test_initialize_idempotent(self, buffer: StreamBuffer) -> None:
        assert buffer._lock is not None
        lock_id = id(buffer._lock)

        await buffer.initialize()

        assert id(buffer._lock) == lock_id

    @pytest.mark.asyncio
    async def test_feed_and_read_data(self, buffer: StreamBuffer) -> None:
        await buffer.feed_data(data=b"hello")

        data, eof = await buffer.read(size=5)

        assert data == b"hello"
        assert not eof

    @pytest.mark.asyncio
    async def test_concurrent_read_and_feed(self, buffer: StreamBuffer) -> None:
        read_task = asyncio.create_task(buffer.read(size=4))
        await asyncio.sleep(0.01)
        assert not read_task.done()

        await buffer.feed_data(data=b"test")
        result, eof = await read_task

        assert result == b"test"
        assert not eof

    @pytest.mark.asyncio
    async def test_read_partial(self, buffer: StreamBuffer) -> None:
        await buffer.feed_data(data=b"hello world")

        data, eof1 = await buffer.read(size=5)
        assert data == b"hello"
        assert not eof1

        remaining_data, eof2 = await buffer.read(size=100)
        assert remaining_data == b" world"
        assert not eof2

    @pytest.mark.asyncio
    async def test_read_all_with_size_minus_one(self, buffer: StreamBuffer) -> None:
        await buffer.feed_data(data=b"part1")
        await buffer.feed_data(data=b"part2")

        data, eof = await buffer.read(size=-1)

        assert data == b"part1part2"
        assert not eof

    @pytest.mark.asyncio
    async def test_read_zero_size(self, buffer: StreamBuffer) -> None:
        await buffer.feed_data(data=b"hello")

        result, eof = await buffer.read(size=0)

        assert result == b""
        assert not eof
        assert buffer.size == 5

    @pytest.mark.asyncio
    async def test_eof_handling(self, buffer: StreamBuffer) -> None:
        await buffer.feed_data(data=b"final data", eof=True)

        data, eof = await buffer.read(size=10)
        assert data == b"final data"
        assert eof
        assert buffer.at_eof

        extra_read, extra_eof = await buffer.read(size=10)
        assert extra_read == b""
        assert extra_eof

    @pytest.mark.asyncio
    async def test_feed_data_after_eof(self, buffer: StreamBuffer) -> None:
        await buffer.feed_data(data=b"some", eof=True)

        await buffer.feed_data(data=b"more")
        content, eof = await buffer.read(size=-1)

        assert content == b"some"
        assert eof

    @pytest.mark.asyncio
    async def test_feed_empty_data_with_eof(self, buffer: StreamBuffer) -> None:
        await buffer.feed_data(data=b"", eof=True)

        assert buffer.at_eof
        data, eof = await buffer.read()
        assert data == b""
        assert eof

    @pytest.mark.asyncio
    async def test_read_timeout(self, buffer: StreamBuffer, mocker: MockerFixture) -> None:
        def timeout_side_effect(coro: Coroutine[Any, Any, Any], timeout: float | None) -> None:
            coro.close()
            raise asyncio.TimeoutError()

        mocker.patch("pywebtransport.stream.stream.asyncio.wait_for", side_effect=timeout_side_effect)

        with pytest.raises(TimeoutError, match="Read timeout after 0.1s"):
            await buffer.read(size=1, timeout=0.1)

    @pytest.mark.asyncio
    async def test_read_uninitialized_raises(self) -> None:
        buf = StreamBuffer()
        with pytest.raises(StreamError, match="StreamBuffer has not been initialized"):
            await buf.read(size=1)

    @pytest.mark.asyncio
    async def test_feed_data_uninitialized_raises(self) -> None:
        buf = StreamBuffer()
        with pytest.raises(StreamError, match="StreamBuffer has not been initialized"):
            await buf.feed_data(data=b"test")


class TestStreamBase:
    @pytest.mark.asyncio
    async def test_wait_closed_no_future(self, mock_session: Any) -> None:
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        stream._closed_future = None

        with pytest.raises(StreamError, match="is not initialized"):
            await stream.wait_closed()

    @pytest.mark.parametrize("stream_class", [WebTransportReceiveStream, WebTransportSendStream, WebTransportStream])
    def test_debug_state_and_summary(self, mock_session: Any, stream_class: Type[Any]) -> None:
        stream = stream_class(stream_id=TEST_STREAM_ID, session=mock_session)
        summary = stream.get_summary()
        debug_state = stream.debug_state()
        assert summary["stream_id"] == TEST_STREAM_ID
        assert "uptime" in summary
        assert debug_state["stream"]["id"] == TEST_STREAM_ID
        assert "statistics" in debug_state
        assert "is_readable" in debug_state["stream"]
        assert "is_writable" in debug_state["stream"]

    def test_str_representation_at_zero_uptime(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.get_timestamp", return_value=1000.0)
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._stats.created_at = 1000.0
        assert "uptime=0s" in str(stream)


class TestWebTransportReceiveStream:
    @pytest.mark.asyncio
    async def test_init(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        assert stream.stream_id == TEST_STREAM_ID
        expected_calls = [
            mocker.call(event_type=f"stream_data_received:{TEST_STREAM_ID}", handler=stream._on_data_received),
            mocker.call(event_type=f"stream_closed:{TEST_STREAM_ID}", handler=stream._on_stream_closed),
        ]
        mock_session.protocol_handler.on.assert_has_calls(expected_calls, any_order=True)

    def test_init_no_connection(self, mock_session: Any) -> None:
        mock_session.connection = None
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream._buffer_size == DEFAULT_BUFFER_SIZE

    def test_init_no_handler(self, mock_session: Any) -> None:
        mock_session.protocol_handler = None
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream._session() is not None

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._is_initialized
        buffer_id = id(receive_stream._buffer)
        await receive_stream.initialize()
        assert id(receive_stream._buffer) == buffer_id

    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exit(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(receive_stream, "abort", new_callable=mocker.AsyncMock)
        async with receive_stream:
            pass
        mock_abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_raises_exception(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(receive_stream, "abort", new_callable=mocker.AsyncMock)
        with pytest.raises(ValueError, match="test error"):
            async with receive_stream:
                raise ValueError("test error")
        mock_abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_already_closed(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(receive_stream, "abort", new_callable=mocker.AsyncMock)
        receive_stream._set_state(StreamState.CLOSED)
        async with receive_stream:
            pass
        mock_abort.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_success(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.stream.stream.get_timestamp", return_value=100.0)
        mocker.patch("time.time", side_effect=[100.5, 101.0])
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"some data")
        data = await receive_stream.read(size=9)
        assert data == b"some data"
        assert receive_stream._stats.bytes_received == 9

    @pytest.mark.asyncio
    async def test_read_with_no_buffer(self, receive_stream: WebTransportReceiveStream) -> None:
        receive_stream._buffer = None
        with pytest.raises(StreamError, match="Internal state error: buffer is None"):
            await receive_stream.read()

    @pytest.mark.asyncio
    async def test_read_from_half_closed_local_with_eof(self, receive_stream: WebTransportReceiveStream) -> None:
        receive_stream._set_state(StreamState.HALF_CLOSED_LOCAL)
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"final", eof=True)
        data = await receive_stream.read()
        assert data == b"final"
        assert receive_stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    async def test_helper_read_methods(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"line1\nline2\nand more", eof=True)
        assert await receive_stream.readline() == b"line1\n"
        assert await receive_stream.readuntil(separator=b"2") == b"line2"
        assert await receive_stream.readexactly(n=3) == b"\nan"
        assert await receive_stream.read_all() == b"d more"

    @pytest.mark.asyncio
    async def test_readline_success(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"hello\nworld")
        line = await receive_stream.readline()
        assert line == b"hello\n"

    @pytest.mark.asyncio
    async def test_read_raises_timeout_error(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        def timeout_side_effect(coro: Coroutine[Any, Any, Any], timeout: float | None) -> None:
            coro.close()
            raise asyncio.TimeoutError()

        mocker.patch("pywebtransport.stream.stream.asyncio.wait_for", side_effect=timeout_side_effect)
        with pytest.raises(TimeoutError, match="Read timeout after 1.0s"):
            await receive_stream.read()
        assert receive_stream._stats.read_errors == 1

    @pytest.mark.asyncio
    async def test_read_raises_stream_error_on_generic_exception(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        assert receive_stream._buffer is not None
        mocker.patch.object(receive_stream._buffer, "read", side_effect=ValueError("test error"))
        with pytest.raises(StreamError, match="Read operation failed: test error"):
            await receive_stream.read()
        assert receive_stream._stats.read_errors == 1

    @pytest.mark.asyncio
    async def test_read_all_exceeds_max_size(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"1234567890", eof=True)
        with pytest.raises(StreamError, match="Stream size exceeds maximum"):
            await receive_stream.read_all(max_size=5)

    @pytest.mark.asyncio
    async def test_read_all_logs_error(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(receive_stream, "read_iter", side_effect=StreamError("read failed"))
        mock_logger = mocker.patch("pywebtransport.stream.stream.logger")
        with pytest.raises(StreamError):
            await receive_stream.read_all()
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_iter_and_break_on_error(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(receive_stream, "read", side_effect=[b"chunk1", StreamError("read failed")])
        chunks = []
        async for chunk in receive_stream.read_iter():
            chunks.append(chunk)
        assert chunks == [b"chunk1"]

    @pytest.mark.asyncio
    async def test_readexactly_incomplete_read(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"short", eof=True)
        with pytest.raises(asyncio.IncompleteReadError):
            await receive_stream.readexactly(n=10)

    @pytest.mark.asyncio
    async def test_readexactly_zero_n(self, receive_stream: WebTransportReceiveStream) -> None:
        result = await receive_stream.readexactly(n=0)
        assert result == b""

    @pytest.mark.asyncio
    async def test_readexactly_negative_n_raises_value_error(self, receive_stream: WebTransportReceiveStream) -> None:
        with pytest.raises(ValueError):
            await receive_stream.readexactly(n=-1)

    @pytest.mark.asyncio
    async def test_readuntil_not_readable(self, receive_stream: WebTransportReceiveStream) -> None:
        receive_stream._state = StreamState.IDLE
        with pytest.raises(StreamError, match="Stream not readable"):
            await receive_stream.readuntil()

    @pytest.mark.asyncio
    async def test_readuntil_no_separator(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"no separator", eof=True)
        result = await receive_stream.readuntil(separator=b"Z")
        assert result == b"no separator"

    @pytest.mark.asyncio
    async def test_read_when_not_readable_raises(self, receive_stream: WebTransportReceiveStream) -> None:
        receive_stream._set_state(new_state=StreamState.IDLE)
        assert not receive_stream.is_readable
        assert not receive_stream.is_closed
        with pytest.raises(StreamError, match="Stream not readable"):
            await receive_stream.read()

    @pytest.mark.asyncio
    async def test_read_when_closed_returns_empty(self, receive_stream: WebTransportReceiveStream) -> None:
        receive_stream._set_state(new_state=StreamState.RESET_SENT)
        result = await receive_stream.read()
        assert result == b""

    @pytest.mark.asyncio
    async def test_on_data_received_no_buffer(self, receive_stream: WebTransportReceiveStream) -> None:
        receive_stream._buffer = None
        await receive_stream._on_data_received(Event(type="test", data={"data": b"foo"}))

    @pytest.mark.asyncio
    async def test_on_data_received_with_end_stream_only(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"original")
        await receive_stream._on_data_received(Event(type="test", data={"end_stream": True}))
        assert receive_stream._buffer.size == 8
        assert receive_stream._buffer._eof

    @pytest.mark.asyncio
    async def test_on_data_received_empty_data_dict(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"original")
        await receive_stream._on_data_received(Event(type="test", data={}))
        assert receive_stream._buffer.size == 8

    @pytest.mark.asyncio
    async def test_on_data_received_no_event_data(self, receive_stream: WebTransportReceiveStream) -> None:
        await receive_stream._on_data_received(Event(type="test", data=None))
        assert receive_stream._buffer is not None
        assert receive_stream._buffer.size == 0

    @pytest.mark.asyncio
    async def test_on_stream_closed_handler(self, receive_stream: WebTransportReceiveStream) -> None:
        await receive_stream._on_stream_closed(Event(type="test", data={}))
        assert receive_stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    @pytest.mark.parametrize("session_available", [True, False])
    async def test_abort(self, mock_session: Any, mocker: MockerFixture, session_available: bool) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        if not session_available:
            mocker.patch.object(stream, "_session", return_value=None)
        await stream.abort(code=99)
        if session_available:
            mock_session.protocol_handler.abort_stream.assert_called_once_with(stream_id=TEST_STREAM_ID, error_code=99)
        else:
            mock_session.protocol_handler.abort_stream.assert_not_called()
        assert stream.state == StreamState.RESET_SENT

    def test_set_state_no_change(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mock_teardown = mocker.patch.object(stream, "_teardown")
        stream._set_state(new_state=StreamState.OPEN)
        mock_teardown.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_state_idempotent(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.stream.logger")
        receive_stream._state = StreamState.HALF_CLOSED_LOCAL
        receive_stream._set_state(StreamState.OPEN)
        receive_stream._set_state(StreamState.OPEN)
        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_teardown(
        self, receive_stream: WebTransportReceiveStream, mock_session: Any, mocker: MockerFixture
    ) -> None:
        receive_stream._set_state(new_state=StreamState.CLOSED)
        await receive_stream.wait_closed()
        expected_calls = [
            mocker.call(event_type=f"stream_data_received:{TEST_STREAM_ID}", handler=receive_stream._on_data_received),
            mocker.call(event_type=f"stream_closed:{TEST_STREAM_ID}", handler=receive_stream._on_stream_closed),
        ]
        mock_session.protocol_handler.off.assert_has_calls(expected_calls, any_order=True)

    @pytest.mark.asyncio
    async def test_teardown_no_session(
        self, receive_stream: WebTransportReceiveStream, mock_session: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(receive_stream, "_session", return_value=None)
        receive_stream._set_state(new_state=StreamState.CLOSED)
        mock_session.protocol_handler.off.assert_not_called()

    @pytest.mark.asyncio
    async def test_teardown_with_session_no_handler(self, receive_stream: WebTransportReceiveStream) -> None:
        session = receive_stream._session()
        assert session is not None
        setattr(session, "protocol_handler", None)
        receive_stream._teardown()

    @pytest.mark.asyncio
    async def test_teardown_future_already_done(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._closed_future is not None
        receive_stream._closed_future.set_result(None)
        assert receive_stream._closed_future.done()
        receive_stream._teardown()


class TestWebTransportSendStream:
    @pytest.mark.asyncio
    async def test_init(self, mock_session: Any, mocker: MockerFixture) -> None:
        mock_ensure_writer = mocker.patch.object(WebTransportSendStream, "_ensure_writer_is_running")
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        mock_ensure_writer.assert_called_once()

    def test_init_no_connection(self, mock_session: Any) -> None:
        mock_session.connection = None
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream._max_buffer_size > 0

    @pytest.mark.asyncio
    async def test_ensure_writer_is_running_idempotent(self, send_stream: WebTransportSendStream) -> None:
        initial_task = send_stream._writer_task
        assert initial_task is not None and not initial_task.done()
        send_stream._ensure_writer_is_running()
        assert send_stream._writer_task is initial_task

    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exit(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(send_stream, "abort", new_callable=mocker.AsyncMock)
        async with send_stream:
            pass
        mock_abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exception(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(send_stream, "abort", new_callable=mocker.AsyncMock)
        with pytest.raises(ValueError, match="test error"):
            async with send_stream:
                raise ValueError("test error")
        mock_abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_already_closed(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(send_stream, "abort", new_callable=mocker.AsyncMock)
        send_stream._set_state(StreamState.CLOSED)
        async with send_stream:
            pass
        mock_abort.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_success(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task is not None
        send_stream._writer_task.cancel()
        completion_future = asyncio.create_task(send_stream.write(data=b"some payload"))
        await asyncio.sleep(0)
        assert len(send_stream._write_buffer) == 1
        assert send_stream._write_buffer[0]["data"] == b"some payload"
        completion_future.cancel()
        with pytest.raises(asyncio.CancelledError):
            await completion_future

    @pytest.mark.asyncio
    async def test_write_no_wait(self, send_stream: WebTransportSendStream) -> None:
        await send_stream.write(data=b"fire and forget", wait_flush=False)
        assert len(send_stream._write_buffer) == 1
        assert send_stream._write_buffer[0]["data"] == b"fire and forget"
        assert send_stream._write_buffer[0]["future"] is None

    @pytest.mark.asyncio
    async def test_write_chunking(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task is not None
        send_stream._writer_task.cancel()
        send_stream._WRITE_CHUNK_SIZE = 10
        write_task = asyncio.create_task(send_stream.write(data=b"a" * 25, end_stream=True))
        await asyncio.sleep(0)
        assert len(send_stream._write_buffer) == 3
        write_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write_task

    @pytest.mark.asyncio
    async def test_write_chunking_no_wait_no_end(self, send_stream: WebTransportSendStream) -> None:
        send_stream._WRITE_CHUNK_SIZE = 5
        await send_stream.write(data=b"long data string", wait_flush=False, end_stream=False)
        assert len(send_stream._write_buffer) == 4
        for item in send_stream._write_buffer:
            assert item["future"] is None

    @pytest.mark.asyncio
    async def test_write_all(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mock_write = mocker.patch.object(send_stream, "write", new_callable=mocker.AsyncMock)
        mock_flush = mocker.patch.object(send_stream, "flush", new_callable=mocker.AsyncMock)
        mock_close = mocker.patch.object(send_stream, "close", new_callable=mocker.AsyncMock)
        await send_stream.write_all(data=b"all the data", chunk_size=5)
        assert mock_write.call_count == 3
        mock_write.assert_has_calls(
            [
                mocker.call(data=b"all t", wait_flush=False),
                mocker.call(data=b"he da", wait_flush=False),
                mocker.call(data=b"ta", wait_flush=False),
            ]
        )
        mock_flush.assert_awaited_once()
        mock_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_empty_and_timeout(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        assert send_stream._write_buffer_size == 0
        await send_stream.flush()
        send_stream._write_buffer_size = 10
        assert send_stream._flushed_event is not None
        mocker.patch.object(
            send_stream._flushed_event, "wait", new_callable=mocker.AsyncMock, side_effect=asyncio.TimeoutError
        )
        with pytest.raises(TimeoutError, match="Flush timeout"):
            await send_stream.flush()

    @pytest.mark.asyncio
    async def test_write_all_error_handling(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mocker.patch.object(send_stream, "write", side_effect=StreamError("send failed"))
        mock_abort = mocker.patch.object(send_stream, "abort", new_callable=mocker.AsyncMock)
        mock_logger = mocker.patch("pywebtransport.stream.stream.logger")
        with pytest.raises(StreamError):
            await send_stream.write_all(data=b"some data")
        mock_abort.assert_called_once_with(code=1)
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "attr_to_nullify",
        ["_write_lock", "_new_data_event", "_flushed_event", "_backpressure_event"],
    )
    async def test_write_with_internal_state_error(
        self, send_stream: WebTransportSendStream, attr_to_nullify: str
    ) -> None:
        setattr(send_stream, attr_to_nullify, None)
        with pytest.raises(StreamError, match="Internal state error: events are None"):
            await send_stream.write(data=b"test")

    @pytest.mark.asyncio
    async def test_wait_for_buffer_space_uninitialized(self, mock_session: Any) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        with pytest.raises(StreamError, match="is not initialized"):
            await stream._wait_for_buffer_space(1)

    @pytest.mark.asyncio
    async def test_write_backpressure_actual_timeout(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        send_stream._write_timeout = 0.01
        send_stream._max_buffer_size = 10
        mocker.patch.object(send_stream, "_write_buffer_size", 11)
        assert send_stream._backpressure_event is not None
        send_stream._backpressure_event.clear()
        with pytest.raises(TimeoutError, match="Write timeout due to backpressure"):
            await send_stream._wait_for_buffer_space(size=1)

    @pytest.mark.asyncio
    async def test_write_not_writable(self, send_stream: WebTransportSendStream) -> None:
        send_stream._set_state(new_state=StreamState.CLOSED)
        with pytest.raises(StreamError):
            await send_stream.write(data=b"data")

    @pytest.mark.asyncio
    async def test_write_empty_data_no_end_stream(self, send_stream: WebTransportSendStream) -> None:
        await send_stream.write(data=b"", end_stream=False)
        assert len(send_stream._write_buffer) == 0

    @pytest.mark.asyncio
    async def test_write_empty_data_with_end_stream(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task is not None
        send_stream._writer_task.cancel()
        write_task = asyncio.create_task(send_stream.write(data=b"", end_stream=True))
        await asyncio.sleep(0)
        assert len(send_stream._write_buffer) == 1
        assert send_stream._write_buffer[0]["data"] == b""
        assert send_stream._write_buffer[0]["end_stream"]
        write_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write_task

    @pytest.mark.asyncio
    async def test_close_when_not_writable(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        send_stream._set_state(StreamState.CLOSED)
        mock_write = mocker.patch.object(send_stream, "write")
        await send_stream.close()
        mock_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_raises_non_writer_stream_error(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.stream.logger")
        mocker.patch.object(send_stream, "write", side_effect=StreamError("other error"))
        await send_stream.close()
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_ignores_writer_terminated_error(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.stream.logger")
        mocker.patch.object(send_stream, "write", side_effect=StreamError("Writer loop terminated"))
        await send_stream.close()
        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_state_idempotent(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.stream.logger")
        send_stream._state = StreamState.HALF_CLOSED_LOCAL
        send_stream._set_state(StreamState.OPEN)
        send_stream._set_state(StreamState.OPEN)
        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_stream_closed_handler(self, send_stream: WebTransportSendStream) -> None:
        await send_stream._on_stream_closed(Event(type="test", data={}))
        assert send_stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    async def test_teardown_with_writer_task_done(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task is not None
        send_stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await send_stream._writer_task
        assert send_stream._writer_task.done()

        send_stream._teardown()

    @pytest.mark.asyncio
    async def test_writer_loop_integration_and_future_success(self, mock_session: Any, mocker: MockerFixture) -> None:
        send_called_event = asyncio.Event()
        mocker.patch("time.time", side_effect=[100.0, 101.0, 102.0])
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = (
            lambda *args, **kwargs: send_called_event.set()
        )
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        write_task = asyncio.create_task(stream.write(data=b"data", wait_flush=True))
        await asyncio.wait_for(send_called_event.wait(), timeout=1.0)
        await write_task
        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_once_with(
            stream_id=TEST_STREAM_ID, data=b"data", end_stream=False
        )
        assert stream._stats.writes_count == 1
        assert stream._stats.bytes_sent == 4

    @pytest.mark.asyncio
    async def test_writer_loop_starts_waits_and_processes(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._new_data_event and not send_stream._new_data_event.is_set()
        assert send_stream._flushed_event and send_stream._flushed_event.is_set()

        await asyncio.sleep(0)
        assert not send_stream._new_data_event.is_set()

        write_task = asyncio.create_task(send_stream.write(data=b"hello", wait_flush=True))
        await write_task
        assert send_stream._write_buffer_size == 0
        assert send_stream._flushed_event.is_set()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "initial_state, expected_final_state",
        [
            (StreamState.OPEN, StreamState.HALF_CLOSED_LOCAL),
            (StreamState.HALF_CLOSED_REMOTE, StreamState.CLOSED),
        ],
    )
    async def test_writer_loop_handles_end_stream(
        self, mock_session: Any, initial_state: StreamState, expected_final_state: StreamState
    ) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        stream._state = initial_state
        await stream.write(data=b"final", end_stream=True, wait_flush=True)
        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_with(
            stream_id=TEST_STREAM_ID, data=b"final", end_stream=True
        )
        assert stream.state == expected_final_state

    @pytest.mark.asyncio
    async def test_writer_loop_handles_send_exception(
        self, send_stream: WebTransportSendStream, mock_session: Any
    ) -> None:
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = ValueError("send failed")
        write_task = asyncio.create_task(send_stream.write(data=b"data"))
        with pytest.raises(ValueError):
            await write_task
        assert send_stream.state == StreamState.RESET_SENT
        assert send_stream._stats.write_errors == 1

    @pytest.mark.asyncio
    async def test_writer_loop_handles_send_exception_no_future(
        self, send_stream: WebTransportSendStream, mock_session: Any
    ) -> None:
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = ValueError("send failed")
        await send_stream.write(data=b"data", wait_flush=False)
        await asyncio.sleep(0)
        assert send_stream.state == StreamState.RESET_SENT
        assert send_stream._stats.write_errors == 1

    @pytest.mark.asyncio
    async def test_writer_loop_handles_flow_control_error(
        self, send_stream: WebTransportSendStream, mock_session: Any
    ) -> None:
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = [
            FlowControlError("credit exhausted"),
            None,
        ]

        async def set_event_later() -> None:
            await asyncio.sleep(0.01)
            mock_session._data_credit_event.set()

        asyncio.create_task(set_event_later())
        await send_stream.write(data=b"data")
        assert mock_session.protocol_handler.send_webtransport_stream_data.call_count == 2
        assert send_stream.state == StreamState.OPEN
        assert send_stream._stats.flow_control_errors == 1

    @pytest.mark.asyncio
    async def test_writer_loop_flow_control_timeout(
        self, send_stream: WebTransportSendStream, mock_session: Any, mocker: MockerFixture
    ) -> None:
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = FlowControlError("credit exhausted")
        mocker.patch.object(mock_session._data_credit_event, "wait", side_effect=asyncio.TimeoutError)
        write_task = asyncio.create_task(send_stream.write(data=b"data"))
        with pytest.raises(TimeoutError, match="Timeout waiting for data credit"):
            await write_task
        assert send_stream._writer_task is not None
        with pytest.raises(TimeoutError):
            await send_stream._writer_task

    @pytest.mark.asyncio
    async def test_writer_loop_flow_control_no_credit_event_retries(
        self, send_stream: WebTransportSendStream, mock_session: Any
    ) -> None:
        side_effects = [FlowControlError("exhausted")] * 2 + [None]
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = side_effects
        mock_session._data_credit_event = None
        await send_stream.write(data=b"test")
        assert mock_session.protocol_handler.send_webtransport_stream_data.call_count == 3

    @pytest.mark.asyncio
    async def test_writer_loop_releases_backpressure(self, mock_session: Any) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._write_timeout = 0.5
        await stream.initialize()
        stream._max_buffer_size = 100
        stream._backpressure_limit = 95
        assert stream._backpressure_event is not None

        await stream.write(data=b"a" * 95, wait_flush=False)
        assert stream._backpressure_event.is_set()

        write_task = asyncio.create_task(stream.write(data=b"b" * 10, wait_flush=True))

        await asyncio.sleep(0.01)

        await asyncio.wait_for(write_task, timeout=1.0)

        assert stream._backpressure_event.is_set()
        assert stream._write_buffer_size == 0

    @pytest.mark.asyncio
    async def test_writer_loop_no_session(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("weakref.ref").return_value.return_value = None
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        write_task = asyncio.create_task(stream.write(data=b"test", wait_flush=True))
        with pytest.raises(StreamError, match="Session is not available for writing"):
            await write_task

    @pytest.mark.asyncio
    async def test_writer_loop_no_handler_and_future_fails(self, send_stream: WebTransportSendStream) -> None:
        session = send_stream._session()
        assert session is not None
        setattr(session, "protocol_handler", None)
        with pytest.raises(StreamError, match="Session is not available for writing"):
            await send_stream.write(data=b"test", wait_flush=True)

    @pytest.mark.asyncio
    async def test_writer_loop_no_handler_no_future(self, send_stream: WebTransportSendStream) -> None:
        session = send_stream._session()
        assert session is not None
        setattr(session, "protocol_handler", None)
        await send_stream.write(data=b"test", wait_flush=False)
        await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_writer_loop_session_closed(self, send_stream: WebTransportSendStream, mock_session: Any) -> None:
        mock_session.is_closed = True
        write_task = asyncio.create_task(send_stream.write(data=b"test", wait_flush=True))
        with pytest.raises(StreamError, match="Session is not available for writing"):
            await write_task

    @pytest.mark.asyncio
    async def test_writer_loop_cancelled_with_pending_writes(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task is not None
        future = asyncio.get_running_loop().create_future()
        send_stream._write_buffer.append({"future": future})
        send_stream._writer_task.cancel()
        await asyncio.sleep(0.01)
        assert future.done()
        with pytest.raises(StreamError, match="Writer loop terminated"):
            await future

    @pytest.mark.asyncio
    async def test_writer_loop_cancelled_with_pending_item_no_future(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task is not None
        send_stream._write_buffer.append({"data": b"lost data", "end_stream": False, "future": None})
        assert send_stream._new_data_event is not None
        send_stream._new_data_event.set()

        send_stream._writer_task.cancel()
        await asyncio.sleep(0)

        with suppress(asyncio.CancelledError):
            await send_stream._writer_task

        assert len(send_stream._write_buffer) == 0

    @pytest.mark.asyncio
    async def test_writer_loop_cancelled_while_waiting(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task is not None
        assert send_stream._new_data_event is not None
        assert not send_stream._new_data_event.is_set()

        send_stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await send_stream._writer_task

        assert send_stream._writer_task.done()

    @pytest.mark.asyncio
    async def test_teardown_no_session(
        self, send_stream: WebTransportSendStream, mock_session: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(send_stream, "_session", return_value=None)
        send_stream._set_state(new_state=StreamState.CLOSED)
        mock_session.protocol_handler.off.assert_not_called()


class TestWebTransportStream:
    def test_init_no_connection(self, mock_session: Any) -> None:
        mock_session.connection = None
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream._buffer_size == DEFAULT_BUFFER_SIZE

    @pytest.mark.asyncio
    async def test_init(self, bidirectional_stream: WebTransportStream) -> None:
        assert bidirectional_stream.direction == StreamDirection.BIDIRECTIONAL
        assert hasattr(bidirectional_stream, "read") and hasattr(bidirectional_stream, "write")

    @pytest.mark.asyncio
    async def test_initialize_no_protocol_handler(self, mock_session: Any, mocker: MockerFixture) -> None:
        mock_session.protocol_handler = None
        mock_ensure_writer = mocker.patch.object(WebTransportStream, "_ensure_writer_is_running")
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        mock_ensure_writer.assert_called_once()

    @pytest.mark.asyncio
    async def test_bidirectional_stream_read_and_write(self, bidirectional_stream: WebTransportStream) -> None:
        assert bidirectional_stream._writer_task is not None
        bidirectional_stream._writer_task.cancel()
        write_task = asyncio.create_task(bidirectional_stream.write(data=b"data to send"))
        await asyncio.sleep(0)
        assert len(bidirectional_stream._write_buffer) == 1
        write_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await write_task
        assert bidirectional_stream._buffer is not None
        await bidirectional_stream._buffer.feed_data(data=b"data to receive")
        read_data = await bidirectional_stream.read(size=100)
        assert read_data == b"data to receive"

    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exit(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(bidirectional_stream, "abort", new_callable=mocker.AsyncMock)
        async with bidirectional_stream:
            pass
        mock_abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exception(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(bidirectional_stream, "abort", new_callable=mocker.AsyncMock)
        with pytest.raises(ValueError, match="test error"):
            async with bidirectional_stream:
                raise ValueError("test error")
        mock_abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_already_closed(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(bidirectional_stream, "abort", new_callable=mocker.AsyncMock)
        bidirectional_stream._set_state(StreamState.CLOSED)
        async with bidirectional_stream:
            pass
        mock_abort.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_calls_sendstream_close(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mock_send_close = mocker.patch.object(WebTransportSendStream, "close", new_callable=mocker.AsyncMock)
        await bidirectional_stream.close()
        mock_send_close.assert_called_once_with(self=bidirectional_stream)

    def test_bidirectional_stream_closes_correctly(self, mock_session: Any) -> None:
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        stream._state = StreamState.HALF_CLOSED_LOCAL
        stream._set_state(new_state=StreamState.CLOSED)
        assert stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    async def test_teardown_with_writer_task_done(self, bidirectional_stream: WebTransportStream) -> None:
        assert bidirectional_stream._writer_task is not None
        bidirectional_stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await bidirectional_stream._writer_task
        assert bidirectional_stream._writer_task.done()

        bidirectional_stream._teardown()

    @pytest.mark.asyncio
    async def test_monitor_health_no_issues(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mock_logger_warning = mocker.patch("pywebtransport.stream.stream.logger.warning")
        bidirectional_stream._stats.reads_count = 5
        bidirectional_stream._stats.read_errors = 0
        monitor_task = asyncio.create_task(bidirectional_stream.monitor_health(check_interval=0.01))
        await asyncio.sleep(0.05)
        mock_logger_warning.assert_not_called()
        bidirectional_stream._set_state(new_state=StreamState.CLOSED)
        monitor_task.cancel()

    @pytest.mark.asyncio
    async def test_monitor_health_cancelled(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        await bidirectional_stream.monitor_health(check_interval=0.01)

    @pytest.mark.asyncio
    async def test_monitor_health_handles_exceptions(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mock_logger_error = mocker.patch("pywebtransport.stream.stream.logger.error")
        error = ValueError("test error")
        mocker.patch("asyncio.sleep", side_effect=error)
        await bidirectional_stream.monitor_health()
        mock_logger_error.assert_called_with("Stream health monitoring error: %s", error, exc_info=True)

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
            (StreamState.OPEN, {}, []),
            (StreamState.OPEN, {"reads_count": 5, "read_errors": 0}, []),
            (StreamState.OPEN, {"writes_count": 5, "write_errors": 0}, []),
            (StreamState.OPEN, {"reads_count": 20, "read_errors": 1}, []),
            (StreamState.OPEN, {"reads_count": 2, "total_read_time": 1.0}, []),
            (StreamState.OPEN, {"writes_count": 2, "total_write_time": 1.0}, []),
        ],
    )
    async def test_diagnose_issues(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        state: StreamState,
        stats_attrs: dict[str, Any],
        expected_issues: list[str],
    ) -> None:
        mocker.patch("pywebtransport.stream.stream.get_timestamp", return_value=5000.0)
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        stream._state = state
        for key, value in stats_attrs.items():
            setattr(stream._stats, key, value)
        issues = await stream.diagnose_issues(latency_threshold=2.0, error_rate_threshold=0.2, stale_threshold=3600.0)
        assert issues == expected_issues


class TestStreamUninitialized:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("stream_class", [WebTransportReceiveStream, WebTransportSendStream, WebTransportStream])
    async def test_methods_raise_before_initialized(self, stream_class: Type[Any], mock_session: Any) -> None:
        stream = stream_class(stream_id=TEST_STREAM_ID, session=mock_session)
        assert not stream._is_initialized
        with pytest.raises(StreamError, match="is not initialized"):
            await stream.wait_closed()
        if hasattr(stream, "read"):
            with pytest.raises(StreamError, match="is not initialized"):
                await stream.read()
        if hasattr(stream, "write"):
            with pytest.raises(StreamError, match="is not initialized"):
                await stream.write(data=b"data")
        if hasattr(stream, "flush"):
            with pytest.raises(StreamError, match="is not initialized"):
                await stream.flush()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["feed_data", "read"])
    async def test_buffer_methods_raise_before_initialized(self, method_name: str) -> None:
        buffer = StreamBuffer()
        with pytest.raises(StreamError, match="StreamBuffer has not been initialized"):
            coro = getattr(buffer, method_name)
            if method_name == "feed_data":
                await coro(data=b"data")
            else:
                await coro()
