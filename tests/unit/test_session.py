"""Unit tests for the pywebtransport.session.session module."""

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ConnectionError,
    SessionError,
    StreamError,
    TimeoutError,
    WebTransportSendStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport._protocol.events import (
    UserCloseSession,
    UserCreateStream,
    UserGetSessionDiagnostics,
    UserGrantDataCredit,
    UserGrantStreamsCredit,
    UserSendDatagram,
)
from pywebtransport.connection import WebTransportConnection
from pywebtransport.session import SessionDiagnostics
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
            active_streams=[],
            blocked_streams=[],
            close_code=None,
            close_reason=None,
            closed_at=None,
            ready_at=101.0,
        )

        assert diag.session_id == "sess-1"
        assert diag.state == SessionState.CONNECTED


class TestWebTransportSession:

    @pytest.fixture
    def mock_connection(self, mocker: MockerFixture) -> MagicMock:
        conn = mocker.Mock(spec=WebTransportConnection)
        conn.config = mocker.Mock()
        conn.config.stream_creation_timeout = 0.1
        conn.config.max_event_queue_size = 100
        conn.config.max_event_listeners = 100
        conn.config.max_event_history_size = 100
        conn._stream_handles = {}
        conn._engine = mocker.Mock()
        conn._engine._state = mocker.Mock()
        conn._engine._state.sessions = mocker.Mock()
        conn._send_event_to_engine = mocker.AsyncMock()
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_close_already_closed(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        session._cached_state = SessionState.CLOSED

        await session.close()

        mock_connection._send_event_to_engine.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_handles_engine_error(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_exception(SessionError("Already closed"))

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.close()

        mock_connection._send_event_to_engine.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_no_connection(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(session, "_connection", return_value=None)

        await session.close()

        mock_connection._send_event_to_engine.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_manager(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(session, "close", new_callable=mocker.AsyncMock)

        async with session as s:
            assert s is session

        spy_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_stream_engine_error(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_exception(ValueError("Engine rejected stream"))

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        with pytest.raises(ValueError, match="Engine rejected stream"):
            await session.create_bidirectional_stream()

    @pytest.mark.asyncio
    async def test_create_stream_generic_exception_cancels_future(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_connection._send_event_to_engine.side_effect = None
        mock_fut = mocker.Mock(spec=asyncio.Future)
        mock_fut.done.return_value = False
        mock_loop = mocker.Mock()
        mock_loop.create_future.return_value = mock_fut
        mocker.patch("asyncio.get_running_loop", return_value=mock_loop)

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

        mock_fut.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_stream_internal_error_no_handle(
        self, session: WebTransportSession, mock_connection: MagicMock
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result(999)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        with pytest.raises(StreamError, match="Internal error creating stream handle"):
            await session.create_bidirectional_stream()

    @pytest.mark.parametrize(
        "method_name, is_unidirectional, stream_class, expected_result_id",
        [
            ("create_bidirectional_stream", False, WebTransportStream, 101),
            ("create_unidirectional_stream", True, WebTransportSendStream, 202),
        ],
    )
    @pytest.mark.asyncio
    async def test_create_stream_success(
        self,
        session: WebTransportSession,
        mock_connection: MagicMock,
        mocker: MockerFixture,
        method_name: str,
        is_unidirectional: bool,
        stream_class: Any,
        expected_result_id: int,
    ) -> None:
        stream_handle = mocker.Mock(spec=stream_class)
        mock_connection._stream_handles = {expected_result_id: stream_handle}

        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserCreateStream)
            assert event.is_unidirectional == is_unidirectional
            event.future.set_result(expected_result_id)

        mock_connection._send_event_to_engine.side_effect = engine_behavior
        create_method = getattr(session, method_name)

        stream = await create_method()

        assert stream is stream_handle
        mock_connection._send_event_to_engine.assert_awaited_once()

    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    @pytest.mark.asyncio
    async def test_create_stream_timeout(
        self, session: WebTransportSession, mock_connection: MagicMock, mocker: MockerFixture, method_name: str
    ) -> None:
        mock_connection._send_event_to_engine.side_effect = None
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
        create_method = getattr(session, method_name)

        with pytest.raises(TimeoutError, match="timed out creating stream"):
            await create_method()

        mock_fut.cancel.assert_called_once()

    @pytest.mark.parametrize(
        "method_name, wrong_type_class, expected_error_msg",
        [
            ("create_bidirectional_stream", WebTransportSendStream, "Expected bidirectional stream"),
            ("create_unidirectional_stream", WebTransportStream, "Expected unidirectional send stream"),
        ],
    )
    @pytest.mark.asyncio
    async def test_create_stream_wrong_type(
        self,
        session: WebTransportSession,
        mock_connection: MagicMock,
        mocker: MockerFixture,
        method_name: str,
        wrong_type_class: Any,
        expected_error_msg: str,
    ) -> None:
        wrong_handle = mocker.Mock(spec=wrong_type_class)
        mock_connection._stream_handles = {303: wrong_handle}

        async def engine_behavior(event: Any) -> None:
            event.future.set_result(303)

        mock_connection._send_event_to_engine.side_effect = engine_behavior
        create_method = getattr(session, method_name)

        with pytest.raises(StreamError, match=expected_error_msg):
            await create_method()

    @pytest.mark.asyncio
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
                    "active_streams": [],
                    "blocked_streams": [],
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

    @pytest.mark.asyncio
    async def test_diagnostics_connection_error(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        mock_connection._send_event_to_engine.side_effect = ConnectionError("Closed")

        with pytest.raises(SessionError, match="Connection is closed"):
            await session.diagnostics()

    @pytest.mark.asyncio
    async def test_grant_data_credit(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserGrantDataCredit)
            event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.grant_data_credit(max_data=1024)

        mock_connection._send_event_to_engine.assert_awaited_once()
        event = mock_connection._send_event_to_engine.await_args[1]["event"]
        assert event.max_data == 1024

    @pytest.mark.asyncio
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

    def test_headers_property(self, session: WebTransportSession) -> None:
        assert session.headers == {"User-Agent": "TestClient"}

        headers_copy = session.headers
        if isinstance(headers_copy, dict):
            headers_copy["New"] = "Value"

        assert session.headers == {"User-Agent": "TestClient"}

    def test_internal_add_stream_handle(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        stream = mocker.Mock(stream_id=10)
        event_data = {"extra": "info"}

        mock_emit = mocker.patch.object(session.events, "emit_nowait")

        session._add_stream_handle(stream=stream, event_data=event_data)

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[1]
        assert call_args["event_type"] == EventType.STREAM_OPENED
        assert call_args["data"]["stream"] is stream
        assert call_args["data"]["extra"] == "info"

    def test_is_closed_false_when_connected(self, session: WebTransportSession) -> None:
        session._cached_state = SessionState.CONNECTED
        assert session.is_closed is False

    def test_is_closed_true_when_closed(self, session: WebTransportSession) -> None:
        session._cached_state = SessionState.CLOSED
        assert session.is_closed is True

    def test_on_session_closed(self, session: WebTransportSession) -> None:
        session._cached_state = SessionState.CONNECTED
        session._on_session_closed(event=MagicMock())
        assert session.state == SessionState.CLOSED

    def test_on_session_ready(self, session: WebTransportSession) -> None:
        session._cached_state = SessionState.CONNECTING
        session._on_session_ready(event=MagicMock())
        assert session.state == SessionState.CONNECTED

    @pytest.mark.asyncio
    async def test_operation_no_connection(self, session: WebTransportSession, mocker: MockerFixture) -> None:
        mocker.patch.object(session, "_connection", return_value=None)

        with pytest.raises(ConnectionError, match="Connection is gone"):
            await session.grant_data_credit(max_data=100)

    def test_path_property(self, session: WebTransportSession) -> None:
        assert session.path == "/chat"

    def test_repr(self, session: WebTransportSession) -> None:
        session._cached_state = SessionState.CONNECTED
        assert "id=sess-1" in repr(session)
        assert "state=connected" in repr(session)

    @pytest.mark.asyncio
    async def test_send_datagram(self, session: WebTransportSession, mock_connection: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserSendDatagram)
            event.future.set_result(None)

        mock_connection._send_event_to_engine.side_effect = engine_behavior

        await session.send_datagram(data=b"payload")

        mock_connection._send_event_to_engine.assert_awaited_once()
        event = mock_connection._send_event_to_engine.await_args[1]["event"]
        assert event.data == b"payload"

    @pytest.mark.asyncio
    async def test_send_event_to_engine_connection_gone_future_done(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(session, "_connection", return_value=None)
        mock_future = mocker.Mock(spec=asyncio.Future)
        mock_future.done.return_value = True
        event = UserSendDatagram(session_id=session.session_id, data=b"test", future=mock_future)

        await session._send_event_to_engine(event=event)

        mock_future.set_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_event_to_engine_race_condition(
        self, session: WebTransportSession, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(session, "_connection", return_value=None)
        mock_future = mocker.Mock(spec=asyncio.Future)
        mock_future.done.return_value = False
        mock_future.set_exception.side_effect = asyncio.InvalidStateError()
        event = UserSendDatagram(session_id=session.session_id, data=b"test", future=mock_future)

        await session._send_event_to_engine(event=event)

        mock_future.set_exception.assert_called_once()
        args = mock_future.set_exception.call_args[0]
        assert isinstance(args[0], ConnectionError)

    def test_session_id_property(self, session: WebTransportSession) -> None:
        assert session.session_id == "sess-1"
