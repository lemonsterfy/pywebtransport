"""Unit tests for the pywebtransport.connection.connection module."""

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport._protocol.events import (
    ConnectionClose,
    Effect,
    EmitConnectionEvent,
    EmitSessionEvent,
    EmitStreamEvent,
    UserConnectionGracefulClose,
    UserCreateSession,
    UserGetConnectionDiagnostics,
)
from pywebtransport._protocol.state import ProtocolState, StreamStateData
from pywebtransport.client._adapter import WebTransportClientProtocol
from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import ConnectionDiagnostics, WebTransportConnection
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import ConnectionError, SessionError
from pywebtransport.session.session import WebTransportSession
from pywebtransport.stream.stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.types import ConnectionState, EventType, StreamDirection


class TestConnectionDiagnostics:

    def test_init(self) -> None:
        diag = ConnectionDiagnostics(
            connection_id="uuid-123",
            state=ConnectionState.CONNECTED,
            is_client=True,
            connected_at=100.0,
            closed_at=None,
            max_datagram_size=1200,
            remote_max_datagram_frame_size=1200,
            session_count=1,
            stream_count=2,
            active_session_handles=1,
            active_stream_handles=2,
        )

        assert diag.connection_id == "uuid-123"
        assert diag.state == ConnectionState.CONNECTED


