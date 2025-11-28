"""Unit tests for the pywebtransport.stream.stream module."""

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ConnectionError,
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
from pywebtransport._protocol.state import StreamStateData
from pywebtransport.constants import ErrorCodes
from pywebtransport.stream.stream import StreamDiagnostics, _BaseStream
from pywebtransport.types import StreamDirection, StreamState


class TestBaseStream:

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        session._connection = mocker.Mock()
        session._connection._engine = mocker.Mock()
        session._connection._engine._state.streams = mocker.Mock()
        return cast(MagicMock, session)

    def test_get_engine_state_missing_state_attr(self, mock_session: MagicMock) -> None:
        del mock_session._connection._engine._state
        stream = _BaseStream(session=mock_session, stream_id=1)

        assert stream._get_engine_state() is None

    def test_get_engine_state_no_connection(self, mock_session: MagicMock) -> None:
        mock_session._connection = None
        stream = _BaseStream(session=mock_session, stream_id=1)

        assert stream.state == StreamState.CLOSED

    def test_get_engine_state_no_engine(self, mock_session: MagicMock) -> None:
        del mock_session._connection._engine
        stream = _BaseStream(session=mock_session, stream_id=1)

        assert stream.state == StreamState.CLOSED

    def test_is_closed_true_when_no_state(self, mock_session: MagicMock) -> None:
        mock_session._connection._engine._state.streams.get.return_value = None
        stream = _BaseStream(session=mock_session, stream_id=1)

        assert stream.is_closed is True

    def test_repr_closed_when_no_state(self, mock_session: MagicMock) -> None:
        mock_session._connection._engine._state.streams.get.return_value = None
        stream = _BaseStream(session=mock_session, stream_id=1)

        assert "state=closed" in repr(stream)

    def test_state_closed_when_no_state(self, mock_session: MagicMock) -> None:
        mock_session._connection._engine._state.streams.get.return_value = None
        stream = _BaseStream(session=mock_session, stream_id=1)

        assert stream.state == StreamState.CLOSED


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
            close_code=None,
            close_reason=None,
            closed_at=None,
        )

        assert diagnostics.stream_id == 1
        assert diagnostics.state == StreamState.OPEN


