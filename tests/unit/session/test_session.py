"""Unit tests for the pywebtransport.session.session module."""

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport._protocol.events import (
    UserCloseSession,
    UserCreateStream,
    UserGetSessionDiagnostics,
    UserGrantDataCredit,
    UserGrantStreamsCredit,
    UserSendDatagram,
)
from pywebtransport._protocol.state import SessionStateData
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.exceptions import ConnectionError, SessionError, StreamError, TimeoutError
from pywebtransport.session.session import SessionDiagnostics, WebTransportSession
from pywebtransport.stream.stream import WebTransportSendStream, WebTransportStream
from pywebtransport.types import EventType, SessionState


class TestSessionDiagnostics:

    def test_init(self) -> None:
        diag = SessionDiagnostics(
            session_id="sess-1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            headers={"Host": "example.com"},
            created_at=100.0,
            local_max_data=1000,
            local_data_sent=50,
            peer_max_data=2000,
            peer_data_sent=100,
            local_max_streams_bidi=10,
            local_streams_bidi_opened=1,
            peer_max_streams_bidi=10,
            peer_streams_bidi_opened=2,
            local_max_streams_uni=5,
            local_streams_uni_opened=0,
            peer_max_streams_uni=5,
            peer_streams_uni_opened=0,
            pending_bidi_stream_futures=[],
            pending_uni_stream_futures=[],
            datagrams_sent=5,
            datagram_bytes_sent=500,
            datagrams_received=3,
            datagram_bytes_received=300,
            close_code=None,
            close_reason=None,
            closed_at=None,
            ready_at=101.0,
        )

        assert diag.session_id == "sess-1"
        assert diag.state == SessionState.CONNECTED


