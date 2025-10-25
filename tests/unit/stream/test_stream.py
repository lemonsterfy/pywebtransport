"""Unit tests for the pywebtransport.stream.stream module."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from contextlib import suppress
from typing import Any

import pytest
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import (
    Event,
    StreamError,
    TimeoutError,
    WebTransportReceiveStream,
    WebTransportSendStream,
    WebTransportStream,
)
from pywebtransport.constants import DEFAULT_STREAM_LINE_LIMIT
from pywebtransport.exceptions import FlowControlError
from pywebtransport.stream import StreamDiagnostics, StreamStats
from pywebtransport.stream.stream import _StreamBuffer
from pywebtransport.types import EventType, StreamId, StreamState

DEFAULT_BUFFER_SIZE = 65536
TEST_STREAM_ID: StreamId = 123


@asyncio_fixture
async def bidirectional_stream(
    mock_session: Any,
) -> AsyncGenerator[WebTransportStream, None]:
    stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
    await stream.initialize()
    yield stream
    try:
        if not stream.is_closed:
            await stream.abort()
    except Exception:
        pass
    if stream._writer_task and not stream._writer_task.done():
        stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream._writer_task


@asyncio_fixture
async def buffer() -> AsyncGenerator[_StreamBuffer, None]:
    buf = _StreamBuffer(max_size=DEFAULT_BUFFER_SIZE)
    await buf.initialize()
    yield buf


@pytest.fixture
def mock_logger(mocker: MockerFixture) -> Any:
    return mocker.patch("pywebtransport.stream.stream.logger")


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


@asyncio_fixture
async def receive_stream(
    mock_session: Any,
) -> AsyncGenerator[WebTransportReceiveStream, None]:
    stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
    await stream.initialize()
    yield stream
    if not stream.is_closed:
        with suppress(StreamError):
            await stream.abort()


@asyncio_fixture
async def send_stream(
    mock_session: Any,
) -> AsyncGenerator[WebTransportSendStream, None]:
    stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
    await stream.initialize()
    yield stream
    if not stream.is_closed:
        with suppress(StreamError):
            await stream.abort()
    if stream._writer_task and not stream._writer_task.done():
        stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await stream._writer_task


@pytest.mark.asyncio
class TestStreamBuffer:
    async def test_eof_handling(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"final data", eof=True)

        data, eof = await buffer.read(size=10)
        assert data == b"final data"
        assert eof
        assert buffer.at_eof

        extra_read, extra_eof = await buffer.read(size=10)
        assert extra_read == b""
        assert extra_eof

    async def test_feed_and_read_data(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"hello")
        data, eof = await buffer.read(size=5)
        assert data == b"hello"
        assert not eof

    async def test_feed_data_after_eof(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"first", eof=True)
        await buffer.feed_data(data=b"second")
        data, eof = await buffer.read(size=100)
        assert data == b"first"
        assert eof

    async def test_find_separator_not_found(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"hello world")
        assert buffer.find_separator(separator=b"Z") == -1

    async def test_find_separator_on_empty_buffer(self, buffer: _StreamBuffer) -> None:
        assert buffer.find_separator(separator=b"\n") == -1

    async def test_find_separator_simple(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"hello\nworld")
        assert buffer.find_separator(separator=b"\n") == 6

    async def test_find_separator_spanning_chunks(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"hello\r")
        await buffer.feed_data(data=b"\nworld")
        assert buffer.find_separator(separator=b"\r\n") == 7

    async def test_initialize_idempotent(self, buffer: _StreamBuffer) -> None:
        assert buffer._lock is not None
        lock_id = id(buffer._lock)

        await buffer.initialize()
        await buffer.initialize()

        assert id(buffer._lock) == lock_id

    async def test_read_partial_first_chunk(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"longchunk")
        data, _ = await buffer.read(size=4)
        assert data == b"long"
        assert buffer.size == 5
        data, _ = await buffer.read()
        assert data == b"chunk"

    async def test_read_timeout(self, buffer: _StreamBuffer, mocker: MockerFixture) -> None:
        async def timeout_side_effect(coro: Coroutine[Any, Any, Any], timeout: float | None) -> None:
            coro.close()
            raise asyncio.TimeoutError()

        mocker.patch("asyncio.wait_for", side_effect=timeout_side_effect)

        with pytest.raises(TimeoutError, match="Read timeout after 0.1s"):
            await buffer.read(size=1, timeout=0.1)

    @pytest.mark.parametrize("size, expected", [(-1, b"all data"), (0, b""), (4, b"all ")])
    async def test_read_with_different_sizes(self, buffer: _StreamBuffer, size: int, expected: bytes) -> None:
        await buffer.feed_data(data=b"all data")
        data, _ = await buffer.read(size=size)
        assert data == expected

    async def test_read_zero_bytes_returns_empty(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"some data")
        data, _ = await buffer.read(size=0)
        assert data == b""
        assert buffer.size == 9

    async def test_uninitialized_raises_error(self) -> None:
        uninitialized_buffer = _StreamBuffer()
        with pytest.raises(StreamError, match="not been initialized"):
            await uninitialized_buffer.feed_data(data=b"test")
        with pytest.raises(StreamError, match="not been initialized"):
            await uninitialized_buffer.read(size=1)
        with pytest.raises(StreamError, match="not initialized"):
            await uninitialized_buffer.wait_for_data()

    async def test_wait_for_data(self, buffer: _StreamBuffer) -> None:
        wait_task = asyncio.create_task(buffer.wait_for_data())
        await asyncio.sleep(0.01)
        assert not wait_task.done()

        await buffer.feed_data(data=b"test")
        await asyncio.wait_for(wait_task, timeout=1.0)

    async def test_wait_for_data_at_eof(self, buffer: _StreamBuffer) -> None:
        await buffer.feed_data(data=b"", eof=True)
        assert buffer.at_eof
        wait_task = asyncio.create_task(buffer.wait_for_data())
        await asyncio.sleep(0)
        assert wait_task.done()


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


class TestWebTransportBidirectionalStream:
    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exception(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        mock_abort = mocker.patch.object(stream, "abort", new_callable=mocker.AsyncMock)
        with pytest.raises(ValueError):
            async with stream:
                raise ValueError("Test Exception")
        mock_abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_already_closed(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        patcher = mocker.patch.object(
            WebTransportStream,
            "is_closed",
            new_callable=mocker.PropertyMock,
            return_value=True,
        )
        patcher.start()
        try:
            mock_close = mocker.patch.object(bidirectional_stream, "close", new_callable=mocker.AsyncMock)
            async with bidirectional_stream:
                pass
            mock_close.assert_not_called()
        finally:
            patcher.stop()

    @pytest.mark.asyncio
    async def test_async_context_manager_closes_on_success(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        mock_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)
        async with stream:
            pass
        mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_bidirectional_stream_read_and_write(self, bidirectional_stream: WebTransportStream) -> None:
        mock_session: Any = bidirectional_stream._session()
        assert mock_session is not None
        await bidirectional_stream.write(data=b"data to send")
        assert mock_session.protocol_handler is not None
        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_once_with(
            stream_id=TEST_STREAM_ID, data=b"data to send", end_stream=False
        )

        assert bidirectional_stream._buffer is not None
        await bidirectional_stream._buffer.feed_data(data=b"data to receive")
        read_data = await bidirectional_stream.read(size=100)
        assert read_data == b"data to receive"

    @pytest.mark.asyncio
    async def test_close_calls_send_stream_close(self, bidirectional_stream: WebTransportStream, mocker: Any) -> None:
        mock_send_close = mocker.patch.object(WebTransportSendStream, "close", new_callable=mocker.AsyncMock)
        await bidirectional_stream.close()
        mock_send_close.assert_awaited_once_with(self=bidirectional_stream)

    @pytest.mark.asyncio
    async def test_diagnostics_property(self, bidirectional_stream: WebTransportStream) -> None:
        diags = bidirectional_stream.diagnostics

        assert isinstance(diags, StreamDiagnostics)
        assert diags.stats is bidirectional_stream._stats
        assert diags.read_buffer_size == 0
        assert diags.write_buffer_size == 0

        assert bidirectional_stream._buffer is not None
        await bidirectional_stream._buffer.feed_data(data=b"read_data")
        await bidirectional_stream.write(data=b"write_data", wait_flush=False)

        diags_updated = bidirectional_stream.diagnostics
        assert diags_updated.read_buffer_size == len(b"read_data")
        assert diags_updated.write_buffer_size == len(b"write_data")

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, bidirectional_stream: WebTransportStream) -> None:
        assert bidirectional_stream._is_initialized
        closed_future_id = id(bidirectional_stream._closed_future)
        await bidirectional_stream.initialize()
        assert id(bidirectional_stream._closed_future) == closed_future_id

    @pytest.mark.asyncio
    async def test_initialize_no_handler(self, mock_session: Any) -> None:
        mock_session.protocol_handler = None
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        assert stream._is_initialized

    @pytest.mark.asyncio
    async def test_set_state_future_already_done(self, bidirectional_stream: WebTransportStream) -> None:
        assert bidirectional_stream._closed_future
        bidirectional_stream._closed_future.set_result(None)
        await bidirectional_stream._set_state(StreamState.CLOSED)

    @pytest.mark.asyncio
    async def test_set_state_idempotent(self, bidirectional_stream: WebTransportStream) -> None:
        bidirectional_stream._state = StreamState.OPEN
        await bidirectional_stream._set_state(StreamState.OPEN)

    @pytest.mark.asyncio
    async def test_teardown_composes_both_parents(
        self, bidirectional_stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        mock_receive_teardown = mocker.patch.object(
            WebTransportReceiveStream, "_teardown", new_callable=mocker.AsyncMock
        )
        mock_send_teardown = mocker.patch.object(WebTransportSendStream, "_teardown", new_callable=mocker.AsyncMock)

        await bidirectional_stream._teardown()

        mock_receive_teardown.assert_awaited_once_with(self=bidirectional_stream)
        mock_send_teardown.assert_awaited_once_with(self=bidirectional_stream)


class TestWebTransportReceiveStream:
    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exit(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        mock_abort = mocker.patch.object(stream, "abort", new_callable=mocker.AsyncMock)
        async with stream:
            pass
        mock_abort.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_already_closed(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mock_abort = mocker.patch.object(receive_stream, "abort", new_callable=mocker.AsyncMock)
        await receive_stream._set_state(StreamState.CLOSED)
        async with receive_stream:
            pass
        mock_abort.assert_not_called()

    @pytest.mark.asyncio
    async def test_diagnostics(self, receive_stream: WebTransportReceiveStream) -> None:
        diags = receive_stream.diagnostics
        assert isinstance(diags, StreamDiagnostics)
        assert diags.write_buffer_size == 0

    @pytest.mark.asyncio
    async def test_init_registers_handlers(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        assert mock_session.protocol_handler is not None
        expected_calls = [
            mocker.call(
                event_type=EventType.STREAM_DATA_RECEIVED,
                handler=stream._on_data_received,
            ),
            mocker.call(event_type=EventType.STREAM_CLOSED, handler=stream._on_stream_closed),
        ]
        mock_session.protocol_handler.on.assert_has_calls(expected_calls, any_order=True)

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._is_initialized
        assert receive_stream._buffer is not None
        buffer_id = id(receive_stream._buffer)
        await receive_stream.initialize()
        assert id(receive_stream._buffer) == buffer_id

    @pytest.mark.asyncio
    async def test_initialize_no_session_handler(self, mock_session: Any) -> None:
        mock_session.protocol_handler = None
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        assert stream._is_initialized

    @pytest.mark.asyncio
    async def test_initialize_with_dead_session_ref(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        mocker.patch.object(stream, "_session", return_value=None)
        await stream.initialize()
        mock_session.protocol_handler.on.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_with_no_connection_on_session(self, mock_session: Any) -> None:
        mock_session.connection = None
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream._buffer_size == 65536

    @pytest.mark.asyncio
    async def test_on_data_received_ignores_wrong_stream_id(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        assert receive_stream._buffer is not None
        mock_feed = mocker.patch.object(receive_stream._buffer, "feed_data", new_callable=mocker.AsyncMock)
        event = Event(
            type=EventType.STREAM_DATA_RECEIVED,
            data={"stream_id": 999, "data": b"foo"},
        )
        await receive_stream._on_data_received(event)
        mock_feed.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_data_received_invalid_event_data(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        assert receive_stream._buffer is not None
        mock_feed = mocker.patch.object(receive_stream._buffer, "feed_data", new_callable=mocker.AsyncMock)
        event = Event(type=EventType.STREAM_DATA_RECEIVED, data=None)
        await receive_stream._on_data_received(event)
        mock_feed.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_data_received_uninitialized_buffer(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        event = Event(
            type=EventType.STREAM_DATA_RECEIVED,
            data={"stream_id": TEST_STREAM_ID, "data": b"foo"},
        )
        await stream._on_data_received(event)

    @pytest.mark.asyncio
    async def test_on_stream_closed_event(self, receive_stream: WebTransportReceiveStream) -> None:
        event = Event(type=EventType.STREAM_CLOSED, data={"stream_id": TEST_STREAM_ID})
        await receive_stream._on_stream_closed(event)
        assert receive_stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    async def test_on_stream_closed_ignores_wrong_id(self, receive_stream: WebTransportReceiveStream) -> None:
        event = Event(type=EventType.STREAM_CLOSED, data={"stream_id": 999})
        await receive_stream._on_stream_closed(event)
        assert receive_stream.state == StreamState.OPEN

    @pytest.mark.asyncio
    async def test_read_all(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer
        await receive_stream._buffer.feed_data(data=b"chunk1")
        await receive_stream._buffer.feed_data(data=b"chunk2", eof=True)
        all_data = await receive_stream.read_all()
        assert all_data == b"chunk1chunk2"

    @pytest.mark.asyncio
    async def test_read_all_error_handling(
        self,
        receive_stream: WebTransportReceiveStream,
        mock_logger: Any,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(receive_stream, "read_iter", side_effect=StreamError("Read failed"))
        with pytest.raises(StreamError):
            await receive_stream.read_all()
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_all_max_size_exceeded(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer
        await receive_stream._buffer.feed_data(data=b"1234567890")
        with pytest.raises(StreamError, match="Stream size exceeds maximum"):
            await receive_stream.read_all(max_size=5)

    @pytest.mark.asyncio
    async def test_read_from_half_closed_local_with_eof(self, receive_stream: WebTransportReceiveStream) -> None:
        await receive_stream._set_state(StreamState.HALF_CLOSED_LOCAL)
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"final", eof=True)
        data = await receive_stream.read()
        assert data == b"final"
        assert receive_stream.state == StreamState.CLOSED

    @pytest.mark.asyncio
    async def test_read_generic_error(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        assert receive_stream._buffer is not None
        mocker.patch.object(receive_stream._buffer, "read", side_effect=ValueError("test error"))
        with pytest.raises(StreamError, match="Read operation failed: test error"):
            await receive_stream.read()
        assert receive_stream._stats.read_errors == 1

    @pytest.mark.asyncio
    async def test_read_iter(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer
        await receive_stream._buffer.feed_data(data=b"chunk1chunk2", eof=True)
        chunks = [chunk async for chunk in receive_stream.read_iter(chunk_size=6)]
        assert chunks == [b"chunk1", b"chunk2"]

    @pytest.mark.asyncio
    async def test_read_raises_exception(self, receive_stream: WebTransportReceiveStream) -> None:
        receive_stream._buffer = None
        with pytest.raises(StreamError, match="Internal state error: buffer is None"):
            await receive_stream.read()

    @pytest.mark.asyncio
    async def test_read_timeout_error(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        assert receive_stream._buffer is not None
        mocker.patch.object(receive_stream._buffer, "read", side_effect=TimeoutError("timeout"))
        with pytest.raises(TimeoutError):
            await receive_stream.read()
        assert receive_stream._stats.read_errors == 1

    @pytest.mark.asyncio
    async def test_read_when_closed_returns_empty(self, receive_stream: WebTransportReceiveStream) -> None:
        await receive_stream._set_state(StreamState.CLOSED)
        result = await receive_stream.read()
        assert result == b""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("n, expected", [(0, b""), (-1, ValueError)])
    async def test_readexactly_edge_cases(
        self, receive_stream: WebTransportReceiveStream, n: int, expected: Any
    ) -> None:
        if isinstance(expected, type) and issubclass(expected, Exception):
            with pytest.raises(expected):
                await receive_stream.readexactly(n=n)
        else:
            result = await receive_stream.readexactly(n=n)
            assert result == expected

    @pytest.mark.asyncio
    async def test_readexactly_incomplete_read(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer
        await receive_stream._buffer.feed_data(data=b"short", eof=True)
        with pytest.raises(asyncio.IncompleteReadError):
            await receive_stream.readexactly(n=10)

    @pytest.mark.asyncio
    async def test_readexactly_multiple_chunks(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        read_task = asyncio.create_task(receive_stream.readexactly(n=10))
        await asyncio.sleep(0)
        await receive_stream._buffer.feed_data(data=b"part1")
        await asyncio.sleep(0)
        assert not read_task.done()
        await receive_stream._buffer.feed_data(data=b"part2")
        result = await read_task
        assert result == b"part1part2"

    @pytest.mark.asyncio
    async def test_readline_success(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"hello\nworld")
        line = await receive_stream.readline()
        assert line == b"hello\n"

    @pytest.mark.asyncio
    async def test_readline_with_default_limit_exceeded(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=b"a" * (DEFAULT_STREAM_LINE_LIMIT + 1))
        with pytest.raises(
            StreamError,
            match=f"Separator not found within the configured limit of {DEFAULT_STREAM_LINE_LIMIT} bytes",
        ):
            await receive_stream.readline()

    @pytest.mark.asyncio
    async def test_readuntil_empty_separator_raises_error(self, receive_stream: WebTransportReceiveStream) -> None:
        with pytest.raises(ValueError, match="Separator cannot be empty"):
            await receive_stream.readuntil(separator=b"")

    @pytest.mark.asyncio
    async def test_readuntil_eof_before_separator(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer
        await receive_stream._buffer.feed_data(data=b"no separator", eof=True)
        data = await receive_stream.readuntil(separator=b"Z")
        assert data == b"no separator"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "feed_data, separator, limit, expected_error",
        [
            (
                b"a" * 11,
                b"Z",
                10,
                "Separator not found within the configured limit of 10 bytes",
            ),
            (
                b"long-line\n",
                b"\n",
                5,
                "Separator not found within the configured limit of 5 bytes",
            ),
        ],
    )
    async def test_readuntil_limit_exceeded(
        self,
        receive_stream: WebTransportReceiveStream,
        feed_data: bytes,
        separator: bytes,
        limit: int,
        expected_error: str,
    ) -> None:
        assert receive_stream._buffer is not None
        await receive_stream._buffer.feed_data(data=feed_data)
        with pytest.raises(StreamError, match=expected_error):
            await receive_stream.readuntil(separator=separator, limit=limit)

    @pytest.mark.asyncio
    async def test_readuntil_waits_for_data(self, receive_stream: WebTransportReceiveStream) -> None:
        assert receive_stream._buffer is not None
        read_task = asyncio.create_task(receive_stream.readuntil(separator=b"\n"))
        await asyncio.sleep(0)
        await receive_stream._buffer.feed_data(data=b"hello ")
        await asyncio.sleep(0)
        assert not read_task.done()
        await receive_stream._buffer.feed_data(data=b"world\n")
        result = await asyncio.wait_for(read_task, timeout=1.0)
        assert result == b"hello world\n"

    @pytest.mark.asyncio
    async def test_set_state_closed_idempotency(
        self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        teardown_spy = mocker.spy(receive_stream, "_teardown")
        await receive_stream._set_state(StreamState.CLOSED)
        assert teardown_spy.call_count == 1
        await receive_stream._set_state(StreamState.RESET_SENT)
        assert teardown_spy.call_count == 1

    @pytest.mark.asyncio
    async def test_set_state_idempotent(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        receive_stream._state = StreamState.OPEN
        mock_teardown = mocker.patch.object(receive_stream, "_teardown", new_callable=mocker.AsyncMock)
        await receive_stream._set_state(StreamState.OPEN)
        mock_teardown.assert_not_called()

    @pytest.mark.asyncio
    async def test_str_with_zero_uptime(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(StreamStats, "uptime", new_callable=mocker.PropertyMock, return_value=0.0)
        assert "uptime=0s" in str(receive_stream)

    @pytest.mark.asyncio
    async def test_teardown(
        self,
        receive_stream: WebTransportReceiveStream,
        mock_session: Any,
        mocker: MockerFixture,
    ) -> None:
        await receive_stream._set_state(StreamState.CLOSED)
        await receive_stream.wait_closed()
        assert mock_session.protocol_handler is not None
        expected_calls = [
            mocker.call(
                event_type=EventType.STREAM_DATA_RECEIVED,
                handler=receive_stream._on_data_received,
            ),
            mocker.call(
                event_type=EventType.STREAM_CLOSED,
                handler=receive_stream._on_stream_closed,
            ),
        ]
        mock_session.protocol_handler.off.assert_has_calls(expected_calls, any_order=True)

    @pytest.mark.asyncio
    async def test_teardown_no_session(self, receive_stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(receive_stream, "_session", return_value=None)
        await receive_stream._set_state(StreamState.CLOSED)
        await receive_stream.wait_closed()

    @pytest.mark.asyncio
    async def test_uninitialized_stream_raises_error(self, mock_session: Any) -> None:
        stream = WebTransportReceiveStream(stream_id=TEST_STREAM_ID, session=mock_session)
        with pytest.raises(StreamError, match="not initialized"):
            await stream.wait_closed()
        with pytest.raises(StreamError, match="not initialized"):
            await stream.read()


class TestWebTransportSendStream:
    @pytest.mark.asyncio
    async def test_abort(self, send_stream: WebTransportSendStream, mock_session: Any) -> None:
        await send_stream.abort(code=99)
        mock_session.protocol_handler.abort_stream.assert_called_once_with(stream_id=TEST_STREAM_ID, error_code=99)
        assert send_stream.state == StreamState.RESET_SENT

    @pytest.mark.asyncio
    async def test_abort_no_session(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mocker.patch.object(send_stream, "_session", return_value=None)
        await send_stream.abort(code=99)

    @pytest.mark.asyncio
    async def test_async_context_manager_aborts_on_exception(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        mock_abort = mocker.patch.object(stream, "abort", new_callable=mocker.AsyncMock)
        with pytest.raises(ValueError):
            async with stream:
                raise ValueError("Test Exception")
        mock_abort.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_already_closed(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mock_close = mocker.patch.object(send_stream, "close", new_callable=mocker.AsyncMock)
        mock_abort = mocker.patch.object(send_stream, "abort", new_callable=mocker.AsyncMock)
        await send_stream._set_state(StreamState.CLOSED)
        async with send_stream:
            pass
        mock_close.assert_not_called()
        mock_abort.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_context_manager_closes_on_success(self, mock_session: Any, mocker: MockerFixture) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        mock_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)
        async with stream:
            pass
        mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_gracefully(self, send_stream: WebTransportSendStream, mock_session: Any) -> None:
        await send_stream.close()
        await send_stream.wait_closed()
        assert mock_session.protocol_handler is not None
        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_with(
            stream_id=TEST_STREAM_ID, data=b"", end_stream=True
        )
        assert send_stream.state == StreamState.HALF_CLOSED_LOCAL

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error, expected_log_method",
        [
            (StreamError("Writer loop terminated"), "debug"),
            (StreamError("Some other error"), "warning"),
        ],
    )
    async def test_close_with_stream_error(
        self,
        send_stream: WebTransportSendStream,
        mock_logger: Any,
        mocker: MockerFixture,
        error: StreamError,
        expected_log_method: str,
    ) -> None:
        mocker.patch.object(send_stream, "write", side_effect=error)
        await send_stream.close()
        getattr(mock_logger, expected_log_method).assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_writer_restarts(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task and not send_stream._writer_task.done()
        original_task = send_stream._writer_task
        original_task.cancel()
        with suppress(asyncio.CancelledError):
            await original_task

        send_stream._ensure_writer_is_running()
        assert send_stream._writer_task is not original_task
        assert not send_stream._writer_task.done()

    @pytest.mark.asyncio
    async def test_flush_on_empty_buffer(self, send_stream: WebTransportSendStream) -> None:
        await send_stream.flush()

    @pytest.mark.asyncio
    async def test_flush_timeout(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        send_stream._write_timeout = 0.01
        await send_stream.write(data=b"some data", wait_flush=False)
        mocker.patch.object(send_stream._flushed_event, "wait", side_effect=asyncio.TimeoutError)

        with pytest.raises(TimeoutError, match="Flush timeout"):
            await send_stream.flush()

    @pytest.mark.asyncio
    async def test_initialize_with_no_connection_on_session(self, mock_session: Any) -> None:
        mock_session.connection = None
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        assert stream._max_buffer_size == 1024 * 1024

    @pytest.mark.asyncio
    async def test_on_stream_closed_ignores_wrong_id(self, send_stream: WebTransportSendStream) -> None:
        event = Event(type=EventType.STREAM_CLOSED, data={"stream_id": 999})
        await send_stream._on_stream_closed(event)
        assert send_stream.state == StreamState.OPEN

    @pytest.mark.asyncio
    async def test_set_state_idempotent(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        send_stream._state = StreamState.OPEN
        mock_teardown = mocker.patch.object(send_stream, "_teardown", new_callable=mocker.AsyncMock)
        await send_stream._set_state(StreamState.OPEN)
        mock_teardown.assert_not_called()

    @pytest.mark.asyncio
    async def test_teardown_cancels_and_awaits_writer(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        assert send_stream._writer_task and not send_stream._writer_task.done()
        cancel_spy = mocker.spy(send_stream._writer_task, "cancel")

        await send_stream._set_state(StreamState.CLOSED)

        cancel_spy.assert_called_once()
        assert send_stream._writer_task.done()

    @pytest.mark.asyncio
    async def test_teardown_no_session(self, send_stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mocker.patch.object(send_stream, "_session", return_value=None)
        await send_stream._teardown()

    @pytest.mark.asyncio
    async def test_teardown_with_done_writer_task(self, send_stream: WebTransportSendStream) -> None:
        assert send_stream._writer_task
        send_stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await send_stream._writer_task

        await send_stream._teardown()

    @pytest.mark.asyncio
    async def test_uninitialized_send_stream_raises_error(self, mock_session: Any) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        with pytest.raises(StreamError, match="not initialized"):
            await stream.flush()
        with pytest.raises(StreamError, match="not initialized"):
            await stream.write(data=b"test")
        with pytest.raises(StreamError, match="not initialized"):
            await stream._wait_for_buffer_space(1)
        with pytest.raises(StreamError, match="not initialized"):
            await stream._writer_loop()

    @pytest.mark.asyncio
    async def test_wait_for_buffer_space_timeout(self, send_stream: WebTransportSendStream) -> None:
        send_stream._max_buffer_size = 10
        send_stream._write_timeout = 0.01
        send_stream._write_buffer_size = 10
        assert send_stream._backpressure_event is not None
        send_stream._backpressure_event.clear()

        with pytest.raises(TimeoutError, match="Write timeout due to backpressure"):
            await send_stream.write(data=b"1", wait_flush=True)

    @pytest.mark.asyncio
    async def test_write_all_error_handling(
        self,
        send_stream: WebTransportSendStream,
        mock_logger: Any,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch.object(send_stream, "write", side_effect=StreamError("Write failed"))
        mock_abort = mocker.patch.object(send_stream, "abort", new_callable=mocker.AsyncMock)
        with pytest.raises(StreamError):
            await send_stream.write_all(data=b"test")
        mock_logger.error.assert_called_once()
        mock_abort.assert_awaited_once_with(code=1)

    @pytest.mark.asyncio
    async def test_write_all_success(self, send_stream: WebTransportSendStream, mock_session: Any) -> None:
        data_to_send = b"a" * 10000
        await send_stream.write_all(data=data_to_send, chunk_size=4000)

        assert mock_session.protocol_handler.send_webtransport_stream_data.call_count == 4
        last_call = mock_session.protocol_handler.send_webtransport_stream_data.call_args_list[-1]
        assert last_call.kwargs["end_stream"] is True
        assert send_stream.state == StreamState.HALF_CLOSED_LOCAL

    @pytest.mark.asyncio
    async def test_write_and_writer_loop_integration(self, mock_session: Any) -> None:
        stream = WebTransportSendStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        await stream.write(data=b"data", wait_flush=True)
        assert mock_session.protocol_handler is not None
        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_once_with(
            stream_id=TEST_STREAM_ID, data=b"data", end_stream=False
        )
        assert stream._stats.writes_count == 1

    @pytest.mark.asyncio
    async def test_write_empty_data(self, send_stream: WebTransportSendStream) -> None:
        await send_stream.write(data=b"")
        assert send_stream._stats.writes_count == 0

    @pytest.mark.asyncio
    async def test_write_handles_backpressure(
        self,
        send_stream: WebTransportSendStream,
        mock_session: Any,
        mocker: MockerFixture,
    ) -> None:
        send_stream._max_buffer_size = 10
        send_stream._backpressure_limit = 8
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = [
            FlowControlError("blocked"),
            None,
            None,
        ]
        credit_event_wait_spy = mocker.spy(mock_session._data_credit_event, "wait")

        asyncio.create_task(send_stream.write(data=b"12345678", wait_flush=True))
        await asyncio.sleep(0.01)
        credit_event_wait_spy.assert_called_once()
        assert send_stream._write_buffer_size == 8

        write_task = asyncio.create_task(send_stream.write(data=b"next", wait_flush=True))
        await asyncio.sleep(0.01)

        assert not write_task.done()
        assert send_stream._backpressure_event is not None
        assert not send_stream._backpressure_event.is_set()

        mock_session._data_credit_event.set()
        await asyncio.sleep(0.01)

        await asyncio.wait_for(write_task, timeout=1.0)
        assert send_stream._backpressure_event is not None
        assert send_stream._backpressure_event.is_set()

    @pytest.mark.asyncio
    async def test_write_large_data_chunks(self, send_stream: WebTransportSendStream, mock_session: Any) -> None:
        large_data = b"a" * (send_stream._WRITE_CHUNK_SIZE + 10)
        await send_stream.write(data=large_data, wait_flush=True)
        assert mock_session.protocol_handler.send_webtransport_stream_data.call_count == 2
        first_call, second_call = mock_session.protocol_handler.send_webtransport_stream_data.call_args_list
        assert len(first_call.kwargs["data"]) == send_stream._WRITE_CHUNK_SIZE
        assert len(second_call.kwargs["data"]) == 10
        assert second_call.kwargs["end_stream"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state",
        [StreamState.CLOSED, StreamState.RESET_SENT, StreamState.HALF_CLOSED_LOCAL],
    )
    async def test_write_not_writable(self, send_stream: WebTransportSendStream, state: StreamState) -> None:
        await send_stream._set_state(state)
        with pytest.raises(StreamError, match="Stream not writable"):
            await send_stream.write(data=b"data")

    @pytest.mark.asyncio
    async def test_writer_loop_cleanup_with_missing_events(self, send_stream: WebTransportSendStream) -> None:
        send_stream._flushed_event = None
        send_stream._write_lock = None
        assert send_stream._writer_task
        send_stream._writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await send_stream._writer_task

    @pytest.mark.asyncio
    async def test_writer_loop_flow_control_no_credit_event(
        self, send_stream: WebTransportSendStream, mock_session: Any
    ) -> None:
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = FlowControlError("credit exhausted")
        mock_session._data_credit_event = None

        with pytest.raises(StreamError, match="Flow control error but no data credit event"):
            await send_stream.write(data=b"test", wait_flush=True)
        await asyncio.sleep(0)
        assert send_stream.is_closed
        assert send_stream.state == StreamState.RESET_SENT

    @pytest.mark.asyncio
    async def test_writer_loop_flow_control_timeout(
        self,
        send_stream: WebTransportSendStream,
        mock_session: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = FlowControlError("credit exhausted")
        mocker.patch.object(mock_session._data_credit_event, "wait", side_effect=asyncio.TimeoutError)

        with pytest.raises(TimeoutError, match="Timeout waiting for data credit"):
            await send_stream.write(data=b"test", wait_flush=True)

        await asyncio.sleep(0)
        assert send_stream.state == StreamState.RESET_SENT

    @pytest.mark.asyncio
    async def test_writer_loop_handles_flow_control_error(
        self,
        send_stream: WebTransportSendStream,
        mock_session: Any,
        mocker: MockerFixture,
    ) -> None:
        send_stream._write_timeout = 2.0
        assert mock_session.protocol_handler is not None
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = [
            FlowControlError(message="credit exhausted"),
            None,
        ]

        event_was_waited = asyncio.Event()
        original_wait = mock_session._data_credit_event.wait

        async def new_wait() -> bool:
            event_was_waited.set()
            await original_wait()
            return True

        mocker.patch.object(mock_session._data_credit_event, "wait", side_effect=new_wait)
        write_task = asyncio.create_task(send_stream.write(data=b"data", wait_flush=True))

        await event_was_waited.wait()
        mock_session._data_credit_event.set()

        await write_task

        assert mock_session.protocol_handler.send_webtransport_stream_data.call_count == 2
        assert send_stream._stats.flow_control_errors == 1

    @pytest.mark.asyncio
    async def test_writer_loop_handles_generic_exception(
        self,
        send_stream: WebTransportSendStream,
        mock_session: Any,
        mock_logger: Any,
    ) -> None:
        mock_session.protocol_handler.send_webtransport_stream_data.side_effect = ValueError("generic error")
        with pytest.raises(ValueError):
            await send_stream.write(data=b"test", wait_flush=True)
        await asyncio.sleep(0)
        mock_logger.error.assert_called_once()
        assert send_stream.state == StreamState.RESET_SENT

    @pytest.mark.asyncio
    async def test_writer_loop_no_future(self, send_stream: WebTransportSendStream, mock_session: Any) -> None:
        await send_stream.write(data=b"test", wait_flush=False)
        await send_stream.flush()
        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_once_with(
            stream_id=TEST_STREAM_ID, data=b"test", end_stream=False
        )

    @pytest.mark.asyncio
    async def test_writer_loop_no_session_or_handler(
        self, send_stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(send_stream, "_session", return_value=None)
        with pytest.raises(StreamError, match="Session is not available"):
            await send_stream.write(data=b"test")

    @pytest.mark.asyncio
    async def test_writer_loop_processes_multiple_items(
        self, send_stream: WebTransportSendStream, mock_session: Any
    ) -> None:
        await send_stream.write(data=b"first", wait_flush=False)
        await send_stream.write(data=b"second", wait_flush=False)
        await send_stream.flush()

        assert mock_session.protocol_handler.send_webtransport_stream_data.call_count == 2
        call_args = mock_session.protocol_handler.send_webtransport_stream_data.call_args_list
        assert call_args[0].kwargs["data"] == b"first"
        assert call_args[1].kwargs["data"] == b"second"

    @pytest.mark.asyncio
    async def test_writer_loop_terminates_and_fails_pending_writes(
        self,
        send_stream: WebTransportSendStream,
        mock_session: Any,
        mocker: MockerFixture,
    ) -> None:
        await send_stream.write(data=b"processed", wait_flush=True)
        mock_session.protocol_handler.send_webtransport_stream_data.assert_called_once()

        assert send_stream._new_data_event is not None
        pause_event = asyncio.Event()
        mocker.patch.object(send_stream._new_data_event, "wait", side_effect=pause_event.wait)

        write_task_pending = asyncio.create_task(send_stream.write(data=b"pending", wait_flush=True))
        await asyncio.sleep(0)

        assert send_stream._writer_task is not None
        send_stream._writer_task.cancel()
        with pytest.raises(StreamError, match="Writer loop terminated"):
            await write_task_pending


class TestWebTransportStreamDiagnostics:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state, stats_attrs, expected_issue",
        [
            (StreamState.RESET_RECEIVED, {}, "reset by remote peer"),
            (StreamState.RESET_SENT, {}, "reset locally"),
            (
                StreamState.OPEN,
                {"reads_count": 11, "read_errors": 2},
                "High read error rate",
            ),
            (
                StreamState.OPEN,
                {"writes_count": 11, "write_errors": 2},
                "High write error rate",
            ),
            (
                StreamState.OPEN,
                {"reads_count": 1, "total_read_time": 2.0},
                "Slow read operations",
            ),
            (
                StreamState.OPEN,
                {"writes_count": 1, "total_write_time": 2.0},
                "Slow write operations",
            ),
            (
                StreamState.OPEN,
                {"uptime_override": 4000.0, "reads_count": 0, "writes_count": 0},
                "Stream appears stale",
            ),
        ],
    )
    async def test_diagnose_issues_all_issues(
        self,
        mock_session: Any,
        mocker: MockerFixture,
        state: StreamState,
        stats_attrs: dict[str, Any],
        expected_issue: str,
    ) -> None:
        stream = WebTransportStream(stream_id=TEST_STREAM_ID, session=mock_session)
        await stream.initialize()
        stream._state = state
        if "uptime_override" in stats_attrs:
            mocker.patch(
                "pywebtransport.stream.stream.get_timestamp",
                return_value=stream._stats.created_at + stats_attrs["uptime_override"],
            )
        for attr, value in stats_attrs.items():
            if hasattr(stream._stats, attr):
                setattr(stream._stats, attr, value)

        issues = stream.diagnose_issues()
        assert any(expected_issue in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_diagnose_issues_no_issues(self, bidirectional_stream: WebTransportStream) -> None:
        issues = bidirectional_stream.diagnose_issues()
        assert not issues

    @pytest.mark.asyncio
    async def test_monitor_health_handles_exception(
        self,
        bidirectional_stream: WebTransportStream,
        mock_logger: Any,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch("asyncio.sleep", side_effect=ValueError("Test Error"))
        await bidirectional_stream.monitor_health()
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_monitor_health_logs_warning(
        self, bidirectional_stream: WebTransportStream, mock_logger: Any
    ) -> None:
        bidirectional_stream._stats.reads_count = 10
        bidirectional_stream._stats.writes_count = 10
        bidirectional_stream._stats.read_errors = 3
        task = asyncio.create_task(bidirectional_stream.monitor_health(check_interval=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_monitor_health_no_warning(self, bidirectional_stream: WebTransportStream, mock_logger: Any) -> None:
        task = asyncio.create_task(bidirectional_stream.monitor_health(check_interval=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_monitor_health_stops_when_closed(self, bidirectional_stream: WebTransportStream) -> None:
        await bidirectional_stream._set_state(StreamState.CLOSED)
        task = asyncio.create_task(bidirectional_stream.monitor_health(check_interval=0.01))
        await asyncio.sleep(0.05)
        assert task.done()
