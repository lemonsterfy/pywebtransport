"""Unit tests for the pywebtransport.stream.stream module."""

import asyncio
from collections import deque
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ConnectionError,
    ErrorCodes,
    StreamError,
    TimeoutError,
    WebTransportReceiveStream,
    WebTransportSendStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport._protocol.events import (
    UserGetStreamDiagnostics,
    UserResetStream,
    UserSendStreamData,
    UserStopStream,
    UserStreamRead,
)
from pywebtransport.stream import StreamDiagnostics, _BaseStream
from pywebtransport.types import StreamDirection, StreamState


class TestBaseStream:

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        session._connection = mocker.Mock()
        return cast(MagicMock, session)

    @pytest.mark.asyncio
    async def test_diagnostics_connection_closed(self, mock_session: MagicMock, mocker: MockerFixture) -> None:
        stream = _BaseStream(session=mock_session, stream_id=1)
        mock_session._send_event_to_engine.side_effect = ConnectionError("Closed")

        with pytest.raises(StreamError, match="Connection is closed") as exc_info:
            await stream.diagnostics()

        assert isinstance(exc_info.value.__cause__, ConnectionError)

    @pytest.mark.asyncio
    async def test_diagnostics_handles_deque_write_buffer(self, mock_session: MagicMock) -> None:
        stream = _BaseStream(session=mock_session, stream_id=1)

        async def engine_behavior(event: Any) -> None:
            event.future.set_result(
                {
                    "stream_id": 1,
                    "session_id": "1",
                    "direction": StreamDirection.BIDIRECTIONAL,
                    "state": StreamState.OPEN,
                    "created_at": 0.0,
                    "bytes_sent": 0,
                    "bytes_received": 0,
                    "read_buffer": b"",
                    "read_buffer_size": 0,
                    "pending_read_requests": [],
                    "write_buffer": deque([(b"data", None, False)]),
                    "write_buffer_size": 4,
                    "close_code": None,
                    "close_reason": None,
                    "closed_at": None,
                }
            )

        mock_session._send_event_to_engine.side_effect = engine_behavior

        diag = await stream.diagnostics()

        assert isinstance(diag.write_buffer, list)
        assert diag.write_buffer == [(b"data", None, False)]

    def test_init_sets_weakref(self, mock_session: MagicMock) -> None:
        stream = _BaseStream(session=mock_session, stream_id=1)

        assert stream.session is mock_session

    def test_is_closed_false_when_open(self, mock_session: MagicMock) -> None:
        stream = _BaseStream(session=mock_session, stream_id=1)
        stream._cached_state = StreamState.OPEN

        assert stream.is_closed is False

    def test_is_closed_true_when_closed(self, mock_session: MagicMock) -> None:
        stream = _BaseStream(session=mock_session, stream_id=1)
        stream._cached_state = StreamState.CLOSED

        assert stream.is_closed is True

    def test_repr(self, mock_session: MagicMock) -> None:
        stream = _BaseStream(session=mock_session, stream_id=1)
        stream._cached_state = StreamState.OPEN

        repr_str = repr(stream)

        assert "id=1" in repr_str
        assert "state=open" in repr_str
        assert "_BaseStream" in repr_str

    def test_session_property_raises_if_gone(self, mocker: MockerFixture) -> None:
        dummy_session = mocker.Mock(spec=WebTransportSession)
        stream = _BaseStream(session=dummy_session, stream_id=1)
        mocker.patch.object(stream, "_session", return_value=None)

        with pytest.raises(ConnectionError, match="Session is gone"):
            _ = stream.session


class TestStreamDiagnostics:

    def test_init(self) -> None:
        diagnostics = StreamDiagnostics(
            stream_id=1,
            session_id="100",
            direction=StreamDirection.BIDIRECTIONAL,
            state=StreamState.OPEN,
            created_at=1000.0,
            bytes_sent=50,
            bytes_received=100,
            read_buffer=b"data",
            read_buffer_size=4,
            pending_read_requests=[],
            write_buffer=[],
            write_buffer_size=0,
            close_code=None,
            close_reason=None,
            closed_at=None,
        )

        assert diagnostics.stream_id == 1
        assert diagnostics.state == StreamState.OPEN