class TestWebTransportSessionSync:

    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture) -> MagicMock:
        conn = mocker.Mock(spec=WebTransportConnection)
        conn._engine = mocker.Mock()
        conn._engine._state = mocker.Mock()
        conn._engine._state.sessions = mocker.Mock()
        return cast(MagicMock, conn)

    @pytest.fixture
    def session(self, mock_connection: MagicMock) -> WebTransportSession:
        return WebTransportSession(
            connection=mock_connection,
            session_id="sess-1",
            path="/chat",
            headers={"User-Agent": "TestClient"},
            control_stream_id=0,
        )

    def test_headers_property(self, session: WebTransportSession) -> None:
        headers = session.headers
        assert headers == {"User-Agent": "TestClient"}
        headers["New"] = "Value"
        assert session.headers == {"User-Agent": "TestClient"}

    def test_internal_add_stream_handle(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        stream = mocker.Mock(stream_id=10)
        event_data = {"extra": "info"}
        spy_emit = mocker.spy(session.events, "emit_nowait")

        session._add_stream_handle(stream=stream, event_data=event_data)

        spy_emit.assert_called_once()
        call_args = spy_emit.call_args[1]
        assert call_args["event_type"] == EventType.STREAM_OPENED
        assert call_args["data"]["stream"] is stream
        assert call_args["data"]["extra"] == "info"

    def test_is_closed_false_when_connected(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        state_data = MagicMock(spec=SessionStateData)
        state_data.state = SessionState.CONNECTED
        mock_connection._engine._state.sessions.get.return_value = state_data
        assert session.is_closed is False

    def test_is_closed_true_when_closed(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        state_data = MagicMock(spec=SessionStateData)
        state_data.state = SessionState.CLOSED
        mock_connection._engine._state.sessions.get.return_value = state_data
        assert session.is_closed is True

    def test_is_closed_true_when_no_state(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        mock_connection._engine._state.sessions.get.return_value = None
        assert session.is_closed is True

    def test_path_property(self, session: WebTransportSession) -> None:
        assert session.path == "/chat"

    def test_repr(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        state_data = MagicMock(spec=SessionStateData)
        state_data.state = SessionState.CONNECTED
        mock_connection._engine._state.sessions.get.return_value = state_data

        assert "id=sess-1" in repr(session)
        assert "state=connected" in repr(session)

    def test_session_id_property(self, session: WebTransportSession) -> None:
        assert session.session_id == "sess-1"

    def test_state_handling_no_connection(self, mock_connection: MagicMock) -> None:
        session = WebTransportSession(
            connection=cast(WebTransportConnection, None), session_id="s1", path="/", headers={}, control_stream_id=None
        )
        assert session.state == SessionState.CLOSED
        assert session.is_closed is True

    def test_state_handling_no_engine(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        del mock_connection._engine
        assert session.state == SessionState.CLOSED

    def test_state_handling_no_state_object(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        del mock_connection._engine._state
        assert session.state == SessionState.CLOSED


@pytest.mark.asyncio
class TestWebTransportSessionAsync:

    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture) -> MagicMock:
        conn = mocker.Mock(spec=WebTransportConnection)
        conn.config = mocker.Mock()
        conn.config.stream_creation_timeout = 0.1
        conn._stream_handles = {}
        conn._engine = mocker.Mock()
        conn._engine._state = mocker.Mock()
        conn._engine._state.sessions = mocker.Mock()
        conn._send_event_to_engine = mocker.AsyncMock()
        conn.close = mocker.AsyncMock()
        return cast(MagicMock, conn)

    @pytest.fixture
    def mock_loop(self, mocker: MockerFixture) -> MagicMock:
        loop = mocker.Mock(spec=asyncio.AbstractEventLoop)
        loop.create_future.side_effect = lambda: asyncio.Future()
        mocker.patch("asyncio.get_running_loop", return_value=loop)
        return cast(MagicMock, loop)

    @pytest.fixture
    def session(self, mock_connection: MagicMock) -> WebTransportSession:
        return WebTransportSession(
            connection=mock_connection,
            session_id="sess-1",
            path="/chat",
            headers={"User-Agent": "TestClient"},
            control_stream_id=0,
        )

    async def test_close(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserCloseSession)
            event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.close(error_code=100, reason="Done")

        mock_connection._send_event_to_engine.assert_awaited_once()
        event = mock_connection._send_event_to_engine.await_args[1]["event"]
        assert isinstance(event, UserCloseSession)
        assert event.session_id == "sess-1"
        assert event.error_code == 100
        assert event.reason == "Done"
        mock_connection.close.assert_not_awaited()

    async def test_close_handles_engine_error(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_exception(SessionError("Already closed"))

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.close()

        mock_connection._send_event_to_engine.assert_awaited_once()

    async def test_close_with_connection(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.close(close_connection=True)

        mock_connection.close.assert_awaited_once()

    async def test_context_manager(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)

        async with session as s:
            assert s is session

        spy_close.assert_awaited_once()

    async def test_create_bidirectional_stream(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportStream)
        mock_connection._stream_handles = {101: stream_handle}

        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserCreateStream)
            assert not event.is_unidirectional
            event.future.set_result(101)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        stream = await session.create_bidirectional_stream()

        assert stream is stream_handle
        mock_connection._send_event_to_engine.assert_awaited_once()

    async def test_create_bidirectional_stream_generic_exception(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_connection._send_event_to_engine.side_effect = None

        class MockTimeoutGeneric:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise ValueError("Generic Error")

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeoutGeneric)

        with pytest.raises(ValueError, match="Generic Error"):
            await session.create_bidirectional_stream()

    async def test_create_bidirectional_stream_internal_error(
        self, session: WebTransportSession, mock_connection: MagicMock
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result(999)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        with pytest.raises(StreamError, match="Internal error creating stream handle"):
            await session.create_bidirectional_stream()

    async def test_create_bidirectional_stream_timeout(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_connection._send_event_to_engine.side_effect = None

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="timed out creating bidirectional stream"):
            await session.create_bidirectional_stream()

    async def test_create_bidirectional_stream_wrong_type(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        wrong_handle = mocker.Mock(spec=WebTransportSendStream)
        mock_connection._stream_handles = {101: wrong_handle}

        async def engine_behavior(event: Any) -> None:
            event.future.set_result(101)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        with pytest.raises(StreamError, match="Internal error creating stream handle"):
            await session.create_bidirectional_stream()

    async def test_create_unidirectional_stream(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportSendStream)
        mock_connection._stream_handles = {202: stream_handle}

        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserCreateStream)
            assert event.is_unidirectional
            event.future.set_result(202)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        stream = await session.create_unidirectional_stream()

        assert stream is stream_handle
        mock_connection._send_event_to_engine.assert_awaited_once()

    async def test_create_unidirectional_stream_generic_exception(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_connection._send_event_to_engine.side_effect = None

        class MockTimeoutGeneric:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise ValueError("Generic Error")

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeoutGeneric)

        with pytest.raises(ValueError, match="Generic Error"):
            await session.create_unidirectional_stream()

    async def test_create_unidirectional_stream_internal_error(
        self, session: WebTransportSession, mock_connection: MagicMock
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result(888)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        with pytest.raises(StreamError, match="Internal error creating stream handle"):
            await session.create_unidirectional_stream()

    async def test_create_unidirectional_stream_timeout(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_connection._send_event_to_engine.side_effect = None

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        with pytest.raises(TimeoutError, match="timed out creating unidirectional stream"):
            await session.create_unidirectional_stream()

    async def test_create_unidirectional_stream_wrong_type(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        wrong_handle = mocker.Mock(spec=WebTransportStream)
        mock_connection._stream_handles = {202: wrong_handle}

        async def engine_behavior(event: Any) -> None:
            event.future.set_result(202)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        with pytest.raises(StreamError, match="Internal error creating stream handle"):
            await session.create_unidirectional_stream()

    async def test_diagnostics(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserGetSessionDiagnostics)
            event.future.set_result(
                {
                    "session_id": "sess-1",
                    "control_stream_id": 0,
                    "state": SessionState.CONNECTED,
                    "path": "/",
                    "headers": {},
                    "created_at": 0.0,
                    "local_max_data": 0,
                    "local_data_sent": 0,
                    "peer_max_data": 0,
                    "peer_data_sent": 0,
                    "local_max_streams_bidi": 0,
                    "local_streams_bidi_opened": 0,
                    "peer_max_streams_bidi": 0,
                    "peer_streams_bidi_opened": 0,
                    "local_max_streams_uni": 0,
                    "local_streams_uni_opened": 0,
                    "peer_max_streams_uni": 0,
                    "peer_streams_uni_opened": 0,
                    "pending_bidi_stream_futures": [],
                    "pending_uni_stream_futures": [],
                    "datagrams_sent": 0,
                    "datagram_bytes_sent": 0,
                    "datagrams_received": 0,
                    "datagram_bytes_received": 0,
                    "close_code": None,
                    "close_reason": None,
                    "closed_at": None,
                    "ready_at": None,
                }
            )

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        diag = await session.diagnostics()

        mock_connection._send_event_to_engine.assert_awaited_once()
        assert diag.session_id == "sess-1"
        assert diag.state == SessionState.CONNECTED

    async def test_diagnostics_connection_error(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        mock_connection._send_event_to_engine.side_effect = ConnectionError("Closed")

        with pytest.raises(SessionError, match="Connection is closed"):
            await session.diagnostics()

    async def test_grant_data_credit(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserGrantDataCredit)
            event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.grant_data_credit(max_data=1024)

        mock_connection._send_event_to_engine.assert_awaited_once()
        event = mock_connection._send_event_to_engine.await_args[1]["event"]
        assert event.max_data == 1024

    async def test_grant_streams_credit(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserGrantStreamsCredit)
            event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.grant_streams_credit(max_streams=5, is_unidirectional=True)

        mock_connection._send_event_to_engine.assert_awaited_once()
        event = mock_connection._send_event_to_engine.await_args[1]["event"]
        assert event.max_streams == 5
        assert event.is_unidirectional is True

    async def test_send_datagram(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserSendDatagram)
            event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.send_datagram(data=b"payload")

        mock_connection._send_event_to_engine.assert_awaited_once()
        event = mock_connection._send_event_to_engine.await_args[1]["event"]
        assert event.data == b"payload"