class TestWebTransportConnection:

    @pytest.fixture
    def connection(
        self,
        mock_config: MagicMock,
        mock_protocol: MagicMock,
        mock_transport: MagicMock,
        mock_engine: MagicMock,
        mocker: MockerFixture,
    ) -> WebTransportConnection:
        mocker.patch("pywebtransport.connection.connection.WebTransportEngine", return_value=mock_engine)
        conn = WebTransportConnection(
            config=mock_config, protocol=mock_protocol, transport=mock_transport, is_client=True
        )
        return conn

    @pytest.fixture
    def mock_config(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.Mock(spec=ClientConfig))

    @pytest.fixture
    def mock_engine(self, mocker: MockerFixture) -> MagicMock:
        engine = mocker.Mock()
        engine._state = mocker.Mock(spec=ProtocolState)
        engine._state.connection_state = ConnectionState.IDLE
        engine._state.sessions = mocker.Mock()
        engine._state.streams = mocker.Mock()
        engine._driver_task = None
        engine._event_queue = mocker.Mock()
        engine.put_event = mocker.AsyncMock()
        engine.start_driver_loop = mocker.Mock()
        engine.stop_driver_loop = mocker.AsyncMock()
        return cast(MagicMock, engine)

    @pytest.fixture
    def mock_loop(self, mocker: MockerFixture) -> MagicMock:
        loop = mocker.Mock(spec=asyncio.AbstractEventLoop)
        loop.create_future.side_effect = lambda: asyncio.Future()
        loop.create_task.side_effect = lambda coro: asyncio.create_task(coro=coro)
        mocker.patch("asyncio.get_running_loop", return_value=loop)
        return cast(MagicMock, loop)

    @pytest.fixture
    def mock_protocol(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.Mock(spec=WebTransportClientProtocol))

    @pytest.fixture
    def mock_transport(self, mocker: MockerFixture) -> MagicMock:
        transport = mocker.Mock(spec=asyncio.DatagramTransport)
        transport.is_closing.return_value = False
        return cast(MagicMock, transport)

    @pytest.mark.asyncio
    async def test_close_forceful_sends_event(self, connection: WebTransportConnection, mock_engine: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, ConnectionClose)
            assert event.error_code == ErrorCodes.NO_ERROR
            event.future.set_result(None)

        mock_engine.put_event.side_effect = engine_behavior

        await connection.close()

        mock_engine.put_event.assert_awaited_once()
        mock_engine.stop_driver_loop.assert_awaited_once()
        assert cast(MagicMock, connection._transport.close).called
        assert mock_engine._state.connection_state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_close_no_engine(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        del connection._engine
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        spy_close_transport = mocker.spy(connection._transport, "close")

        await connection.close()

        spy_logger.info.assert_any_call("Closing connection %s...", mocker.ANY)
        spy_close_transport.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_server_side_does_not_close_transport(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture
    ) -> None:
        connection._is_client = False
        spy_close_transport = mocker.spy(connection._transport, "close")

        async def engine_behavior(event: Any) -> None:
            event.future.set_result(None)

        mock_engine.put_event.side_effect = engine_behavior

        await connection.close()

        spy_close_transport.assert_not_called()
        mock_engine.stop_driver_loop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_timeout_ignored(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture, mock_loop: MagicMock
    ) -> None:
        mock_engine.put_event.return_value = None
        fut: asyncio.Future[Any] = asyncio.Future()
        mock_loop.create_future.side_effect = None
        mock_loop.create_future.return_value = fut

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        await connection.close()

        mock_engine.put_event.assert_awaited()
        assert fut.cancelled()
        mock_engine.stop_driver_loop.assert_awaited_once()
        assert cast(MagicMock, connection._transport.close).called

    @pytest.mark.asyncio
    async def test_close_transport_already_closed(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        cast(MagicMock, connection._transport.is_closing).return_value = True
        spy_close = mocker.spy(connection._transport, "close")

        await connection.close()

        spy_close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_wait_for_completes(self, connection: WebTransportConnection, mock_engine: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result(None)

        mock_engine.put_event.side_effect = engine_behavior

        await connection.close()

        mock_engine.put_event.assert_awaited()
        mock_engine.stop_driver_loop.assert_awaited_once()
        assert cast(MagicMock, connection._transport.close).called

    @pytest.mark.asyncio
    async def test_context_manager(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        spy_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)

        async with connection as c:
            assert c is connection

        spy_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_session_client(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserCreateSession)
            session_mock = mocker.Mock(spec=WebTransportSession)
            connection._session_handles["sess-1"] = session_mock
            event.future.set_result("sess-1")

        mock_engine.put_event.side_effect = engine_behavior

        session = await connection.create_session(path="/")

        assert session is connection._session_handles["sess-1"]

    @pytest.mark.asyncio
    async def test_create_session_handles_missing_handle_error(
        self, connection: WebTransportConnection, mock_engine: MagicMock
    ) -> None:
        async def engine_behavior(event: Any) -> None:
            event.future.set_result("sess-1")

        mock_engine.put_event.side_effect = engine_behavior

        with pytest.raises(SessionError, match="Internal error creating session handle"):
            await connection.create_session(path="/")

    @pytest.mark.asyncio
    async def test_create_session_no_engine(self, connection: WebTransportConnection) -> None:
        del connection._engine
        with pytest.raises(ConnectionError, match="Engine not available"):
            await connection.create_session(path="/")

    @pytest.mark.asyncio
    async def test_create_session_server_error(self, connection: WebTransportConnection) -> None:
        connection._is_client = False

        with pytest.raises(ConnectionError, match="Sessions can only be created by the client"):
            await connection.create_session(path="/")

    @pytest.mark.asyncio
    async def test_diagnostics(self, connection: WebTransportConnection, mock_engine: MagicMock) -> None:
        async def engine_behavior(event: Any) -> None:
            assert isinstance(event, UserGetConnectionDiagnostics)
            event.future.set_result(
                {
                    "connection_id": "uuid",
                    "state": ConnectionState.CONNECTED,
                    "is_client": True,
                    "connected_at": 0.0,
                    "closed_at": None,
                    "max_datagram_size": 1000,
                    "remote_max_datagram_frame_size": 1000,
                    "session_count": 0,
                    "stream_count": 0,
                    "active_session_handles": 0,
                    "active_stream_handles": 0,
                }
            )

        mock_engine.put_event.side_effect = engine_behavior

        diag = await connection.diagnostics()

        assert diag.connection_id == "uuid"
        assert diag.active_session_handles == 0

    @pytest.mark.asyncio
    async def test_diagnostics_no_engine(self, connection: WebTransportConnection) -> None:
        del connection._engine

        with pytest.raises(ConnectionError, match="Engine not available"):
            await connection.diagnostics()

    def test_get_all_sessions(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        s1 = mocker.Mock(spec=WebTransportSession)
        s2 = mocker.Mock(spec=WebTransportSession)
        connection._session_handles = {"s1": s1, "s2": s2}

        assert connection.get_all_sessions() == [s1, s2]

    def test_get_engine_state_defaults(self, connection: WebTransportConnection) -> None:
        del connection._engine
        assert connection._get_engine_state() == ConnectionState.CLOSED

    def test_get_engine_state_missing_state_attr(self, connection: WebTransportConnection) -> None:
        del connection._engine._state
        assert connection._get_engine_state() == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_graceful_shutdown_generic_exception(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture
    ) -> None:
        class MockTimeoutGeneric:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise ValueError("Generic error")

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeoutGeneric)

        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        spy_close = mocker.spy(connection, "close")

        await connection.graceful_shutdown()

        spy_logger.warning.assert_called_with("Error during graceful shutdown: %s", mocker.ANY)
        spy_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_success(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture
    ) -> None:
        spy_close = mocker.spy(connection, "close")

        async def engine_behavior(event: Any) -> None:
            if isinstance(event, UserConnectionGracefulClose):
                event.future.set_result(None)
            elif isinstance(event, ConnectionClose):
                event.future.set_result(None)

        mock_engine.put_event.side_effect = engine_behavior

        await connection.graceful_shutdown()

        assert mock_engine.put_event.call_count == 2
        args_list = mock_engine.put_event.await_args_list
        assert isinstance(args_list[0].kwargs["event"], UserConnectionGracefulClose)
        spy_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_timeout(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture, mock_loop: MagicMock
    ) -> None:
        mock_engine.put_event.return_value = None
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        spy_close = mocker.spy(connection, "close")

        fut: asyncio.Future[Any] = asyncio.Future()
        mock_loop.create_future.side_effect = None
        mock_loop.create_future.return_value = fut

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        await connection.graceful_shutdown()

        spy_logger.warning.assert_called_with("Timeout waiting for graceful shutdown GOAWAY confirmation.")
        assert fut.cancelled()
        spy_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize(self, connection: WebTransportConnection, mock_engine: MagicMock) -> None:
        await connection.initialize()

        mock_engine.start_driver_loop.assert_called_once()
        cast(MagicMock, connection._protocol.set_engine_queue).assert_called_once_with(
            engine_queue=mock_engine._event_queue
        )

    @pytest.mark.asyncio
    async def test_initialize_already_running(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_engine._driver_task = mocker.Mock()
        spy_start = mocker.spy(mock_engine, "start_driver_loop")

        await connection.initialize()

        spy_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_engine_event_queue_missing(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_engine._event_queue = None
        spy_close = mocker.patch.object(connection, "close", new_callable=mocker.AsyncMock)
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")

        await connection.initialize()

        spy_logger.critical.assert_called_with(
            "Engine failed to create event queue during initialization for %s", mocker.ANY
        )
        spy_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_no_engine(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        del connection._engine
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")

        await connection.initialize()

        spy_logger.warning.assert_called_with("Attempted to initialize connection %s without an engine.", mocker.ANY)

    def test_notify_owner_connection_event(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        spy_emit = mocker.spy(connection.events, "emit_nowait")
        effect = EmitConnectionEvent(event_type=EventType.CONNECTION_ESTABLISHED, data={"info": "test"})

        connection._notify_owner(effect)

        spy_emit.assert_called_once()
        call_args = spy_emit.call_args[1]
        assert call_args["event_type"] == EventType.CONNECTION_ESTABLISHED
        assert call_args["data"]["connection"] is connection

    def test_notify_owner_connection_event_existing_key(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_emit = mocker.spy(connection.events, "emit_nowait")
        existing_conn = mocker.Mock()
        effect = EmitConnectionEvent(event_type=EventType.CONNECTION_ESTABLISHED, data={"connection": existing_conn})

        connection._notify_owner(effect)

        spy_emit.assert_called_once()
        call_args = spy_emit.call_args[1]
        assert call_args["data"]["connection"] is existing_conn

    def test_notify_owner_exception_handling(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        mocker.patch.object(connection.events, "emit_nowait", side_effect=ValueError("Boom"))
        effect = EmitConnectionEvent(event_type=EventType.CONNECTION_ESTABLISHED, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with("Error during owner notification callback: %s", mocker.ANY, exc_info=True)

    def test_notify_owner_session_closed_missing_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_create_task = mocker.patch("asyncio.create_task")
        effect = EmitSessionEvent(session_id="missing", event_type=EventType.SESSION_CLOSED, data={})

        connection._notify_owner(effect)

        mock_create_task.assert_not_called()

    def test_notify_owner_session_closed_removes_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        session_handle.events = mocker.Mock()
        session_handle.events.close.return_value = asyncio.sleep(delay=0)
        connection._session_handles["sess-1"] = session_handle
        mock_create_task = mocker.patch("asyncio.create_task")
        effect = EmitSessionEvent(session_id="sess-1", event_type=EventType.SESSION_CLOSED, data={})

        connection._notify_owner(effect)

        assert "sess-1" not in connection._session_handles
        mock_create_task.assert_called_once()
        coro = mock_create_task.call_args.kwargs["coro"]
        coro.close()

    def test_notify_owner_session_creation_missing_engine(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        del connection._engine
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitSessionEvent(session_id="s1", event_type=EventType.SESSION_READY, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with("Engine or state missing during session handle creation for %s.", "s1")

    def test_notify_owner_session_creation_missing_state_data(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        mock_engine._state.sessions.get.return_value = None
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitSessionEvent(session_id="s1", event_type=EventType.SESSION_READY, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with("Engine state for session %s missing during handle creation.", "s1")

    def test_notify_owner_session_event_blocked_warning(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        session_handle.events = mocker.Mock()
        session_handle.events.listener_count.return_value = 0
        connection._session_handles["sess-1"] = session_handle
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitSessionEvent(session_id="sess-1", event_type=EventType.SESSION_DATA_BLOCKED, data={})

        connection._notify_owner(effect)

        spy_logger.warning.assert_called_with(
            "Session %s received unhandled event '%s'.", "sess-1", EventType.SESSION_DATA_BLOCKED.value
        )

    def test_notify_owner_session_event_existing_key(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        session_handle.events = mocker.Mock()
        connection._session_handles["s1"] = session_handle
        existing_session_obj = mocker.Mock()
        effect = EmitSessionEvent(
            session_id="s1", event_type=EventType.SESSION_DATA_BLOCKED, data={"session": existing_session_obj}
        )

        connection._notify_owner(effect)

        session_handle.events.emit_nowait.assert_called_once()
        call_args = session_handle.events.emit_nowait.call_args[1]
        assert call_args["data"]["session"] is existing_session_obj

    def test_notify_owner_session_event_missing_handle_warning(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitSessionEvent(session_id="unknown", event_type=EventType.SESSION_MAX_DATA_UPDATED, data={})

        connection._notify_owner(effect)

        spy_logger.warning.assert_called_with(
            "No session handle found for event %s on session %s", EventType.SESSION_MAX_DATA_UPDATED, "unknown"
        )

    def test_notify_owner_session_event_propagates(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        session_handle.events = mocker.Mock()
        session_handle.events.listener_count.return_value = 1
        connection._session_handles["sess-1"] = session_handle
        effect = EmitSessionEvent(session_id="sess-1", event_type=EventType.SESSION_DATA_BLOCKED, data={})

        connection._notify_owner(effect)

        session_handle.events.emit_nowait.assert_called_once()

    def test_notify_owner_session_request_creates_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        connection._is_client = False
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        session_data = MagicMock()
        session_data.path = "/"
        session_data.headers = {}
        session_data.control_stream_id = 0
        mock_engine._state.sessions.get.return_value = session_data
        effect = EmitSessionEvent(session_id="sess-new", event_type=EventType.SESSION_REQUEST, data={})

        connection._notify_owner(effect)

        assert "sess-new" in connection._session_handles
        assert isinstance(connection._session_handles["sess-new"], WebTransportSession)

    def test_notify_owner_stream_closed_missing_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_create_task = mocker.patch("asyncio.create_task")
        effect = EmitStreamEvent(stream_id=999, event_type=EventType.STREAM_CLOSED, data={})

        connection._notify_owner(effect)

        mock_create_task.assert_not_called()

    def test_notify_owner_stream_closed_removes_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportStream)
        stream_handle.events = mocker.Mock()
        stream_handle.events.close.return_value = asyncio.sleep(delay=0)
        connection._stream_handles[10] = stream_handle
        mock_create_task = mocker.patch("asyncio.create_task")
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_CLOSED, data={})

        connection._notify_owner(effect)

        assert 10 not in connection._stream_handles
        mock_create_task.assert_called_once()
        coro = mock_create_task.call_args.kwargs["coro"]
        coro.close()

    def test_notify_owner_stream_creation_missing_engine(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        del connection._engine
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with("Engine or state missing during stream handle creation for %d.", 10)

    def test_notify_owner_stream_creation_missing_session_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        stream_data = MagicMock(spec=StreamStateData)
        stream_data.session_id = "missing_sess"
        mock_engine._state.streams.get.return_value = stream_data
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with(
            "Stream data (%s) or session handle (%s) missing for stream %d.", True, False, 10
        )

    def test_notify_owner_stream_event_existing_key(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportStream)
        stream_handle.events = mocker.Mock()
        connection._stream_handles[10] = stream_handle
        existing_stream_obj = mocker.Mock()
        effect = EmitStreamEvent(
            stream_id=10, event_type=EventType.STREAM_DATA_RECEIVED, data={"stream": existing_stream_obj}
        )

        connection._notify_owner(effect)

        stream_handle.events.emit_nowait.assert_called_once()
        call_args = stream_handle.events.emit_nowait.call_args[1]
        assert call_args["data"]["stream"] is existing_stream_obj

    def test_notify_owner_stream_event_missing_handle_warning(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitStreamEvent(stream_id=999, event_type=EventType.STREAM_DATA_RECEIVED, data={})

        connection._notify_owner(effect)

        spy_logger.warning.assert_called_with(
            "No stream handle found for event %s on stream %d", EventType.STREAM_DATA_RECEIVED, 999
        )

    def test_notify_owner_stream_event_propagates(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportStream)
        stream_handle.events = mocker.Mock()
        connection._stream_handles[10] = stream_handle
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_DATA_RECEIVED, data={})

        connection._notify_owner(effect)

        stream_handle.events.emit_nowait.assert_called_once()

    @pytest.mark.parametrize(
        "direction, expected_cls",
        [
            (StreamDirection.BIDIRECTIONAL, WebTransportStream),
            (StreamDirection.SEND_ONLY, WebTransportSendStream),
            (StreamDirection.RECEIVE_ONLY, WebTransportReceiveStream),
        ],
    )
    def test_stream_handle_creation_all_directions(
        self, connection: WebTransportConnection, mocker: MockerFixture, direction: StreamDirection, expected_cls: type
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        connection._session_handles["sess-1"] = session_handle
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        stream_data = MagicMock(spec=StreamStateData)
        stream_data.session_id = "sess-1"
        stream_data.direction = direction
        mock_engine._state.streams.get.return_value = stream_data
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data={})

        connection._notify_owner(effect)

        assert 10 in connection._stream_handles
        assert isinstance(connection._stream_handles[10], expected_cls)

    def test_stream_handle_creation_invalid_direction(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        connection._session_handles["sess-1"] = session_handle
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        stream_data = MagicMock(spec=StreamStateData)
        stream_data.session_id = "sess-1"
        stream_data.direction = "UNKNOWN_DIRECTION"
        mock_engine._state.streams.get.return_value = stream_data
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with("Error during owner notification callback: %s", mocker.ANY, exc_info=True)

    def test_notify_owner_stream_opened_late_session_lookup(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportStream)
        stream_handle.events = mocker.Mock()
        connection._stream_handles[10] = stream_handle
        session_handle = mocker.Mock(spec=WebTransportSession)
        connection._session_handles["s1"] = session_handle
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        stream_data = MagicMock(spec=StreamStateData)
        stream_data.session_id = "s1"
        mock_engine._state.streams.get.return_value = stream_data
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data={})

        connection._notify_owner(effect)

        session_handle._add_stream_handle.assert_called_once()

    def test_notify_owner_stream_opened_no_session_found(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportStream)
        stream_handle.events = mocker.Mock()
        connection._stream_handles[10] = stream_handle
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        mock_engine._state.streams.get.return_value = None
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with("No session handle found to propagate STREAM_OPENED for stream %d", 10)

    def test_notify_owner_stream_opened_session_handle_missing(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        stream_handle = mocker.Mock(spec=WebTransportStream)
        stream_handle.events = mocker.Mock()
        connection._stream_handles[10] = stream_handle
        mock_engine = mocker.Mock()
        connection._engine = mock_engine
        stream_data = MagicMock(spec=StreamStateData)
        stream_data.session_id = "s_missing"
        mock_engine._state.streams.get.return_value = stream_data
        spy_logger = mocker.patch("pywebtransport.connection.connection.logger")
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data={})

        connection._notify_owner(effect)

        spy_logger.error.assert_called_with("No session handle found to propagate STREAM_OPENED for stream %d", 10)

    def test_notify_owner_unknown_effect(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        mock_effect = mocker.Mock(spec=Effect)

        connection._notify_owner(mock_effect)

    def test_properties(self, connection: WebTransportConnection, mock_config: MagicMock) -> None:
        assert connection.config == mock_config
        assert isinstance(connection.connection_id, str)
        assert connection.is_client is True
        assert connection.is_closed is False
        assert connection.is_closing is False
        assert connection.is_connected is False

    def test_properties_address(self, connection: WebTransportConnection) -> None:
        cast(MagicMock, connection._transport.get_extra_info).side_effect = lambda k: (
            ("127.0.0.1", 443) if k == "peername" else ("10.0.0.1", 12345)
        )

        assert connection.remote_address == ("127.0.0.1", 443)
        assert connection.local_address == ("10.0.0.1", 12345)

    def test_properties_address_none(self, connection: WebTransportConnection) -> None:
        connection._transport = cast(Any, None)

        assert connection.remote_address is None
        assert connection.local_address is None

    def test_repr(self, connection: WebTransportConnection) -> None:
        assert "id=" in repr(connection)
        assert "state=" in repr(connection)

    @pytest.mark.asyncio
    async def test_send_event_to_engine_missing(self, connection: WebTransportConnection) -> None:
        del connection._engine
        fut: asyncio.Future[Any] = asyncio.Future()
        event = UserConnectionGracefulClose(future=fut)

        await connection._send_event_to_engine(event=event)

        assert fut.done()
        with pytest.raises(ConnectionError, match="engine is missing"):
            await fut

    @pytest.mark.asyncio
    async def test_send_event_to_engine_missing_future_done(self, connection: WebTransportConnection) -> None:
        del connection._engine
        fut: asyncio.Future[Any] = asyncio.Future()
        fut.set_result(None)
        event = UserConnectionGracefulClose(future=fut)

        await connection._send_event_to_engine(event=event)

        assert fut.result() is None

    @pytest.mark.asyncio
    async def test_send_event_to_engine_missing_invalid_state(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        del connection._engine
        mock_fut = mocker.Mock()
        mock_fut.done.return_value = False
        mock_fut.set_exception.side_effect = asyncio.InvalidStateError()
        event = UserConnectionGracefulClose(future=mock_fut)

        await connection._send_event_to_engine(event=event)

        mock_fut.set_exception.assert_called_once()