@pytest.mark.asyncio
class TestWebTransportReceiveStream:

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        conn = mocker.Mock()
        conn.config.max_stream_read_buffer = 1024
        conn.config.read_timeout = 0.01
        session._connection = mocker.Mock(return_value=conn)
        session._send_event_to_engine = mocker.AsyncMock()
        return cast(MagicMock, session)

    @pytest.fixture
    def stream(self, mock_session: MagicMock) -> WebTransportReceiveStream:
        return WebTransportReceiveStream(session=mock_session, stream_id=1)

    async def test_aiter(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "read", side_effect=[b"chunk1", b"chunk2", b""])
        chunks = []

        async for chunk in stream:
            chunks.append(chunk)

        assert chunks == [b"chunk1", b"chunk2"]

    async def test_aiter_handles_error(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        error = StreamError("End", stream_id=1)
        error.error_code = ErrorCodes.NO_ERROR
        mocker.patch.object(stream, "read", side_effect=error)
        chunks = []

        async for chunk in stream:
            chunks.append(chunk)

        assert chunks == []

    async def test_aiter_handles_unexpected_error(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(stream, "read", side_effect=ValueError("Unexpected"))

        with pytest.raises(ValueError, match="Unexpected"):
            await stream.__anext__()

    async def test_aiter_re_raises_other_stream_errors(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        error = StreamError("Fatal", stream_id=1)
        error.error_code = ErrorCodes.INTERNAL_ERROR
        mocker.patch.object(stream, "read", side_effect=error)

        with pytest.raises(StreamError, match="Fatal"):
            await stream.__anext__()

    async def test_anext_stops_on_empty(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "read", return_value=b"")

        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    async def test_can_read(self, stream: WebTransportReceiveStream) -> None:
        stream._cached_state = StreamState.OPEN

        assert stream.can_read

    @pytest.mark.parametrize("state", [StreamState.CLOSED, StreamState.RESET_RECEIVED])
    async def test_can_read_false_if_closed_or_reset(
        self, stream: WebTransportReceiveStream, state: StreamState
    ) -> None:
        stream._cached_state = state

        assert not stream.can_read

    async def test_close(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        spy_stop = mocker.patch.object(stream, "stop_receiving", new_callable=mocker.AsyncMock)

        await stream.close()

        spy_stop.assert_awaited_once_with()

    async def test_context_manager(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        spy_stop = mocker.patch.object(stream, "stop_receiving", new_callable=mocker.AsyncMock)

        async with stream as s:
            assert s is stream

        spy_stop.assert_awaited_once_with()

    async def test_diagnostics(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserGetStreamDiagnostics)
            event.future.set_result(
                {
                    "stream_id": 1,
                    "session_id": "100",
                    "direction": StreamDirection.RECEIVE_ONLY,
                    "state": StreamState.OPEN,
                    "created_at": 0.0,
                    "bytes_sent": 0,
                    "bytes_received": 0,
                    "read_buffer": b"",
                    "read_buffer_size": 0,
                    "pending_read_requests": [],
                    "write_buffer": [],
                    "write_buffer_size": 0,
                    "close_code": None,
                    "close_reason": None,
                    "closed_at": None,
                }
            )

        mock_session._send_event_to_engine.side_effect = engine_behavior

        diag = await stream.diagnostics()

        mock_session._send_event_to_engine.assert_awaited_once()
        assert diag.stream_id == 1

    async def test_diagnostics_connection_closed(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock
    ) -> None:
        mock_session._send_event_to_engine.side_effect = ConnectionError("Closed")

        with pytest.raises(StreamError, match="Connection is closed"):
            await stream.diagnostics()

    async def test_direction(self, stream: WebTransportReceiveStream) -> None:
        assert stream.direction == StreamDirection.RECEIVE_ONLY

    async def test_find_in_buffer_seam_exact_match(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"123a"))
        stream._read_buffer.append(memoryview(b"b456"))
        stream._read_buffer_size = 8

        idx = stream._find_in_buffer(sep=b"ab")

        assert idx == 3

    async def test_find_in_buffer_seam_not_found(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"aaa"))
        stream._read_buffer.append(memoryview(b"ccc"))
        stream._read_buffer_size = 6

        idx = stream._find_in_buffer(sep=b"ab")

        assert idx == -1

    async def test_find_in_buffer_skip_logic(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"skip_me"))
        stream._read_buffer.append(memoryview(b"123_find"))
        stream._read_buffer_size = 15

        idx = stream._find_in_buffer(sep=b"find", start=8)

        assert idx == 11

    async def test_find_in_buffer_small_chunks_large_sep(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"a"))
        stream._read_buffer.append(memoryview(b"b"))
        stream._read_buffer.append(memoryview(b"c"))
        stream._read_buffer.append(memoryview(b"d"))
        stream._read_buffer_size = 4

        idx = stream._find_in_buffer(sep=b"bc")

        assert idx == 1

    async def test_read_all(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "read", side_effect=[b"a", b"b", b""])

        data = await stream.read_all()

        assert data == b"ab"

    async def test_read_all_logs_warning(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        error = StreamError("Fail", stream_id=1)
        error.error_code = ErrorCodes.INTERNAL_ERROR
        mocker.patch.object(stream, "read", side_effect=error)
        spy_logger = mocker.patch("pywebtransport.stream.logger")

        data = await stream.read_all()

        assert data == b""
        spy_logger.warning.assert_called_once()

    async def test_read_all_with_error(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        error = StreamError("Fail", stream_id=1)
        error.error_code = ErrorCodes.INTERNAL_ERROR
        mocker.patch.object(stream, "read", side_effect=[b"a", error])

        data = await stream.read_all()

        assert data == b"a"

    async def test_read_from_buffer_all(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"hello"))
        stream._read_buffer.append(memoryview(b"world"))
        stream._read_buffer_size = 10

        data_partial = await stream.read(max_bytes=5)
        data_all = await stream.read(max_bytes=-1)

        assert data_partial == b"hello"
        assert data_all == b"world"
        assert len(stream._read_buffer) == 0
        assert stream._read_buffer_size == 0

    async def test_read_from_engine(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserStreamRead)
            event.future.set_result(b"engine_data")

        mock_session._send_event_to_engine.side_effect = engine_behavior

        data = await stream.read(max_bytes=100)

        assert data == b"engine_data"
        mock_session._send_event_to_engine.assert_awaited_once()
        event = mock_session._send_event_to_engine.await_args[1]["event"]
        assert event.max_bytes == 100

    async def test_read_from_engine_generic_exception(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(stream.session, "_send_event_to_engine")

        class MockTimeoutGeneric:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise RuntimeError("Fatal")

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeoutGeneric)

        with pytest.raises(RuntimeError, match="Fatal"):
            await stream._read_from_engine()

    async def test_read_from_engine_no_connection(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(stream, "_session", return_value=None)

        with pytest.raises(ConnectionError, match="Session is gone"):
            await stream._read_from_engine()

    async def test_read_from_engine_timeout(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_session._send_event_to_engine.side_effect = None
        mock_fut = mocker.Mock(spec=asyncio.Future)
        mock_fut.done.return_value = False
        mock_loop = mocker.Mock()
        mock_loop.create_future.return_value = mock_fut
        mocker.patch("asyncio.get_running_loop", return_value=mock_loop)

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> "MockTimeout":
                return self

            async def __aexit__(self, *args: Any) -> None:
                raise asyncio.TimeoutError()

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="read operation timed out"):
            await stream.read()

        mock_fut.cancel.assert_called_once()

    async def test_read_handles_stream_state_error(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        error = StreamError("State error", stream_id=1)
        error.error_code = ErrorCodes.STREAM_STATE_ERROR
        mocker.patch.object(stream, "_read_from_engine", side_effect=error)

        data = await stream.read()

        assert data == b""
        assert stream._read_eof is True

    async def test_read_re_raises_other_stream_errors(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        error = StreamError("Fatal", stream_id=1)
        error.error_code = ErrorCodes.INTERNAL_ERROR
        mocker.patch.object(stream, "_read_from_engine", side_effect=error)

        with pytest.raises(StreamError, match="Fatal"):
            await stream.read()

    async def test_read_sets_eof_and_returns_empty(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result(None)

        mock_session._send_event_to_engine.side_effect = engine_behavior

        data1 = await stream.read()

        assert data1 == b""
        assert stream._read_eof is True

    async def test_read_when_closed(self, stream: WebTransportReceiveStream) -> None:
        stream._cached_state = StreamState.CLOSED

        data = await stream.read()

        assert data == b""
        assert stream._read_eof is True

    async def test_read_when_eof_pre_set(self, stream: WebTransportReceiveStream) -> None:
        stream._read_eof = True

        assert await stream.read() == b""

    async def test_readexactly_buffer_limit_exceeded(self, stream: WebTransportReceiveStream) -> None:
        with pytest.raises(StreamError, match="Read request .* exceeds max read buffer"):
            await stream.readexactly(n=2000)

    async def test_readexactly_eof_from_engine(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "_read_from_engine", return_value=None)

        with pytest.raises(asyncio.IncompleteReadError):
            await stream.readexactly(n=5)

    async def test_readexactly_eof_in_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"short"))
        stream._read_buffer_size = 5
        stream._read_eof = True

        with pytest.raises(asyncio.IncompleteReadError):
            await stream.readexactly(n=10)

    async def test_readexactly_from_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"helloworld"))
        stream._read_buffer_size = 10

        data = await stream.readexactly(n=5)

        assert data == b"hello"
        assert stream._read_buffer[0].tobytes() == b"world"
        assert stream._read_buffer_size == 5

    async def test_readexactly_negative(self, stream: WebTransportReceiveStream) -> None:
        with pytest.raises(ValueError, match="n must be a non-negative integer"):
            await stream.readexactly(n=-1)

    async def test_readexactly_no_connection(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "_session", return_value=None)

        with pytest.raises(ConnectionError, match="Session is gone"):
            await stream.readexactly(n=10)

    async def test_readexactly_pulls_from_engine(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(stream, "_read_from_engine", side_effect=[memoryview(b"he"), memoryview(b"llo")])

        data = await stream.readexactly(n=5)

        assert data == b"hello"

    async def test_readexactly_raises_if_engine_chunk_overflows_buffer(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture, mock_session: MagicMock
    ) -> None:
        mock_session._connection.return_value.config.max_stream_read_buffer = 10
        mocker.patch.object(stream, "_read_from_engine", return_value=memoryview(b"overflowing_chunk"))

        with pytest.raises(StreamError, match="Read buffer limit"):
            await stream.readexactly(n=10)

    async def test_readexactly_timeout(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="readexactly timed out"):
            await stream.readexactly(n=1)

    async def test_readexactly_zero(self, stream: WebTransportReceiveStream) -> None:
        data = await stream.readexactly(n=0)

        assert data == b""

    async def test_readline(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "readuntil", return_value=b"line\n")

        data = await stream.readline()

        assert data == b"line\n"
        cast(MagicMock, stream.readuntil).assert_awaited_once_with(separator=b"\n", limit=-1)

    async def test_readuntil_buffer_limit_exceeded(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture, mock_session: MagicMock
    ) -> None:
        mock_session._connection.return_value.config.max_stream_read_buffer = 5
        stream._read_buffer.append(memoryview(b"123"))
        stream._read_buffer_size = 3
        mocker.patch.object(stream, "_read_from_engine", return_value=memoryview(b"456"))

        with pytest.raises(StreamError, match="Read buffer limit .* exceeded"):
            await stream.readuntil(separator=b"\n")

    async def test_readuntil_found_after_pull(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        stream._read_buffer.append(memoryview(b"one"))
        stream._read_buffer_size = 3
        mocker.patch.object(stream, "_read_from_engine", return_value=memoryview(b"\ntwo"))

        data = await stream.readuntil(separator=b"\n")

        assert data == b"one\n"
        assert stream._read_buffer[0].tobytes() == b"two"
        assert stream._read_buffer_size == 3

    async def test_readuntil_found_in_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"one\ntwo"))
        stream._read_buffer_size = 7

        data = await stream.readuntil(separator=b"\n")

        assert data == b"one\n"
        assert stream._read_buffer[0].tobytes() == b"two"
        assert stream._read_buffer_size == 3

    async def test_readuntil_limit_checks(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        mock_session._connection.return_value.config.max_stream_read_buffer = 100
        stream._read_buffer.append(memoryview(b"123"))
        stream._read_buffer_size = 3

        with pytest.raises(StreamError, match="Read limit .* exceeds max read buffer"):
            await stream.readuntil(separator=b"\n", limit=200)

    async def test_readuntil_limit_exceeded_in_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"long line\n"))
        stream._read_buffer_size = 10

        with pytest.raises(StreamError, match="line over limit"):
            await stream.readuntil(separator=b"\n", limit=5)

    async def test_readuntil_limit_exceeds_max_buffer(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock
    ) -> None:
        mock_session._connection.return_value.config.max_stream_read_buffer = 10

        with pytest.raises(StreamError, match="Read limit .* exceeds max read buffer"):
            await stream.readuntil(separator=b"\n", limit=20)

    async def test_readuntil_no_connection(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "_session", return_value=None)

        with pytest.raises(ConnectionError, match="Session is gone"):
            await stream.readuntil(separator=b"\n")

    async def test_readuntil_not_found_within_limit_buffer_overflow(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"123456"))
        stream._read_buffer_size = 6

        with pytest.raises(StreamError, match="separator not found within limit"):
            await stream.readuntil(separator=b"\n", limit=5)

    async def test_readuntil_offset_logic_branch_coverage(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        stream._read_buffer.append(memoryview(b"abc"))
        stream._read_buffer_size = 3
        mocker.patch.object(stream, "_read_from_engine", return_value=memoryview(b"z"))

        data1 = await stream.readuntil(separator=b"z")

        assert data1 == b"abcz"

        stream._read_buffer.clear()
        stream._read_buffer_size = 0
        mocker.patch.object(stream, "_read_from_engine", return_value=memoryview(b"z"))

        data2 = await stream.readuntil(separator=b"z")

        assert data2 == b"z"

    async def test_readuntil_optim_offset(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        stream._read_buffer.append(memoryview(b"abc"))
        stream._read_buffer_size = 3
        mocker.patch.object(stream, "_read_from_engine", return_value=memoryview(b"defz"))

        data = await stream.readuntil(separator=b"z")

        assert data == b"abcdefz"

    async def test_readuntil_raises_on_empty_separator(self, stream: WebTransportReceiveStream) -> None:
        with pytest.raises(ValueError):
            await stream.readuntil(separator=b"")

    async def test_readuntil_returns_buffer_at_eof(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        stream._read_buffer.append(memoryview(b"partial"))
        stream._read_buffer_size = 7
        mocker.patch.object(stream, "_read_from_engine", return_value=None)

        with pytest.raises(asyncio.IncompleteReadError) as exc_info:
            await stream.readuntil(separator=b"\n")

        assert exc_info.value.partial == b"partial"
        assert len(stream._read_buffer) == 0
        assert stream._read_buffer_size == 0
        assert stream._read_eof is True

    async def test_readuntil_search_complex_seam(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"a"))
        stream._read_buffer.append(memoryview(b"b"))
        stream._read_buffer_size = 2

        idx = stream._find_in_buffer(sep=b"ab", start=0)

        assert idx == 0

    async def test_readuntil_separator_not_found_within_limit(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(memoryview(b"123456"))
        stream._read_buffer_size = 6

        with pytest.raises(StreamError, match="separator not found within limit"):
            await stream.readuntil(separator=b"\n", limit=5)

    async def test_readuntil_timeout(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="readuntil timed out"):
            await stream.readuntil(separator=b"\n")

    async def test_stop_receiving(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserStopStream)
            event.future.set_result(None)

        mock_session._send_event_to_engine.side_effect = engine_behavior

        await stream.stop_receiving(error_code=123)

        mock_session._send_event_to_engine.assert_awaited_once()
        event = mock_session._send_event_to_engine.await_args[1]["event"]
        assert event.error_code == 123


@pytest.mark.asyncio
class TestWebTransportSendStream:

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        conn = mocker.Mock()
        conn.config.write_timeout = 0.01
        session._connection = mocker.Mock(return_value=conn)
        session._send_event_to_engine = mocker.AsyncMock()
        return cast(MagicMock, session)

    @pytest.fixture
    def stream(self, mock_session: MagicMock) -> WebTransportSendStream:
        return WebTransportSendStream(session=mock_session, stream_id=2)

    async def test_can_write(self, stream: WebTransportSendStream) -> None:
        stream._cached_state = StreamState.OPEN

        assert stream.can_write

    @pytest.mark.parametrize("state", [StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED, StreamState.RESET_SENT])
    async def test_can_write_false_if_closed_or_reset(self, stream: WebTransportSendStream, state: StreamState) -> None:
        stream._cached_state = state

        assert not stream.can_write

    async def test_close(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_write = mocker.patch.object(stream, "write", new_callable=mocker.AsyncMock)

        await stream.close()

        spy_write.assert_awaited_once_with(data=b"", end_stream=True)

    async def test_close_ignores_stream_error(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "write", side_effect=StreamError("Closed", stream_id=2))

        await stream.close()

    async def test_close_propagates_unexpected_error(
        self, stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(stream, "write", side_effect=ValueError("Boom"))

        with pytest.raises(ValueError):
            await stream.close()

    async def test_close_with_error_code(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_stop = mocker.patch.object(stream, "stop_sending", new_callable=mocker.AsyncMock)

        await stream.close(error_code=99)

        spy_stop.assert_awaited_once_with(error_code=99)

    async def test_context_manager_cancelled_error(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(asyncio.CancelledError):
            async with stream:
                raise asyncio.CancelledError()

        spy_close.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)

    async def test_context_manager_clean_exit(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        async with stream as s:
            assert s is stream

        spy_close.assert_awaited_once_with(error_code=None)

    async def test_context_manager_custom_error_code(
        self, stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        class CustomError(Exception):
            error_code = 12345

        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(CustomError):
            async with stream:
                raise CustomError()

        spy_close.assert_awaited_once_with(error_code=12345)

    async def test_context_manager_exception_exit(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(ValueError):
            async with stream:
                raise ValueError("Error")

        spy_close.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)

    async def test_context_manager_exception_with_error_code_attribute(
        self, stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        class WeirdException(BaseException):
            error_code = 999

        with pytest.raises(WeirdException):
            async with stream:
                raise WeirdException()

        spy_close.assert_awaited_once_with(error_code=999)

    async def test_context_manager_generic_exception(
        self, stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(RuntimeError):
            async with stream:
                raise RuntimeError("Generic failure")

        spy_close.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)

    async def test_direction(self, stream: WebTransportSendStream) -> None:
        assert stream.direction == StreamDirection.SEND_ONLY

    async def test_stop_sending(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserResetStream)
            event.future.set_result(None)

        mock_session._send_event_to_engine.side_effect = engine_behavior

        await stream.stop_sending(error_code=404)

        mock_session._send_event_to_engine.assert_awaited_once()
        event = mock_session._send_event_to_engine.await_args[1]["event"]
        assert event.error_code == 404

    async def test_write(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserSendStreamData)
            event.future.set_result(None)

        mock_session._send_event_to_engine.side_effect = engine_behavior

        await stream.write(data=b"data", end_stream=True)

        mock_session._send_event_to_engine.assert_awaited_once()
        event = mock_session._send_event_to_engine.await_args[1]["event"]
        assert event.data == b"data"
        assert event.end_stream is True

    async def test_write_all(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_write = mocker.patch.object(stream, "write", new_callable=mocker.AsyncMock)

        await stream.write_all(data=b"1234", chunk_size=2)

        assert spy_write.await_count == 2
        spy_write.assert_has_awaits(
            [mocker.call(data=b"12", end_stream=False), mocker.call(data=b"34", end_stream=True)]
        )

    async def test_write_all_empty(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_write = mocker.patch.object(stream, "write", new_callable=mocker.AsyncMock)

        await stream.write_all(data=b"")

        spy_write.assert_awaited_once_with(data=b"", end_stream=True)

    async def test_write_all_error(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "write", side_effect=StreamError("Fail", stream_id=2))
        spy_stop = mocker.patch.object(stream, "stop_sending", new_callable=mocker.AsyncMock)

        with pytest.raises(StreamError):
            await stream.write_all(data=b"data")

        spy_stop.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)

    async def test_write_all_memoryview(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        spy_write = mocker.patch.object(stream, "write", new_callable=mocker.AsyncMock)
        data = memoryview(b"1234")

        await stream.write_all(data=data, chunk_size=2)

        assert spy_write.await_count == 2
        args1 = spy_write.await_args_list[0].kwargs
        args2 = spy_write.await_args_list[1].kwargs
        assert args1["data"] == data[:2]
        assert args1["end_stream"] is False
        assert args2["data"] == data[2:]
        assert args2["end_stream"] is True

    async def test_write_empty_no_fin(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        await stream.write(data=b"", end_stream=False)

        mock_session._send_event_to_engine.assert_not_awaited()

    async def test_write_empty_skipped(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        await stream.write(data=b"")

        mock_session._send_event_to_engine.assert_not_awaited()

    async def test_write_generic_exception_in_wait_for(
        self, stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        class MockTimeoutGeneric:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise Exception("Fatal Error inside wait_for")

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeoutGeneric)

        with pytest.raises(Exception, match="Fatal Error inside wait_for"):
            await stream.write(data=b"data")

    async def test_write_handles_type_error(self, stream: WebTransportSendStream) -> None:
        with pytest.raises(TypeError):
            await stream.write(data=123)  # type: ignore[arg-type]

    async def test_write_memoryview(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserSendStreamData)
            event.future.set_result(None)

        mock_session._send_event_to_engine.side_effect = engine_behavior
        data = memoryview(b"data")

        await stream.write(data=data, end_stream=True)

        mock_session._send_event_to_engine.assert_awaited_once()
        event = mock_session._send_event_to_engine.await_args[1]["event"]
        assert event.data == data
        assert event.end_stream is True

    async def test_write_no_connection(self, stream: WebTransportSendStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "_session", return_value=None)

        with pytest.raises(ConnectionError, match="Session is gone"):
            await stream.write(data=b"data")

    async def test_write_timeout(
        self, stream: WebTransportSendStream, mock_session: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_session._send_event_to_engine.side_effect = None
        mock_fut = mocker.Mock(spec=asyncio.Future)
        mock_fut.done.return_value = False
        mock_loop = mocker.Mock()
        mock_loop.create_future.return_value = mock_fut
        mocker.patch("asyncio.get_running_loop", return_value=mock_loop)

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> "MockTimeout":
                return self

            async def __aexit__(self, *args: Any) -> None:
                raise asyncio.TimeoutError()

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="write operation timed out"):
            await stream.write(data=b"data")

        mock_fut.cancel.assert_called_once()


@pytest.mark.asyncio
class TestWebTransportStream:

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        session._connection = mocker.Mock()
        return cast(MagicMock, session)

    @pytest.fixture
    def stream(self, mock_session: MagicMock) -> WebTransportStream:
        return WebTransportStream(session=mock_session, stream_id=3)

    async def test_close(self, stream: WebTransportStream, mocker: MockerFixture) -> None:
        spy_send_close = mocker.patch.object(WebTransportSendStream, "close", new_callable=mocker.AsyncMock)
        spy_recv_stop = mocker.patch.object(WebTransportReceiveStream, "stop_receiving", new_callable=mocker.AsyncMock)

        await stream.close(error_code=None)

        spy_send_close.assert_awaited_once_with(stream, error_code=None)
        spy_recv_stop.assert_awaited_once_with(stream, error_code=ErrorCodes.NO_ERROR)

    async def test_close_with_error(self, stream: WebTransportStream, mocker: MockerFixture) -> None:
        spy_send_close = mocker.patch.object(WebTransportSendStream, "close", new_callable=mocker.AsyncMock)
        spy_recv_stop = mocker.patch.object(WebTransportReceiveStream, "stop_receiving", new_callable=mocker.AsyncMock)

        await stream.close(error_code=123)

        spy_send_close.assert_awaited_once_with(stream, error_code=123)
        spy_recv_stop.assert_awaited_once_with(stream, error_code=123)

    async def test_context_manager_cancelled_error(self, stream: WebTransportStream, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(asyncio.CancelledError):
            async with stream:
                raise asyncio.CancelledError()

        spy_close.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)

    async def test_context_manager_custom_error_code(self, stream: WebTransportStream, mocker: MockerFixture) -> None:
        class CustomError(Exception):
            error_code = 12345

        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(CustomError):
            async with stream:
                raise CustomError()

        spy_close.assert_awaited_once_with(error_code=12345)

    async def test_context_manager_exception_with_error_code_attribute(
        self, stream: WebTransportStream, mocker: MockerFixture
    ) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        class WeirdException(BaseException):
            error_code = 777

        with pytest.raises(WeirdException):
            async with stream:
                raise WeirdException()

        spy_close.assert_awaited_once_with(error_code=777)

    async def test_context_manager_exit(self, stream: WebTransportStream, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        async with stream:
            pass

        spy_close.assert_awaited_once_with(error_code=None)

    async def test_context_manager_generic_exception(self, stream: WebTransportStream, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(RuntimeError):
            async with stream:
                raise RuntimeError("Generic failure")

        spy_close.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)

    async def test_direction(self, stream: WebTransportStream) -> None:
        assert stream.direction == StreamDirection.BIDIRECTIONAL
