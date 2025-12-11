"""Unit tests for the pywebtransport.connection.connection module."""

import asyncio
import weakref
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError, ErrorCodes, SessionError, WebTransportSession
from pywebtransport._adapter.client import WebTransportClientProtocol
from pywebtransport._protocol.events import (
    ConnectionClose,
    EmitConnectionEvent,
    EmitSessionEvent,
    EmitStreamEvent,
    UserCloseSession,
    UserConnectionGracefulClose,
    UserCreateSession,
    UserGetConnectionDiagnostics,
    UserRejectSession,
)
from pywebtransport._protocol.state import ProtocolState
from pywebtransport.connection import ConnectionDiagnostics, WebTransportConnection
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
        mocker.patch("pywebtransport.connection.WebTransportEngine", return_value=mock_engine)
        conn = WebTransportConnection(
            config=mock_config, protocol=mock_protocol, transport=mock_transport, is_client=True
        )
        conn.events = mocker.Mock()
        return conn

    @pytest.fixture
    def mock_config(self, mocker: MockerFixture) -> MagicMock:
        conf = mocker.Mock(spec=ClientConfig)
        conf.max_event_queue_size = 100
        conf.max_event_listeners = 100
        conf.max_event_history_size = 100
        return cast(MagicMock, conf)

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
    def mock_session_cls(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("pywebtransport.connection.WebTransportSession")

    @pytest.fixture
    def mock_transport(self, mocker: MockerFixture) -> MagicMock:
        transport = mocker.Mock(spec=asyncio.DatagramTransport)
        transport.is_closing.return_value = False
        return cast(MagicMock, transport)

    @pytest.mark.asyncio
    async def test_close_cancelled_ignored(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture, mock_loop: MagicMock
    ) -> None:
        mock_engine.put_event.return_value = None
        fut: asyncio.Future[Any] = asyncio.Future()
        mock_loop.create_future.side_effect = None
        mock_loop.create_future.return_value = fut

        class MockCancelled:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.CancelledError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockCancelled)

        await connection.close()

        mock_engine.put_event.assert_awaited()
        mock_engine.stop_driver_loop.assert_awaited_once()
        assert cast(MagicMock, connection._transport.close).called

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
        assert connection.state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_close_generic_exception(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_engine.put_event.return_value = None

        class MockError(Exception):
            pass

        class MockTimeoutError:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise MockError("Unexpected error")

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeoutError)
        spy_logger = mocker.patch("pywebtransport.connection.logger")

        await connection.close()

        mock_engine.stop_driver_loop.assert_awaited_once()
        spy_logger.warning.assert_any_call("Error during close event processing: %s", mocker.ANY)

    @pytest.mark.asyncio
    async def test_close_idempotent(self, connection: WebTransportConnection, mock_engine: MagicMock) -> None:
        connection._cached_state = ConnectionState.CLOSED

        await connection.close()

        mock_engine.put_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close_no_engine(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        del connection._engine
        spy_logger = mocker.patch("pywebtransport.connection.logger")

        await connection.close()

        spy_logger.info.assert_any_call("Closing connection %s...", mocker.ANY)
        assert cast(MagicMock, connection._transport.close).called

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
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        spy_close = mocker.spy(connection, "close")

        await connection.graceful_shutdown()

        spy_logger.warning.assert_any_call("Error during graceful shutdown: %s", mocker.ANY)
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
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        spy_close = mocker.spy(connection, "close")

        fut_shutdown: asyncio.Future[Any] = asyncio.Future()
        fut_close: asyncio.Future[Any] = asyncio.Future()
        mock_loop.create_future.side_effect = [fut_shutdown, fut_close]

        class MockTimeout:
            def __init__(self, delay: float) -> None:
                pass

            async def __aenter__(self) -> None:
                raise asyncio.TimeoutError()

            async def __aexit__(self, *args: Any) -> None:
                pass

        mocker.patch("asyncio.timeout", side_effect=MockTimeout)

        await connection.graceful_shutdown()

        spy_logger.warning.assert_any_call("Timeout waiting for graceful shutdown GOAWAY confirmation.")
        assert fut_shutdown.cancelled()
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
        spy_logger = mocker.patch("pywebtransport.connection.logger")

        await connection.initialize()

        spy_logger.critical.assert_called_with(
            "Engine failed to create event queue during initialization for %s", mocker.ANY
        )
        spy_close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_no_engine(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        del connection._engine
        spy_logger = mocker.patch("pywebtransport.connection.logger")

        await connection.initialize()

        spy_logger.warning.assert_called_with("Attempted to initialize connection %s without an engine.", mocker.ANY)

    def test_internal_engine_state(self, connection: WebTransportConnection) -> None:
        assert connection._get_engine_state() == ConnectionState.IDLE

        del connection._engine._state
        assert connection._get_engine_state() == ConnectionState.CLOSED

        del connection._engine
        assert connection._get_engine_state() == ConnectionState.CLOSED

    @pytest.mark.parametrize(
        "event_type, expected_state, data_preset",
        [
            (EventType.CONNECTION_ESTABLISHED, ConnectionState.CONNECTED, {}),
            (EventType.CONNECTION_CLOSED, ConnectionState.CLOSED, {}),
            (EventType.DATAGRAM_RECEIVED, ConnectionState.IDLE, {"connection": "exists"}),
        ],
    )
    def test_notify_owner_connection_events(
        self,
        connection: WebTransportConnection,
        mocker: MockerFixture,
        event_type: EventType,
        expected_state: ConnectionState,
        data_preset: dict[str, Any],
    ) -> None:
        connection._cached_state = ConnectionState.IDLE
        data = data_preset.copy()
        effect = EmitConnectionEvent(event_type=event_type, data=data)

        connection._notify_owner(effect=effect)

        mock_emit = cast(MagicMock, connection.events.emit_nowait)
        mock_emit.assert_called_once()

        assert connection.state == expected_state

        call_data = mock_emit.call_args[1]["data"]
        if not data_preset:
            assert isinstance(call_data["connection"], weakref.ProxyType)
        else:
            assert call_data["connection"] == "exists"

    def test_notify_owner_exception_handling(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        cast(MagicMock, connection.events.emit_nowait).side_effect = ValueError("Boom")
        effect = EmitConnectionEvent(event_type=EventType.CONNECTION_ESTABLISHED, data={})

        connection._notify_owner(effect=effect)

        spy_logger.error.assert_called_with("Error during owner notification callback: %s", mocker.ANY, exc_info=True)

    def test_notify_owner_session_closed_handle_not_found(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        connection._session_handles.clear()

        effect = EmitSessionEvent(session_id="unknown_sess", event_type=EventType.SESSION_CLOSED, data={})
        connection._notify_owner(effect=effect)

        for call in spy_logger.debug.call_args_list:
            assert "Removed session handle" not in call[0][0]

    def test_notify_owner_session_closed_removes_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        session_handle.events = mocker.Mock()
        connection._session_handles["s1"] = session_handle
        mock_create_task = mocker.patch("asyncio.create_task")

        effect = EmitSessionEvent(session_id="s1", event_type=EventType.SESSION_CLOSED, data={})

        connection._notify_owner(effect=effect)

        assert "s1" not in connection._session_handles
        mock_create_task.assert_called()
        cast(MagicMock, session_handle.events.close).assert_called_once()

    def test_notify_owner_session_creation_logic(
        self, connection: WebTransportConnection, mocker: MockerFixture, mock_session_cls: MagicMock
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        effect_fail = EmitSessionEvent(session_id="s1", event_type=EventType.SESSION_READY, data={})
        connection._notify_owner(effect=effect_fail)
        spy_logger.error.assert_called()
        assert "Missing metadata" in spy_logger.error.call_args[0][0]

        effect_unrelated = EmitSessionEvent(session_id="unknown", event_type=EventType.SESSION_DATA_BLOCKED, data={})
        connection._notify_owner(effect=effect_unrelated)
        spy_logger.warning.assert_called()
        assert "No session handle found" in spy_logger.warning.call_args[0][0]

        connection._is_client = False
        data = {"path": "/", "headers": {}, "control_stream_id": 0}
        effect_req = EmitSessionEvent(session_id="sess-new", event_type=EventType.SESSION_REQUEST, data=data)
        mock_session_instance = mock_session_cls.return_value
        mock_session_instance.events = mocker.Mock()

        connection._notify_owner(effect=effect_req)
        assert "sess-new" in connection._session_handles
        assert connection._session_handles["sess-new"] == mock_session_instance

    def test_notify_owner_session_data_already_contains_handle(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        session_handle.events = mocker.Mock()
        connection._session_handles["s1"] = session_handle

        pre_existing_obj = "not_the_handle"
        data = {"session": pre_existing_obj}
        effect = EmitSessionEvent(session_id="s1", event_type=EventType.SESSION_DATA_BLOCKED, data=data)

        connection._notify_owner(effect=effect)

        cast(MagicMock, session_handle.events.emit_nowait).assert_called()
        call_data = cast(MagicMock, session_handle.events.emit_nowait).call_args[1]["data"]
        assert call_data["session"] == pre_existing_obj

    @pytest.mark.parametrize(
        "event_type, should_warn, listener_count",
        [
            (EventType.SESSION_DATA_BLOCKED, True, 0),
            (EventType.SESSION_DATA_BLOCKED, False, 1),
            (EventType.SESSION_STREAMS_BLOCKED, True, 0),
            (EventType.SESSION_STREAMS_BLOCKED, False, 1),
            (EventType.SESSION_READY, False, 0),
        ],
    )
    def test_notify_owner_session_events_blocking(
        self,
        connection: WebTransportConnection,
        mocker: MockerFixture,
        event_type: EventType,
        should_warn: bool,
        listener_count: int,
    ) -> None:
        session_handle = mocker.Mock(spec=WebTransportSession)
        session_handle.events = mocker.Mock()
        session_handle.events.listener_count.return_value = listener_count
        connection._session_handles["s1"] = session_handle
        spy_logger = mocker.patch("pywebtransport.connection.logger")

        effect = EmitSessionEvent(session_id="s1", event_type=event_type, data={})
        connection._notify_owner(effect=effect)

        if should_warn:
            spy_logger.warning.assert_called_with("Session %s received unhandled event '%s'.", "s1", event_type.value)
        else:
            cast(MagicMock, session_handle.events.emit_nowait).assert_called_once()

            for call in spy_logger.warning.call_args_list:
                assert "received unhandled event" not in call[0][0]

    def test_notify_owner_stream_closed_handle_not_found(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        connection._stream_handles.clear()

        effect = EmitStreamEvent(stream_id=999, event_type=EventType.STREAM_CLOSED, data={})
        connection._notify_owner(effect=effect)

        for call in spy_logger.debug.call_args_list:
            assert "Removed stream handle" not in call[0][0]

    def test_notify_owner_stream_closed_logic(self, connection: WebTransportConnection, mocker: MockerFixture) -> None:
        stream_handle = mocker.Mock()
        stream_handle.events = mocker.Mock()
        connection._stream_handles[99] = stream_handle
        mock_create_task = mocker.patch("asyncio.create_task")

        effect = EmitStreamEvent(stream_id=99, event_type=EventType.STREAM_CLOSED, data={})
        connection._notify_owner(effect=effect)
        assert 99 not in connection._stream_handles
        mock_create_task.assert_called()

        connection._stream_handles[100] = stream_handle
        effect_other = EmitStreamEvent(stream_id=100, event_type=EventType.STREAM_DATA_RECEIVED, data={})
        connection._notify_owner(effect=effect_other)
        assert 100 in connection._stream_handles

    def test_notify_owner_stream_creation_errors(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")

        effect_miss_sess = EmitStreamEvent(
            stream_id=10,
            event_type=EventType.STREAM_OPENED,
            data={"session_id": "s_missing", "direction": StreamDirection.BIDIRECTIONAL},
        )
        connection._notify_owner(effect=effect_miss_sess)
        spy_logger.error.assert_called_with("Session handle %s missing for stream %d creation.", "s_missing", 10)

        effect_miss_meta = EmitStreamEvent(stream_id=11, event_type=EventType.STREAM_OPENED, data={})
        connection._notify_owner(effect=effect_miss_meta)
        assert "Missing metadata" in spy_logger.error.call_args_list[-1][0][0]

        effect_no_handle = EmitStreamEvent(stream_id=999, event_type=EventType.STREAM_DATA_RECEIVED, data={})
        connection._notify_owner(effect=effect_no_handle)
        spy_logger.warning.assert_called_with(
            "No stream handle found for event %s on stream %d", EventType.STREAM_DATA_RECEIVED, 999
        )

    def test_notify_owner_stream_opened_complex_branches(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        stream_handle = mocker.Mock()
        stream_handle.events = mocker.Mock()

        connection._stream_handles[1] = stream_handle
        data_preset = {"stream": "present"}
        effect = EmitStreamEvent(stream_id=1, event_type=EventType.STREAM_DATA_RECEIVED, data=data_preset)
        connection._notify_owner(effect=effect)
        cast(MagicMock, stream_handle.events.emit_nowait).assert_called()
        assert cast(MagicMock, stream_handle.events.emit_nowait).call_args[1]["data"]["stream"] == "present"

        connection._stream_handles[2] = stream_handle
        effect_opened = EmitStreamEvent(stream_id=2, event_type=EventType.STREAM_OPENED, data={"session_id": "s_miss"})
        connection._notify_owner(effect=effect_opened)
        spy_logger.error.assert_called_with("No session handle found to propagate STREAM_OPENED for stream %d", 2)

        session_handle = mocker.Mock(spec=WebTransportSession)
        connection._session_handles["s1"] = session_handle
        connection._stream_handles[3] = stream_handle
        effect_opened_ok = EmitStreamEvent(stream_id=3, event_type=EventType.STREAM_OPENED, data={"session_id": "s1"})
        connection._notify_owner(effect=effect_opened_ok)
        session_handle._add_stream_handle.assert_called_once()

    def test_notify_owner_stream_opened_existing_handle_missing_session_id_key(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        stream_handle = mocker.Mock()
        stream_handle.events = mocker.Mock()
        connection._stream_handles[1] = stream_handle

        data: dict[str, Any] = {}
        effect = EmitStreamEvent(stream_id=1, event_type=EventType.STREAM_OPENED, data=data)

        connection._notify_owner(effect=effect)

        spy_logger.error.assert_called_with("No session handle found to propagate STREAM_OPENED for stream %d", 1)

    def test_notify_owner_stream_opened_existing_handle_unknown_session_id(
        self, connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        spy_logger = mocker.patch("pywebtransport.connection.logger")
        stream_handle = mocker.Mock()
        stream_handle.events = mocker.Mock()
        connection._stream_handles[1] = stream_handle

        data = {"session_id": "unknown_sess"}
        effect = EmitStreamEvent(stream_id=1, event_type=EventType.STREAM_OPENED, data=data)

        connection._notify_owner(effect=effect)

        spy_logger.error.assert_called_with("No session handle found to propagate STREAM_OPENED for stream %d", 1)

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
    async def test_send_event_passthrough_when_closed_if_not_suppressible(
        self, connection: WebTransportConnection, mock_engine: MagicMock
    ) -> None:
        connection._cached_state = ConnectionState.CLOSED
        fut: asyncio.Future[Any] = asyncio.Future()
        event = UserCreateSession(path="/", headers={}, future=fut)

        await connection._send_event_to_engine(event=event)

        mock_engine.put_event.assert_awaited_once_with(event=event)

    @pytest.mark.asyncio
    async def test_send_event_suppressed_future_already_done_skip_set_result(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mock_loop: MagicMock
    ) -> None:
        connection._cached_state = ConnectionState.CLOSED
        fut: asyncio.Future[Any] = asyncio.Future()
        fut.cancel()
        mock_loop.create_future.return_value = fut

        spy_fut = MagicMock()
        spy_fut.done.return_value = True

        event = UserRejectSession(session_id="s1", status_code=403, future=spy_fut)

        await connection._send_event_to_engine(event=event)

        mock_engine.put_event.assert_not_awaited()
        spy_fut.set_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_event_suppressed_future_race_condition(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mock_loop: MagicMock
    ) -> None:
        connection._cached_state = ConnectionState.CLOSED

        race_fut = MagicMock()
        race_fut.done.return_value = False
        race_fut.set_result.side_effect = asyncio.InvalidStateError()

        event = UserRejectSession(session_id="s1", status_code=403, future=race_fut)

        await connection._send_event_to_engine(event=event)

        mock_engine.put_event.assert_not_awaited()
        race_fut.set_result.assert_called()

    @pytest.mark.asyncio
    async def test_send_event_suppressed_when_closed(
        self, connection: WebTransportConnection, mock_engine: MagicMock, mock_loop: MagicMock
    ) -> None:
        connection._cached_state = ConnectionState.CLOSED
        fut: asyncio.Future[Any] = asyncio.Future()
        mock_loop.create_future.side_effect = None
        mock_loop.create_future.return_value = fut
        event = UserCloseSession(session_id="s1", error_code=0, reason="test", future=fut)

        await connection._send_event_to_engine(event=event)

        mock_engine.put_event.assert_not_awaited()
        assert fut.done()
        assert fut.result() is None

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

    @pytest.mark.parametrize(
        "direction, expected_cls",
        [
            (StreamDirection.BIDIRECTIONAL, "pywebtransport.connection.WebTransportStream"),
            (StreamDirection.SEND_ONLY, "pywebtransport.connection.WebTransportSendStream"),
            (StreamDirection.RECEIVE_ONLY, "pywebtransport.connection.WebTransportReceiveStream"),
        ],
    )
    def test_stream_handle_creation_all_directions(
        self,
        connection: WebTransportConnection,
        mocker: MockerFixture,
        direction: StreamDirection,
        expected_cls: str,
        mock_session_cls: MagicMock,
    ) -> None:
        mock_stream_cls = mocker.patch(expected_cls)
        mock_stream_instance = mock_stream_cls.return_value
        mock_stream_instance.events = mocker.Mock()

        session_handle = mocker.Mock(spec=WebTransportSession)
        connection._session_handles["sess-1"] = session_handle

        data = {"session_id": "sess-1", "direction": direction}
        effect = EmitStreamEvent(stream_id=10, event_type=EventType.STREAM_OPENED, data=data)

        connection._notify_owner(effect=effect)

        assert 10 in connection._stream_handles
        assert connection._stream_handles[10] == mock_stream_instance
        cast(MagicMock, mock_stream_instance.events.emit_nowait).assert_called()
        mock_stream_cls.assert_called_once()