@pytest.mark.asyncio
class TestWebTransportReceiveStream:

    @pytest.fixture
    def mock_loop(self, mocker: MockerFixture) -> MagicMock:
        loop = mocker.Mock(spec=asyncio.AbstractEventLoop)
        loop.create_future.side_effect = lambda: asyncio.Future()
        mocker.patch("asyncio.get_running_loop", return_value=loop)
        return cast(MagicMock, loop)

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        session._connection = mocker.Mock()
        session._connection.config.max_stream_read_buffer = 1024
        session._connection.config.read_timeout = 0.01
        session._connection._engine = mocker.Mock()
        session._connection._engine._state.streams = {}
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
        mocker.patch.object(stream, "read", side_effect=StreamError("Fail", stream_id=1))

        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    async def test_aiter_handles_unexpected_error(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(stream, "read", side_effect=ValueError("Unexpected"))

        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    async def test_can_read(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        state_data = MagicMock(spec=StreamStateData)
        state_data.state = StreamState.OPEN
        mock_session._connection._engine._state.streams[1] = state_data

        assert stream.can_read

    async def test_can_read_false_if_closed(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        state_data = MagicMock(spec=StreamStateData)
        state_data.state = StreamState.CLOSED
        mock_session._connection._engine._state.streams[1] = state_data

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

    async def test_diagnostics(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock, mock_loop: MagicMock
    ) -> None:
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

    async def test_direction(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        state_data = MagicMock(spec=StreamStateData)
        state_data.direction = StreamDirection.BIDIRECTIONAL
        mock_session._connection._engine._state.streams[1] = state_data

        assert stream.direction == StreamDirection.BIDIRECTIONAL

    async def test_direction_default(self, stream: WebTransportReceiveStream) -> None:
        assert stream.direction == StreamDirection.RECEIVE_ONLY

    async def test_find_in_buffer_seam_not_found(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"aaa")
        stream._read_buffer.append(b"bbb")
        stream._read_buffer_size = 6

        idx = stream._find_in_buffer(b"ab")
        assert idx == 2

        idx_fail = stream._find_in_buffer(b"ac")
        assert idx_fail == -1

    async def test_find_in_buffer_skip_logic(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"skip_me")
        stream._read_buffer.append(b"123_find")
        stream._read_buffer_size = 15

        idx = stream._find_in_buffer(b"find", start=8)
        assert idx == 11

    async def test_find_in_buffer_small_chunks_large_sep(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"a")
        stream._read_buffer.append(b"b")
        stream._read_buffer.append(b"c")
        stream._read_buffer.append(b"d")
        stream._read_buffer_size = 4

        idx = stream._find_in_buffer(b"bc")
        assert idx == 1

    async def test_read_all(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "read", side_effect=[b"a", b"b", b""])

        data = await stream.read_all()

        assert data == b"ab"

    async def test_read_all_handles_internal_buffer_exception(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        stream._read_buffer_size = 5
        mocker.patch.object(stream, "_consume_buffer", side_effect=StreamError("Corrupt", stream_id=1))

        data = await stream.read_all()

        assert data == b""

    async def test_read_all_with_error(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "read", side_effect=[b"a", StreamError("Fail", stream_id=1)])

        data = await stream.read_all()

        assert data == b"a"

    async def test_read_from_buffer_all(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"hello")
        stream._read_buffer.append(b"world")
        stream._read_buffer_size = 10

        data_partial = await stream.read(max_bytes=5)
        data_all = await stream.read(max_bytes=-1)

        assert data_partial == b"hello"
        assert data_all == b"world"
        assert len(stream._read_buffer) == 0
        assert stream._read_buffer_size == 0

    async def test_read_from_engine(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock, mock_loop: MagicMock
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserStreamRead)
            event.future.set_result(b"engine_data")

        mock_session._send_event_to_engine.side_effect = engine_behavior

        data = await stream.read(max_bytes=100)

        assert data == b"engine_data"
        mock_session._send_event_to_engine.assert_awaited_once()
        event = mock_session._send_event_to_engine.await_args[1]["event"]
        assert event.max_bytes == 100

    async def test_read_from_engine_timeout(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_session._send_event_to_engine.side_effect = None

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="read operation timed out"):
            await stream.read()

    async def test_read_from_engine_wait_for_exception(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
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
            await stream.read()

    async def test_read_sets_eof_and_returns_empty(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock, mock_loop: MagicMock
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result(b"")

        mock_session._send_event_to_engine.side_effect = engine_behavior

        data1 = await stream.read()
        assert data1 == b""
        assert stream._read_eof is True

        data2 = await stream.read()
        assert data2 == b""

    async def test_readexactly_buffer_limit_exceeded(self, stream: WebTransportReceiveStream) -> None:
        with pytest.raises(StreamError, match="Read request .* exceeds max read buffer"):
            await stream.readexactly(n=2000)

    async def test_readexactly_eof_from_engine(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        mocker.patch.object(stream, "_read_from_engine", return_value=b"")

        with pytest.raises(asyncio.IncompleteReadError):
            await stream.readexactly(n=5)

    async def test_readexactly_eof_in_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"short")
        stream._read_buffer_size = 5
        stream._read_eof = True

        with pytest.raises(asyncio.IncompleteReadError):
            await stream.readexactly(n=10)

    async def test_readexactly_from_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"helloworld")
        stream._read_buffer_size = 10

        data = await stream.readexactly(n=5)

        assert data == b"hello"
        assert list(stream._read_buffer) == [b"world"]
        assert stream._read_buffer_size == 5

    async def test_readexactly_negative(self, stream: WebTransportReceiveStream) -> None:
        with pytest.raises(ValueError, match="n must be a non-negative integer"):
            await stream.readexactly(n=-1)

    async def test_readexactly_pulls_from_engine(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(stream, "_read_from_engine", side_effect=[b"he", b"llo"])

        data = await stream.readexactly(n=5)

        assert data == b"hello"

    async def test_readexactly_raises_if_engine_chunk_overflows_buffer(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture, mock_session: MagicMock
    ) -> None:
        mock_session._connection.config.max_stream_read_buffer = 10
        mocker.patch.object(stream, "_read_from_engine", return_value=b"overflowing_chunk")

        with pytest.raises(StreamError, match="Read buffer limit"):
            await stream.readexactly(n=10)

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
        mock_session._connection.config.max_stream_read_buffer = 5
        stream._read_buffer.append(b"123")
        stream._read_buffer_size = 3
        mocker.patch.object(stream, "_read_from_engine", return_value=b"456")

        with pytest.raises(StreamError, match="Read buffer limit .* exceeded"):
            await stream.readuntil(separator=b"\n")

    async def test_readuntil_found_after_pull(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        stream._read_buffer.append(b"one")
        stream._read_buffer_size = 3
        mocker.patch.object(stream, "_read_from_engine", return_value=b"\ntwo")

        data = await stream.readuntil(separator=b"\n")

        assert data == b"one\n"
        assert list(stream._read_buffer) == [b"two"]
        assert stream._read_buffer_size == 3

    async def test_readuntil_found_in_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"one\ntwo")
        stream._read_buffer_size = 7

        data = await stream.readuntil(separator=b"\n")

        assert data == b"one\n"
        assert list(stream._read_buffer) == [b"two"]
        assert stream._read_buffer_size == 3

    async def test_readuntil_limit_exceeded_in_buffer(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"long line\n")
        stream._read_buffer_size = 10

        with pytest.raises(StreamError, match="line over limit"):
            await stream.readuntil(separator=b"\n", limit=5)

    async def test_readuntil_optim_offset(self, stream: WebTransportReceiveStream, mocker: MockerFixture) -> None:
        """Test that offset optimization works when triggering a new read."""
        stream._read_buffer.append(b"abc")
        stream._read_buffer_size = 3
        mocker.patch.object(stream, "_read_from_engine", return_value=b"defz")

        data = await stream.readuntil(separator=b"z")

        assert data == b"abcdefz"

    async def test_readuntil_raises_on_empty_separator(self, stream: WebTransportReceiveStream) -> None:
        with pytest.raises(ValueError):
            await stream.readuntil(separator=b"")

    async def test_readuntil_returns_buffer_at_eof(
        self, stream: WebTransportReceiveStream, mocker: MockerFixture
    ) -> None:
        stream._read_buffer.append(b"partial")
        stream._read_buffer_size = 7
        mocker.patch.object(stream, "_read_from_engine", return_value=b"")

        with pytest.raises(asyncio.IncompleteReadError) as exc_info:
            await stream.readuntil(separator=b"\n")

        assert exc_info.value.partial == b"partial"
        assert len(stream._read_buffer) == 0
        assert stream._read_buffer_size == 0
        assert stream._read_eof is True

    async def test_readuntil_separator_not_found_within_limit(self, stream: WebTransportReceiveStream) -> None:
        stream._read_buffer.append(b"123456")
        stream._read_buffer_size = 6

        with pytest.raises(StreamError, match="separator not found within limit"):
            await stream.readuntil(separator=b"\n", limit=5)

    async def test_repr(self, stream: WebTransportReceiveStream, mock_session: MagicMock) -> None:
        state_data = MagicMock(spec=StreamStateData)
        state_data.state = StreamState.OPEN
        mock_session._connection._engine._state.streams[1] = state_data

        assert "state=" in repr(stream)

    async def test_stop_receiving(
        self, stream: WebTransportReceiveStream, mock_session: MagicMock, mock_loop: MagicMock
    ) -> None:
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
    def mock_loop(self, mocker: MockerFixture) -> MagicMock:
        loop = mocker.Mock(spec=asyncio.AbstractEventLoop)
        loop.create_future.side_effect = lambda: asyncio.Future()
        mocker.patch("asyncio.get_running_loop", return_value=loop)
        return cast(MagicMock, loop)

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        session._connection = mocker.Mock()
        session._connection.config.write_timeout = 0.01
        session._connection._engine = mocker.Mock()
        session._connection._engine._state.streams = {}
        session._send_event_to_engine = mocker.AsyncMock()
        return cast(MagicMock, session)

    @pytest.fixture
    def stream(self, mock_session: MagicMock) -> WebTransportSendStream:
        return WebTransportSendStream(session=mock_session, stream_id=2)

    async def test_can_write(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        state_data = MagicMock(spec=StreamStateData)
        state_data.state = StreamState.OPEN
        mock_session._connection._engine._state.streams[2] = state_data

        assert stream.can_write

    async def test_can_write_false_if_reset(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        state_data = MagicMock(spec=StreamStateData)
        state_data.state = StreamState.RESET_SENT
        mock_session._connection._engine._state.streams[2] = state_data

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

    async def test_context_manager_generic_exception(
        self, stream: WebTransportSendStream, mocker: MockerFixture
    ) -> None:
        spy_close = mocker.patch.object(stream, "close", new_callable=mocker.AsyncMock)

        with pytest.raises(RuntimeError):
            async with stream:
                raise RuntimeError("Generic failure")

        spy_close.assert_awaited_once_with(error_code=ErrorCodes.APPLICATION_ERROR)

    async def test_direction(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        state_data = MagicMock(spec=StreamStateData)
        state_data.direction = StreamDirection.BIDIRECTIONAL
        mock_session._connection._engine._state.streams[2] = state_data

        assert stream.direction == StreamDirection.BIDIRECTIONAL

    async def test_direction_default(self, stream: WebTransportSendStream) -> None:
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

    async def test_write(self, stream: WebTransportSendStream, mock_session: MagicMock, mock_loop: MagicMock) -> None:
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

    async def test_write_empty_no_fin(self, stream: WebTransportSendStream, mock_session: MagicMock) -> None:
        """Test write with empty data and no FIN returns early."""
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

    async def test_write_timeout(
        self, stream: WebTransportSendStream, mock_session: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_session._send_event_to_engine.side_effect = None

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="write operation timed out"):
            await stream.write(data=b"data")


@pytest.mark.asyncio
class TestWebTransportStream:

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> MagicMock:
        session = mocker.Mock(spec=WebTransportSession)
        session._connection = mocker.Mock()
        session._connection._engine._state.streams = {}
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
