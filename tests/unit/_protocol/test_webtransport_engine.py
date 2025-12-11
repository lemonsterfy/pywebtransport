"""Unit tests for the pywebtransport._protocol.webtransport_engine module."""

import asyncio
import weakref
from collections.abc import AsyncGenerator, Generator
from typing import Any, cast
from unittest.mock import ANY, Mock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError, ErrorCodes, ProtocolError
from pywebtransport._protocol.events import (
    CapsuleReceived,
    CleanupH3Stream,
    CloseQuicConnection,
    CompleteUserFuture,
    ConnectStreamClosed,
    CreateH3Session,
    CreateQuicStream,
    DatagramReceived,
    Effect,
    EmitConnectionEvent,
    EmitSessionEvent,
    FailUserFuture,
    GoawayReceived,
    HeadersReceived,
    InternalBindH3Session,
    InternalBindQuicStream,
    InternalCleanupEarlyEvents,
    InternalCleanupResources,
    InternalFailH3Session,
    InternalFailQuicStream,
    InternalReturnStreamData,
    LogH3Frame,
    ProtocolEvent,
    RescheduleQuicTimer,
    ResetQuicStream,
    SendH3Capsule,
    SendH3Datagram,
    SendH3Goaway,
    SendH3Headers,
    SendQuicData,
    SendQuicDatagram,
    SettingsReceived,
    StopQuicStream,
    TransportConnectionTerminated,
    TransportDatagramFrameReceived,
    TransportHandshakeCompleted,
    TransportQuicParametersReceived,
    TransportQuicTimerFired,
    TransportStreamDataReceived,
    TransportStreamReset,
    TriggerQuicTimer,
    UserAcceptSession,
    UserCloseSession,
    UserConnectionGracefulClose,
    UserCreateSession,
    UserCreateStream,
    UserGetConnectionDiagnostics,
    UserGetSessionDiagnostics,
    UserGetStreamDiagnostics,
    UserGrantDataCredit,
    UserGrantStreamsCredit,
    UserRejectSession,
    UserResetStream,
    UserSendDatagram,
    UserSendStreamData,
    UserStopStream,
    UserStreamRead,
    WebTransportStreamDataReceived,
)
from pywebtransport._protocol.state import SessionStateData
from pywebtransport._protocol.webtransport_engine import WebTransportEngine
from pywebtransport.types import ConnectionState, EventType, SessionState


@pytest.fixture
def mock_config() -> ClientConfig:
    config = ClientConfig()
    config.pending_event_ttl = 0.1
    config.resource_cleanup_interval = 0.1
    config.max_event_queue_size = 100
    return config


@pytest.fixture
def mock_handler(mocker: MockerFixture) -> Generator[Any, None, None]:
    handler = mocker.Mock()
    handler.get_next_available_stream_id.side_effect = [0, 4, 8, 12, 16]
    handler.get_server_name.return_value = "example.com"
    yield handler


@pytest.fixture
def mock_notify_callback(mocker: MockerFixture) -> Any:
    return mocker.Mock()


@pytest_asyncio.fixture
async def engine(
    mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any, mocker: MockerFixture
) -> AsyncGenerator[WebTransportEngine, None]:
    engine_instance = WebTransportEngine(
        connection_id="conn-12345",
        config=mock_config,
        is_client=True,
        protocol_handler=mock_handler,
        owner_notify_callback=mock_notify_callback,
    )
    engine_instance._connection_processor = mocker.Mock()
    engine_instance._session_processor = mocker.Mock()
    engine_instance._stream_processor = mocker.Mock()
    engine_instance._h3_engine = mocker.Mock()

    cast(Mock, engine_instance._connection_processor.handle_cleanup_resources).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_connection_terminated).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_transport_parameters_received).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_goaway_received).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_headers_received).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_graceful_close).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_get_connection_diagnostics).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_create_session).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_connection_close).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_internal_bind_h3_session).return_value = []
    cast(Mock, engine_instance._connection_processor.handle_internal_fail_h3_session).return_value = []

    cast(Mock, engine_instance._stream_processor.handle_transport_stream_reset).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_webtransport_stream_data).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_get_stream_diagnostics).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_reset_stream).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_send_stream_data).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_stop_stream).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_stream_read).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_internal_bind_quic_stream).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_internal_fail_quic_stream).return_value = []
    cast(Mock, engine_instance._stream_processor.handle_return_stream_data).return_value = []

    cast(Mock, engine_instance._session_processor.handle_capsule_received).return_value = []
    cast(Mock, engine_instance._session_processor.handle_connect_stream_closed).return_value = []
    cast(Mock, engine_instance._session_processor.handle_datagram_received).return_value = []
    cast(Mock, engine_instance._session_processor.handle_accept_session).return_value = []
    cast(Mock, engine_instance._session_processor.handle_close_session).return_value = []
    cast(Mock, engine_instance._session_processor.handle_get_session_diagnostics).return_value = []
    cast(Mock, engine_instance._session_processor.handle_grant_data_credit).return_value = []
    cast(Mock, engine_instance._session_processor.handle_grant_streams_credit).return_value = []
    cast(Mock, engine_instance._session_processor.handle_reject_session).return_value = []
    cast(Mock, engine_instance._session_processor.handle_send_datagram).return_value = []
    cast(Mock, engine_instance._session_processor.handle_create_stream).return_value = []

    cast(Mock, engine_instance._h3_engine.handle_transport_event).return_value = ([], [])

    engine_instance.start_driver_loop()
    yield engine_instance
    await engine_instance.stop_driver_loop()


class TestCleanupLoops:

    @pytest.mark.asyncio
    async def test_cleanup_loop_cancellation(self, engine: WebTransportEngine) -> None:
        if engine._early_event_cleanup_task:
            engine._early_event_cleanup_task.cancel()
            try:
                await engine._early_event_cleanup_task
            except asyncio.CancelledError:
                pass

        await asyncio.sleep(delay=0.01)

    @pytest.mark.asyncio
    async def test_cleanup_loops_disabled_via_config(
        self, mock_handler: Any, mock_notify_callback: Any, mocker: MockerFixture
    ) -> None:
        config = ClientConfig()
        config.pending_event_ttl = 0
        config.resource_cleanup_interval = 0

        engine_instance = WebTransportEngine(
            connection_id="conn-disable",
            config=config,
            is_client=True,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )

        engine_instance.start_driver_loop()
        await asyncio.sleep(0.01)

        if engine_instance._early_event_cleanup_task:
            assert engine_instance._early_event_cleanup_task.done()
        if engine_instance._resource_gc_timer_task:
            assert engine_instance._resource_gc_timer_task.done()

        await engine_instance.stop_driver_loop()

    @pytest.mark.asyncio
    async def test_early_event_cleanup_fatal_error(
        self, engine: WebTransportEngine, mocker: MockerFixture, mock_handler: Any
    ) -> None:
        engine._pending_event_ttl = 0.001

        if engine._early_event_cleanup_task:
            engine._early_event_cleanup_task.cancel()

        original_put = engine.put_event

        async def side_effect_put(event: ProtocolEvent) -> None:
            if isinstance(event, InternalCleanupEarlyEvents):
                raise Exception("Early Loop Fatal Error")
            await original_put(event=event)

        mocker.patch.object(engine, "put_event", side_effect=side_effect_put)

        engine._state.early_event_count = 1

        conn_proc_mock = cast(Mock, engine._connection_processor)
        conn_proc_mock.handle_connection_close.return_value = [
            CloseQuicConnection(error_code=ErrorCodes.INTERNAL_ERROR, reason="Early Loop Fatal Error")
        ]

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        engine._early_event_cleanup_task = asyncio.create_task(coro=engine._early_event_cleanup_loop())

        await asyncio.sleep(delay=0.2)

        mock_handler.close_connection.assert_called()
        assert engine._state.connection_state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_early_event_cleanup_triggers_event(self, engine: WebTransportEngine, mocker: MockerFixture) -> None:
        control_stream_id = 10
        mock_now = 1000.0
        mocker.patch("pywebtransport._protocol.webtransport_engine.get_timestamp", return_value=mock_now)

        engine._state.early_event_buffer[control_stream_id] = [(mock_now - 100.0, mocker.Mock())]
        engine._state.early_event_count = 1

        await asyncio.sleep(delay=0.2)

        assert control_stream_id not in engine._state.early_event_buffer
        assert engine._state.early_event_count == 0

    @pytest.mark.asyncio
    async def test_handle_event_internal_cleanup_early_events_no_count(self, engine: WebTransportEngine) -> None:
        engine._state.early_event_count = 0
        await engine.put_event(event=InternalCleanupEarlyEvents())
        await asyncio.sleep(delay=0.01)

    @pytest.mark.asyncio
    async def test_resource_gc_loop_fatal_error(
        self, engine: WebTransportEngine, mocker: MockerFixture, mock_handler: Any
    ) -> None:
        engine._resource_cleanup_interval = 0.001

        original_put = engine.put_event

        async def side_effect_put(event: ProtocolEvent) -> None:
            if isinstance(event, InternalCleanupResources):
                raise Exception("GC Fatal Error")
            await original_put(event=event)

        mocker.patch.object(engine, "put_event", side_effect=side_effect_put)

        conn_proc_mock = cast(Mock, engine._connection_processor)
        conn_proc_mock.handle_connection_close.return_value = [
            CloseQuicConnection(error_code=ErrorCodes.INTERNAL_ERROR, reason="GC Fatal Error")
        ]

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        if engine._resource_gc_timer_task:
            engine._resource_gc_timer_task.cancel()
        engine._resource_gc_timer_task = asyncio.create_task(coro=engine._resource_gc_timer_loop())

        await asyncio.sleep(delay=0.2)

        mock_handler.close_connection.assert_called()
        assert engine._state.connection_state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_resource_gc_loop_triggers_event(self, engine: WebTransportEngine) -> None:
        conn_proc_mock = cast(Mock, engine._connection_processor)
        await asyncio.sleep(delay=0.2)
        conn_proc_mock.handle_cleanup_resources.assert_called()


class TestCoverageGaps:

    @pytest.mark.asyncio
    async def test_check_client_connection_ready_success(
        self, engine: WebTransportEngine, mock_notify_callback: Any, mocker: MockerFixture
    ) -> None:
        engine._state.handshake_complete = True
        engine._state.peer_settings_received = True
        engine._state.connection_state = ConnectionState.CONNECTING
        mocker.patch("pywebtransport._protocol.webtransport_engine.get_timestamp", return_value=1000.0)

        effects, is_ready = engine._check_client_connection_ready()

        assert is_ready
        assert engine._state.connection_state == ConnectionState.CONNECTED
        assert engine._state.connected_at == 1000.0
        assert len(effects) == 1
        assert isinstance(effects[0], EmitConnectionEvent)
        assert effects[0].event_type == EventType.CONNECTION_ESTABLISHED

    @pytest.mark.asyncio
    async def test_check_client_not_ready_without_settings(self, engine: WebTransportEngine) -> None:
        engine._state.handshake_complete = True
        engine._state.peer_settings_received = False
        engine._state.connection_state = ConnectionState.CONNECTING

        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.01)

        assert engine._state.connection_state == ConnectionState.CONNECTING

    @pytest.mark.asyncio
    async def test_create_h3_session_control_stream_failure(
        self, engine: WebTransportEngine, mock_handler: Any
    ) -> None:
        mock_handler.get_next_available_stream_id.side_effect = Exception("No streams")
        fut: asyncio.Future[Any] = asyncio.Future()

        def fail_side_effect(event: Any, state: Any) -> list[Effect]:
            return [FailUserFuture(future=event.future, exception=event.exception)]

        cast(Mock, engine._connection_processor.handle_internal_fail_h3_session).side_effect = fail_side_effect

        await engine._execute_effects(
            effects=[CreateH3Session(session_id="s1", path="/", headers={}, create_future=fut)]
        )

        with pytest.raises(Exception, match="No streams"):
            await fut

    @pytest.mark.asyncio
    async def test_driver_loop_captures_close_reason(
        self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any, mocker: MockerFixture
    ) -> None:
        engine = WebTransportEngine(
            connection_id="c1",
            config=mock_config,
            is_client=True,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        engine._event_queue = asyncio.Queue()
        engine._state.connection_state = ConnectionState.CONNECTED

        engine._connection_processor = mocker.Mock()
        engine._stream_processor = mocker.Mock()

        cast(Mock, engine._connection_processor.handle_cleanup_resources).return_value = []
        cast(Mock, engine._connection_processor.handle_connection_terminated).return_value = []
        cast(Mock, engine._stream_processor.handle_transport_stream_reset).return_value = []

        engine.start_driver_loop()

        close_effect = CloseQuicConnection(error_code=99, reason="Test Exit")
        cast(Mock, engine._stream_processor.handle_transport_stream_reset).return_value = [close_effect]

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        await engine.put_event(event=TransportStreamReset(stream_id=1, error_code=0))

        await asyncio.sleep(delay=0.1)

        mock_notify_callback.assert_called()

        call_args = mock_notify_callback.call_args[0][0]
        assert call_args.event_type == EventType.CONNECTION_CLOSED
        assert call_args.data["reason"] == "Test Exit"
        assert call_args.data["error_code"] == 99

        await engine.stop_driver_loop()

    @pytest.mark.asyncio
    async def test_driver_loop_errors_while_closing(
        self, engine: WebTransportEngine, mock_handler: Any, mocker: MockerFixture
    ) -> None:
        engine._state.connection_state = ConnectionState.CLOSING

        pe = ProtocolError(error_code=1, message="PE")
        mocker.patch.object(engine, "_handle_event", side_effect=pe)
        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.01)
        assert engine._state.connection_state == ConnectionState.CLOSING

        exc = Exception("Gen")
        mocker.patch.object(engine, "_handle_event", side_effect=exc)
        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.01)

        assert engine._state.connection_state == ConnectionState.CLOSING

    @pytest.mark.asyncio
    async def test_driver_loop_fatal_error_cleanup_notification(
        self, engine: WebTransportEngine, mocker: MockerFixture, mock_notify_callback: Any
    ) -> None:
        mocker.patch.object(engine, "_handle_event", side_effect=Exception("Catastrophic"))
        engine._state.connection_state = ConnectionState.CONNECTED

        mocker.patch.object(engine, "_execute_effects", side_effect=Exception("Failed to close"))

        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.05)

        assert engine._state.connection_state == ConnectionState.CLOSED
        mock_notify_callback.assert_called()
        call_args = mock_notify_callback.call_args[0][0]
        assert call_args.event_type == EventType.CONNECTION_CLOSED
        assert call_args.data["error_code"] == ErrorCodes.INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_driver_loop_fatal_error_fails_cleanup(
        self, engine: WebTransportEngine, mocker: MockerFixture, mock_handler: Any, mock_notify_callback: Any
    ) -> None:
        mocker.patch.object(engine, "_handle_event", return_value=[RescheduleQuicTimer()])

        cast(Mock, mock_handler.schedule_timer_now).side_effect = Exception("Primary Failed")

        original_execute = engine._execute_effects

        async def execute_side_effect(effects: list[Effect]) -> None:
            if effects and isinstance(effects[0], CloseQuicConnection):
                raise Exception("Forced Cleanup Failure")
            await original_execute(effects=effects)

        mocker.patch.object(engine, "_execute_effects", side_effect=execute_side_effect)

        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.05)

        assert engine._state.connection_state == ConnectionState.CLOSED

        mock_notify_callback.assert_called()
        call_args = mock_notify_callback.call_args[0][0]
        assert call_args.event_type == EventType.CONNECTION_CLOSED
        assert call_args.data["reason"] == "Effect execution error, close failed"

    @pytest.mark.asyncio
    async def test_driver_loop_final_owner_notify_error(
        self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any, mocker: MockerFixture
    ) -> None:
        engine = WebTransportEngine(
            connection_id="c1",
            config=mock_config,
            is_client=True,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        engine._event_queue = asyncio.Queue()

        mock_notify_callback.side_effect = Exception("Callback Boom")

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        engine.start_driver_loop()

        await engine.put_event(event=TransportConnectionTerminated(error_code=0, reason_phrase=""))
        await asyncio.sleep(delay=0.1)

        assert engine._state.connection_state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_driver_loop_no_queue(
        self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any
    ) -> None:
        engine = WebTransportEngine(
            connection_id="c1",
            config=mock_config,
            is_client=True,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        engine._event_queue = None
        await engine._driver_loop()

    @pytest.mark.asyncio
    async def test_driver_loop_protocol_error(self, engine: WebTransportEngine, mocker: MockerFixture) -> None:
        error = ProtocolError(message="Proto Error", error_code=123)
        mocker.patch.object(engine, "_handle_event", side_effect=error)
        spy_execute = mocker.spy(engine, "_execute_effects")

        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.05)

        assert engine._state.connection_state == ConnectionState.CLOSING
        assert spy_execute.call_count >= 1
        effects = spy_execute.call_args[1]["effects"]
        assert isinstance(effects[0], CloseQuicConnection)
        assert effects[0].error_code == 123

    @pytest.mark.asyncio
    async def test_driver_loop_exit_cleanly(self, engine: WebTransportEngine) -> None:
        assert engine._driver_task is not None
        assert not engine._driver_task.done()

        engine._state.connection_state = ConnectionState.CLOSED
        async with asyncio.timeout(delay=1.0):
            await engine._driver_task

        assert engine._early_event_cleanup_task is None
        assert engine._resource_gc_timer_task is None

    @pytest.mark.asyncio
    async def test_execute_effect_cleanup_h3_stream_no_engine(self, engine: WebTransportEngine) -> None:
        del engine._h3_engine
        await engine._execute_effects(effects=[CleanupH3Stream(stream_id=1)])

    @pytest.mark.asyncio
    async def test_execute_effect_close_quic_connection_already_closing(
        self, engine: WebTransportEngine, mock_handler: Any, mocker: MockerFixture
    ) -> None:
        engine._state.connection_state = ConnectionState.CLOSING
        mocker.patch("pywebtransport._protocol.webtransport_engine.get_timestamp", return_value=999.0)

        await engine._execute_effects(effects=[CloseQuicConnection(error_code=0, reason="Test")])

        assert engine._state.closed_at is None

    @pytest.mark.asyncio
    async def test_execute_effect_close_quic_connection_transition_to_closing(
        self, engine: WebTransportEngine, mock_handler: Any, mocker: MockerFixture
    ) -> None:
        engine._state.connection_state = ConnectionState.CONNECTED
        mocker.patch("pywebtransport._protocol.webtransport_engine.get_timestamp", return_value=777.0)

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSING

        mock_handler.close_connection.side_effect = close_side_effect

        await engine._execute_effects(effects=[CloseQuicConnection(error_code=0, reason="Test")])

        assert engine._state.connection_state == ConnectionState.CLOSING
        assert engine._state.closed_at == 777.0

    @pytest.mark.asyncio
    async def test_execute_effect_close_quic_connection_transition_to_closed(
        self, engine: WebTransportEngine, mock_handler: Any, mock_notify_callback: Any, mocker: MockerFixture
    ) -> None:
        engine._state.connection_state = ConnectionState.CONNECTED
        mocker.patch("pywebtransport._protocol.webtransport_engine.get_timestamp", return_value=888.0)

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        await engine._execute_effects(effects=[CloseQuicConnection(error_code=0, reason="Test")])

        assert engine._state.closed_at == 888.0
        mock_notify_callback.assert_called_with(
            EmitConnectionEvent(
                event_type=EventType.CONNECTION_CLOSED,
                data={"connection_id": engine._connection_id, "reason": "Test", "error_code": 0},
            )
        )

    @pytest.mark.asyncio
    async def test_execute_effect_complete_user_future_cancelled_with_data(self, engine: WebTransportEngine) -> None:
        fut: asyncio.Future[Any] = asyncio.Future()
        fut.cancel()
        setattr(fut, "stream_id", 100)

        await engine._execute_effects(effects=[CompleteUserFuture(future=fut, value=b"data")])
        await asyncio.sleep(delay=0.01)

        mock_stream_proc = cast(Mock, engine._stream_processor)
        mock_stream_proc.handle_return_stream_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_effect_complete_user_future_cancelled_with_data_no_stream_id(
        self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        fut: asyncio.Future[Any] = asyncio.Future()
        fut.cancel()

        await engine._execute_effects(effects=[CompleteUserFuture(future=fut, value=b"data_lost")])
        assert "Read future cancelled with data, but stream_id missing. Data lost." in caplog.text

    @pytest.mark.asyncio
    async def test_execute_effect_create_h3_session_missing_sni(
        self, engine: WebTransportEngine, mock_handler: Any
    ) -> None:
        mock_handler.get_server_name.return_value = None
        fut: asyncio.Future[Any] = asyncio.Future()

        def fail_side_effect(event: Any, state: Any) -> list[Effect]:
            return [FailUserFuture(future=event.future, exception=event.exception)]

        cast(Mock, engine._connection_processor.handle_internal_fail_h3_session).side_effect = fail_side_effect

        await engine._execute_effects(
            effects=[CreateH3Session(session_id="nosni", path="/", headers={}, create_future=fut)]
        )

        with pytest.raises(ConnectionError, match="missing server name"):
            await fut

    @pytest.mark.asyncio
    async def test_execute_effect_create_h3_session_success_verify_state(
        self, engine: WebTransportEngine, mock_handler: Any, mocker: MockerFixture
    ) -> None:
        mock_handler.get_next_available_stream_id.side_effect = None
        mock_handler.get_next_available_stream_id.return_value = 100
        cast(Mock, engine._h3_engine).encode_headers.return_value = []

        fut: asyncio.Future[Any] = asyncio.Future()
        await engine._execute_effects(
            effects=[CreateH3Session(session_id="s1", path="/p", headers={}, create_future=fut)]
        )
        await asyncio.sleep(delay=0.01)

        mock_conn_proc = cast(Mock, engine._connection_processor)
        mock_conn_proc.handle_internal_bind_h3_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_effect_create_quic_stream(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        mock_handler.get_next_available_stream_id.side_effect = None
        mock_handler.get_next_available_stream_id.return_value = 200
        cast(Mock, engine._h3_engine).encode_webtransport_stream_creation.return_value = []

        fut: asyncio.Future[Any] = asyncio.Future()
        await engine._execute_effects(
            effects=[CreateQuicStream(session_id="s1", is_unidirectional=False, create_future=fut)]
        )
        await asyncio.sleep(delay=0.01)

        mock_stream_proc = cast(Mock, engine._stream_processor)
        mock_stream_proc.handle_internal_bind_quic_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_effect_create_quic_stream_failures(
        self, engine: WebTransportEngine, mock_handler: Any
    ) -> None:
        cast(Mock, engine._h3_engine).encode_webtransport_stream_creation.side_effect = Exception("Encode Fail")

        fut2: asyncio.Future[Any] = asyncio.Future()

        def fail_side_effect(event: Any, state: Any) -> list[Effect]:
            return [FailUserFuture(future=event.future, exception=event.exception)]

        cast(Mock, engine._stream_processor.handle_internal_fail_quic_stream).side_effect = fail_side_effect

        await engine._execute_effects(
            effects=[CreateQuicStream(session_id="s1", is_unidirectional=False, create_future=fut2)]
        )
        with pytest.raises(Exception, match="Encode Fail"):
            await fut2

    @pytest.mark.asyncio
    async def test_execute_effect_delegates(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        cast(Mock, engine._h3_engine).cleanup_stream = Mock()
        await engine._execute_effects(effects=[CleanupH3Stream(stream_id=3)])
        cast(Mock, engine._h3_engine).cleanup_stream.assert_called_with(stream_id=3)

        await engine._execute_effects(effects=[RescheduleQuicTimer()])
        mock_handler.schedule_timer_now.assert_called_once()
        mock_handler.schedule_timer_now.reset_mock()

        await engine._execute_effects(effects=[TriggerQuicTimer()])
        mock_handler.handle_timer_now.assert_called_once()

        await engine._execute_effects(effects=[StopQuicStream(stream_id=1, error_code=99)])
        mock_handler.stop_stream.assert_called_with(stream_id=1, error_code=99)

        await engine._execute_effects(effects=[ResetQuicStream(stream_id=2, error_code=88)])
        mock_handler.reset_stream.assert_called_with(stream_id=2, error_code=88)

        await engine._execute_effects(effects=[LogH3Frame(category="cat", event="ev", data={})])
        mock_handler.log_event.assert_called_with(category="cat", event="ev", data={})

        await engine._execute_effects(effects=[SendQuicDatagram(data=b"datagram")])
        mock_handler.send_datagram_frame.assert_called_with(data=b"datagram")

    @pytest.mark.asyncio
    async def test_execute_effect_handler_lost(self, engine: WebTransportEngine, mocker: MockerFixture) -> None:
        engine._protocol_handler = cast(weakref.ReferenceType[Any], lambda: None)

        fut1: asyncio.Future[Any] = asyncio.Future()
        fut2: asyncio.Future[Any] = asyncio.Future()
        fut3: asyncio.Future[Any] = asyncio.Future()
        fut4: asyncio.Future[Any] = asyncio.Future()

        fut_fail_set = mocker.Mock(spec=asyncio.Future)
        fut_fail_set.done.return_value = False
        fut_fail_set.set_exception.side_effect = asyncio.InvalidStateError()

        effects: list[Effect] = [
            CompleteUserFuture(future=fut1, value="success"),
            FailUserFuture(future=fut2, exception=Exception("test")),
            CreateH3Session(session_id="s1", path="/", headers={}, create_future=fut3),
            CreateQuicStream(session_id="s1", is_unidirectional=False, create_future=fut4),
            FailUserFuture(future=fut_fail_set, exception=Exception("ignored")),
        ]

        await engine._execute_effects(effects=effects)

        with pytest.raises(ConnectionError, match="Protocol handler lost"):
            await fut1

        with pytest.raises(Exception, match="test"):
            await fut2
        with pytest.raises(ConnectionError):
            await fut3
        with pytest.raises(ConnectionError):
            await fut4

        fut_fail_set.set_exception.assert_called()

    @pytest.mark.asyncio
    async def test_execute_effect_send_h3_actions(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        h3_mock = cast(Mock, engine._h3_engine)

        h3_mock.encode_capsule.return_value = b"capsule"
        await engine._execute_effects(effects=[SendH3Capsule(stream_id=1, capsule_type=1, capsule_data=b"d")])
        mock_handler.send_stream_data.assert_any_call(stream_id=1, data=b"capsule", end_stream=False)

        h3_mock.encode_headers.return_value = [SendQuicData(stream_id=1, data=b"h", end_stream=True)]
        await engine._execute_effects(effects=[SendH3Headers(stream_id=1, status=200, end_stream=True)])
        mock_handler.send_stream_data.assert_any_call(stream_id=1, data=b"h", end_stream=True)

        h3_mock._local_control_stream_id = 99
        h3_mock.encode_goaway_frame.return_value = b"goaway"
        await engine._execute_effects(effects=[SendH3Goaway()])
        mock_handler.send_stream_data.assert_any_call(stream_id=99, data=b"goaway", end_stream=False)

    @pytest.mark.asyncio
    async def test_execute_effect_send_h3_datagram(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        stream_id = 10
        data = b"payload"
        encoded_data = b"encoded_payload"

        h3_mock = cast(Mock, engine._h3_engine)
        h3_mock.encode_datagram.return_value = encoded_data

        effects: list[Effect] = [SendH3Datagram(stream_id=stream_id, data=data)]

        await engine._execute_effects(effects=effects)

        h3_mock.encode_datagram.assert_called_once_with(stream_id=stream_id, data=data)
        mock_handler.send_datagram_frame.assert_called_once_with(data=encoded_data)

    @pytest.mark.asyncio
    async def test_execute_effect_send_h3_goaway_no_control_stream(
        self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        cast(Mock, engine._h3_engine)._local_control_stream_id = None
        await engine._execute_effects(effects=[SendH3Goaway()])
        assert "Cannot send GOAWAY" in caplog.text

    @pytest.mark.asyncio
    async def test_execute_effect_send_h3_headers_no_fin(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        cast(Mock, engine._h3_engine).encode_headers.return_value = [SendQuicData(stream_id=1, data=b"h")]

        await engine._execute_effects(effects=[SendH3Headers(stream_id=1, status=200, end_stream=False)])

        cast(Mock, engine._h3_engine).encode_headers.assert_called_with(
            stream_id=1, headers={":status": "200"}, end_stream=False
        )

    @pytest.mark.asyncio
    async def test_execute_effect_send_quic_datagram(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        effects: list[Effect] = [SendQuicDatagram(data=b"datagram")]
        await engine._execute_effects(effects=effects)
        mock_handler.send_datagram_frame.assert_called_once_with(data=b"datagram")

    @pytest.mark.asyncio
    async def test_execute_effect_user_futures(self, engine: WebTransportEngine) -> None:
        fut1: asyncio.Future[Any] = asyncio.Future()
        fut2: asyncio.Future[Any] = asyncio.Future()
        exc = ValueError("oops")

        effects: list[Effect] = [CompleteUserFuture(future=fut1, value=42), FailUserFuture(future=fut2, exception=exc)]

        await engine._execute_effects(effects=effects)

        assert await fut1 == 42
        with pytest.raises(ValueError, match="oops"):
            await fut2

    @pytest.mark.asyncio
    async def test_execute_effects_close_fail_during_exception(
        self, engine: WebTransportEngine, mock_handler: Any
    ) -> None:
        await engine.stop_driver_loop()

        cast(Mock, mock_handler.schedule_timer_now).side_effect = Exception("Effect Error")
        cast(Mock, mock_handler.close_connection).side_effect = Exception("Close Error")

        await engine._execute_effects(effects=[RescheduleQuicTimer()])

        assert engine._state.connection_state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_execute_effects_exception_handling(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        effects: list[Effect] = [RescheduleQuicTimer()]
        cast(Mock, mock_handler.schedule_timer_now).side_effect = Exception("Boom")

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        await engine._execute_effects(effects=effects)

        mock_handler.close_connection.assert_called_with(
            error_code=ErrorCodes.INTERNAL_ERROR, reason_phrase="Effect execution error"
        )
        assert engine._state.connection_state == ConnectionState.CLOSED

    @pytest.mark.asyncio
    async def test_execute_effects_fail_remaining_futures_invalid_state(
        self, engine: WebTransportEngine, mocker: MockerFixture
    ) -> None:
        mock_handler = engine._protocol_handler()
        cast(Mock, mock_handler).schedule_timer_now.side_effect = Exception("Initial Error")

        fut_fail = mocker.Mock(spec=asyncio.Future)
        fut_fail.done.return_value = False
        fut_fail.set_exception.side_effect = asyncio.InvalidStateError()

        effects: list[Effect] = [RescheduleQuicTimer(), FailUserFuture(future=fut_fail, exception=Exception("skip"))]

        await engine._execute_effects(effects=effects)
        fut_fail.set_exception.assert_called()

    @pytest.mark.asyncio
    async def test_execute_effects_fatal_error_while_closing(
        self, engine: WebTransportEngine, mock_handler: Any
    ) -> None:
        engine._state.connection_state = ConnectionState.CLOSING
        cast(Mock, mock_handler.schedule_timer_now).side_effect = Exception("Boom")
        await engine._execute_effects(effects=[RescheduleQuicTimer()])
        mock_handler.close_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_effects_future_already_done(self, engine: WebTransportEngine) -> None:
        fut1: asyncio.Future[Any] = asyncio.Future()
        fut1.cancel()
        fut2: asyncio.Future[Any] = asyncio.Future()
        fut2.set_result(100)

        effects: list[Effect] = [
            CompleteUserFuture(future=fut1, value=1),
            FailUserFuture(future=fut2, exception=Exception()),
        ]
        await engine._execute_effects(effects=effects)

    @pytest.mark.asyncio
    async def test_execute_effects_future_race_condition(self, engine: WebTransportEngine) -> None:
        fut1 = Mock(spec=asyncio.Future)
        fut1.done.return_value = False
        fut1.set_exception.side_effect = asyncio.InvalidStateError()

        effects: list[Effect] = [FailUserFuture(future=fut1, exception=Exception("Race"))]
        await engine._execute_effects(effects=effects)

        fut1.set_exception.assert_called()

        fut2 = Mock(spec=asyncio.Future)
        fut2.done.return_value = False
        fut2.cancelled.return_value = False
        fut2.set_result.side_effect = asyncio.InvalidStateError()

        effects2: list[Effect] = [CompleteUserFuture(future=fut2, value=1)]
        await engine._execute_effects(effects=effects2)

        fut2.set_result.assert_called()

    @pytest.mark.asyncio
    async def test_execute_effects_unknown_effect(
        self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        class UnknownEffect(Effect):
            pass

        await engine._execute_effects(effects=[cast(Effect, UnknownEffect())])
        assert "Unhandled effect type" in caplog.text


class TestEngineLifecycle:

    def test_init_state(self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any) -> None:
        engine = WebTransportEngine(
            connection_id="conn-1",
            config=mock_config,
            is_client=True,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        assert engine._state.connection_state == ConnectionState.IDLE

    @pytest.mark.asyncio
    async def test_driver_loop_cancellation(self, engine: WebTransportEngine) -> None:
        await engine.stop_driver_loop()
        assert engine._driver_task is None

    @pytest.mark.asyncio
    async def test_driver_loop_fatal_error_handling(
        self, engine: WebTransportEngine, mock_handler: Any, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(engine, "_handle_event", side_effect=Exception("Fatal Crash"))

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.05)

        assert engine._state.connection_state == ConnectionState.CLOSED
        mock_handler.close_connection.assert_called_with(error_code=ErrorCodes.INTERNAL_ERROR, reason_phrase=ANY)

    @pytest.mark.asyncio
    async def test_driver_loop_protocol_error(
        self, engine: WebTransportEngine, mock_handler: Any, mocker: MockerFixture
    ) -> None:
        error = ProtocolError(error_code=123, message="ProtoErr")
        mocker.patch.object(engine, "_handle_event", side_effect=error)

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.05)

        mock_handler.close_connection.assert_called_with(error_code=123, reason_phrase=ANY)

    @pytest.mark.asyncio
    async def test_start_loop_idempotency(self, engine: WebTransportEngine) -> None:
        task1 = engine._driver_task
        engine.start_driver_loop()
        assert engine._driver_task is task1

    @pytest.mark.asyncio
    async def test_start_driver_loop_state_transitions(
        self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any
    ) -> None:
        engine = WebTransportEngine(
            connection_id="conn-1",
            config=mock_config,
            is_client=True,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        engine._state.connection_state = ConnectionState.IDLE

        engine.start_driver_loop()
        assert engine._state.connection_state == ConnectionState.CONNECTING

        engine._state.connection_state = ConnectionState.CONNECTED
        engine._driver_task = None
        engine.start_driver_loop()
        assert engine._state.connection_state == ConnectionState.CONNECTED
        await engine.stop_driver_loop()

    @pytest.mark.asyncio
    async def test_stop_driver_loop_drains_pending_user_events(self, engine: WebTransportEngine) -> None:
        if engine._driver_task:
            engine._driver_task.cancel()
            try:
                await engine._driver_task
            except asyncio.CancelledError:
                pass

        if engine._event_queue is None:
            engine._event_queue = asyncio.Queue()

        fut: asyncio.Future[Any] = asyncio.Future()
        event = UserCreateSession(future=fut, path="/", headers={})

        engine._event_queue.put_nowait(event)

        await engine.stop_driver_loop()

        with pytest.raises(ConnectionError, match="Engine stopped"):
            await fut

    @pytest.mark.asyncio
    async def test_stop_driver_loop_drains_user_events_invalid_state(
        self, engine: WebTransportEngine, mocker: MockerFixture
    ) -> None:
        if engine._driver_task:
            engine._driver_task.cancel()
            try:
                await engine._driver_task
            except asyncio.CancelledError:
                pass

        if engine._event_queue is None:
            engine._event_queue = asyncio.Queue()

        mock_fut = mocker.Mock(spec=asyncio.Future)
        mock_fut.done.return_value = False
        mock_fut.set_exception.side_effect = asyncio.InvalidStateError()

        event = UserCreateSession(future=mock_fut, path="/", headers={})
        engine._event_queue.put_nowait(event)

        await engine.stop_driver_loop()
        mock_fut.set_exception.assert_called()


class TestEventProcessing:

    @pytest.mark.asyncio
    async def test_check_client_connection_ready_logic(
        self, engine: WebTransportEngine, mock_handler: Any, mock_notify_callback: Any
    ) -> None:
        engine._state.handshake_complete = True
        engine._state.connection_state = ConnectionState.CONNECTING

        cast(Mock, engine._h3_engine)._settings_received = False

        def side_effect(*args: Any, **kwargs: Any) -> tuple[list[Any], list[Any]]:
            cast(Mock, engine._h3_engine)._settings_received = True
            return ([], [])

        cast(Mock, engine._h3_engine).handle_transport_event.side_effect = side_effect

        await engine.put_event(event=TransportStreamDataReceived(data=b"", end_stream=False, stream_id=0))
        await asyncio.sleep(delay=0.01)

        current_state: Any = engine._state.connection_state
        assert current_state == ConnectionState.CONNECTED
        mock_notify_callback.assert_called_with(
            EmitConnectionEvent(
                event_type=EventType.CONNECTION_ESTABLISHED, data={"connection_id": engine._connection_id}
            )
        )

    @pytest.mark.asyncio
    async def test_datagram_received_delegation(self, engine: WebTransportEngine) -> None:
        event = DatagramReceived(data=b"test", stream_id=0)
        session_proc_mock = cast(Mock, engine._session_processor)
        await engine.put_event(event=event)
        await asyncio.sleep(delay=0.01)
        session_proc_mock.handle_datagram_received.assert_called_once_with(event=event, state=engine._state)

    @pytest.mark.asyncio
    async def test_handle_event_capsule_received_delegation(self, engine: WebTransportEngine) -> None:
        ev = CapsuleReceived(capsule_data=b"", capsule_type=1, stream_id=0)
        cast(Mock, engine._session_processor).handle_capsule_received.return_value = []
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._session_processor).handle_capsule_received.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_cleanup_early_events_expires_items(
        self, engine: WebTransportEngine, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport._protocol.webtransport_engine.get_timestamp", return_value=1000.0)
        engine._pending_event_ttl = 10.0

        engine._state.early_event_buffer[1] = [
            (900.0, WebTransportStreamDataReceived(stream_id=1, data=b"", stream_ended=False, control_stream_id=0))
        ]
        engine._state.early_event_count = 1

        await engine.put_event(event=InternalCleanupEarlyEvents())
        await asyncio.sleep(delay=0.01)

        assert engine._state.early_event_count == 0
        assert 1 not in engine._state.early_event_buffer

    @pytest.mark.asyncio
    async def test_handle_event_goaway_received_delegation(self, engine: WebTransportEngine) -> None:
        ev = GoawayReceived()
        cast(Mock, engine._connection_processor).handle_goaway_received.return_value = []
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._connection_processor).handle_goaway_received.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_internal_bind_h3_session(self, engine: WebTransportEngine) -> None:
        ev = InternalBindH3Session(session_id="s1", control_stream_id=10, future=asyncio.Future())
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._connection_processor).handle_internal_bind_h3_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_internal_bind_quic_stream(self, engine: WebTransportEngine) -> None:
        ev = InternalBindQuicStream(stream_id=1, session_id="s1", is_unidirectional=False, future=asyncio.Future())
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._stream_processor).handle_internal_bind_quic_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_internal_cleanup_early_events(self, engine: WebTransportEngine, mocker: MockerFixture) -> None:
        mock_now = 1000.0
        mocker.patch("pywebtransport._protocol.webtransport_engine.get_timestamp", return_value=mock_now)
        engine._pending_event_ttl = 0.1

        engine._state.early_event_count = 1
        engine._state.early_event_buffer[100] = [
            (
                mock_now - 1.0,
                WebTransportStreamDataReceived(stream_id=100, data=b"", stream_ended=False, control_stream_id=0),
            )
        ]

        await engine.put_event(event=InternalCleanupEarlyEvents())
        await asyncio.sleep(delay=0.01)
        assert engine._state.early_event_count == 0

    @pytest.mark.asyncio
    async def test_handle_event_internal_fail_h3_session(self, engine: WebTransportEngine) -> None:
        ev = InternalFailH3Session(session_id="s1", exception=Exception(), future=asyncio.Future())
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._connection_processor).handle_internal_fail_h3_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_internal_fail_quic_stream(self, engine: WebTransportEngine) -> None:
        ev = InternalFailQuicStream(
            session_id="s1", is_unidirectional=False, exception=Exception(), future=asyncio.Future()
        )
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._stream_processor).handle_internal_fail_quic_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_internal_return_stream_data(self, engine: WebTransportEngine) -> None:
        ev = InternalReturnStreamData(stream_id=1, data=b"data")
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._stream_processor).handle_return_stream_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_event_safety_net_reschedules_timer(
        self, engine: WebTransportEngine, mock_handler: Any
    ) -> None:
        event = TransportDatagramFrameReceived(data=b"test")
        cast(Mock, engine._h3_engine).handle_transport_event.return_value = ([], [])

        await engine.put_event(event=event)
        await asyncio.sleep(delay=0.01)

        mock_handler.schedule_timer_now.assert_called()

    @pytest.mark.asyncio
    async def test_handle_event_settings_received_delegation(self, engine: WebTransportEngine) -> None:
        ev = SettingsReceived(settings={})
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)

    @pytest.mark.asyncio
    async def test_handle_event_transport_stream_reset_delegation(self, engine: WebTransportEngine) -> None:
        ev = TransportStreamReset(stream_id=1, error_code=0)
        cast(Mock, engine._stream_processor).handle_transport_stream_reset.return_value = []
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._stream_processor).handle_transport_stream_reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_protocol_error_in_loop(self, engine: WebTransportEngine, mock_handler: Any) -> None:
        exception = ConnectionError(message="Simulated Failure", error_code=ErrorCodes.INTERNAL_ERROR)
        cast(Mock, engine._connection_processor).handle_connection_terminated.side_effect = exception

        def side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = side_effect

        await engine.put_event(event=TransportConnectionTerminated(error_code=0, reason_phrase=""))
        await asyncio.sleep(delay=0.05)

        mock_handler.close_connection.assert_called_with(error_code=ErrorCodes.INTERNAL_ERROR, reason_phrase=ANY)

    @pytest.mark.asyncio
    async def test_handle_transport_handshake_completed_no_handler(
        self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        engine._protocol_handler = cast(weakref.ReferenceType[Any], lambda: None)
        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.01)
        assert "Protocol handler lost during H3 initialization" in caplog.text

    @pytest.mark.asyncio
    async def test_handle_transport_handshake_completed_h3_init_fail(
        self, engine: WebTransportEngine, mock_handler: Any
    ) -> None:
        cast(Mock, engine._h3_engine).initialize_connection.side_effect = Exception("H3 Init Fail")
        mock_handler.get_next_available_stream_id.side_effect = [0, 4, 8]

        def close_side_effect(*args: Any, **kwargs: Any) -> None:
            engine._state.connection_state = ConnectionState.CLOSED

        mock_handler.close_connection.side_effect = close_side_effect

        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.05)

        mock_handler.close_connection.assert_called_with(error_code=ErrorCodes.INTERNAL_ERROR, reason_phrase=ANY)

    @pytest.mark.asyncio
    async def test_handle_transport_handshake_completed_unexpected_state(self, engine: WebTransportEngine) -> None:
        engine._state.connection_state = ConnectionState.CONNECTED
        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.01)
        assert engine._state.connection_state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_headers_received_no_session_event(self, engine: WebTransportEngine) -> None:
        mock_conn_proc = cast(Mock, engine._connection_processor)
        mock_conn_proc.handle_headers_received.return_value = []

        await engine.put_event(event=HeadersReceived(stream_id=1, headers={}, stream_ended=False))
        await asyncio.sleep(delay=0.01)

    @pytest.mark.asyncio
    async def test_headers_received_requeues_early_events(self, engine: WebTransportEngine) -> None:
        sid = "s1"
        ctrl_sid = 10
        session_data = SessionStateData(
            session_id=sid,
            control_stream_id=ctrl_sid,
            state=cast(SessionState, ANY),
            path="/",
            headers={},
            created_at=0,
            local_max_data=0,
            peer_max_data=0,
            local_max_streams_bidi=0,
            peer_max_streams_bidi=0,
            local_max_streams_uni=0,
            peer_max_streams_uni=0,
        )
        engine._state.sessions[sid] = session_data

        mock_buffered_event = Mock(spec=ProtocolEvent)
        engine._state.early_event_buffer[ctrl_sid] = [(0.0, mock_buffered_event)]
        engine._state.early_event_count = 1

        mock_conn_proc = cast(Mock, engine._connection_processor)
        mock_conn_proc.handle_headers_received.return_value = [
            EmitSessionEvent(session_id=sid, event_type=EventType.SESSION_READY, data={})
        ]

        await engine.put_event(event=HeadersReceived(stream_id=ctrl_sid, headers={}, stream_ended=False))
        await asyncio.sleep(delay=0.01)

        assert engine._state.early_event_count == 0
        assert ctrl_sid not in engine._state.early_event_buffer

    @pytest.mark.asyncio
    async def test_internal_cleanup_resources(self, engine: WebTransportEngine) -> None:
        mock_proc = cast(Mock, engine._connection_processor)
        await engine.put_event(event=InternalCleanupResources())
        await asyncio.sleep(delay=0.01)
        mock_proc.handle_cleanup_resources.assert_called_once()

    @pytest.mark.asyncio
    async def test_put_event_queue_full_datagram_dropped(
        self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        engine._config.max_event_queue_size = 1
        engine._event_queue = asyncio.Queue(maxsize=1)
        engine._event_queue.put_nowait(TransportQuicTimerFired())

        event = TransportDatagramFrameReceived(data=b"dropped")
        await engine.put_event(event=event)

        assert "Event queue full" in caplog.text
        assert "dropping datagram event" in caplog.text

    @pytest.mark.asyncio
    async def test_put_event_queue_full_critical_lost(
        self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        engine._config.max_event_queue_size = 1
        engine._event_queue = asyncio.Queue(maxsize=1)
        engine._event_queue.put_nowait(TransportQuicTimerFired())

        event = TransportQuicTimerFired()
        await engine.put_event(event=event)

        assert "Event queue full" in caplog.text
        assert "critical event lost" in caplog.text
        assert engine._internal_error is not None
        assert engine._internal_error[0] == ErrorCodes.INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_put_event_queue_full_user_event_rejected(self, engine: WebTransportEngine) -> None:
        engine._config.max_event_queue_size = 1
        engine._event_queue = asyncio.Queue(maxsize=1)
        engine._event_queue.put_nowait(TransportQuicTimerFired())

        fut: asyncio.Future[Any] = asyncio.Future()
        event = UserSendDatagram(data=b"test", session_id="s1", future=fut)

        await engine.put_event(event=event)

        with pytest.raises(ConnectionError, match="Event queue full"):
            await fut

    @pytest.mark.asyncio
    async def test_put_event_queue_full_user_event_rejected_invalid_state(
        self, engine: WebTransportEngine, mocker: MockerFixture
    ) -> None:
        engine._config.max_event_queue_size = 1
        engine._event_queue = asyncio.Queue(maxsize=1)
        engine._event_queue.put_nowait(TransportQuicTimerFired())

        mock_fut = mocker.Mock(spec=asyncio.Future)
        mock_fut.done.return_value = False
        mock_fut.set_exception.side_effect = asyncio.InvalidStateError()

        event = UserSendDatagram(data=b"test", session_id="s1", future=mock_fut)
        await engine.put_event(event=event)

        mock_fut.set_exception.assert_called()

    @pytest.mark.asyncio
    async def test_put_event_future_race_condition(self, engine: WebTransportEngine) -> None:
        await engine.stop_driver_loop()

        mock_fut = Mock(spec=asyncio.Future)
        mock_fut.done.return_value = False
        mock_fut.set_exception.side_effect = asyncio.InvalidStateError()

        event = UserCreateSession(future=mock_fut, path="/", headers={})
        await engine.put_event(event=event)

        mock_fut.set_exception.assert_called()

    @pytest.mark.asyncio
    async def test_put_event_engine_not_running_future_done(self, engine: WebTransportEngine) -> None:
        await engine.stop_driver_loop()

        mock_fut = Mock(spec=asyncio.Future)
        mock_fut.done.return_value = True

        event = UserCreateSession(future=mock_fut, path="/", headers={})
        await engine.put_event(event=event)

        mock_fut.set_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_put_event_stopped_done_future(self, engine: WebTransportEngine) -> None:
        await engine.stop_driver_loop()

        fut: asyncio.Future[Any] = asyncio.Future()
        fut.cancel()
        event = UserCreateSession(future=fut, path="/", headers={})

        await engine.put_event(event=event)

    @pytest.mark.asyncio
    async def test_put_event_stopped_protocol_event(
        self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture
    ) -> None:
        await engine.stop_driver_loop()
        event = TransportQuicTimerFired()
        await engine.put_event(event=event)
        assert "Engine not running, discarding event: TransportQuicTimerFired" in caplog.text

    @pytest.mark.asyncio
    async def test_put_event_stopped_user_event(self, engine: WebTransportEngine) -> None:
        await engine.stop_driver_loop()

        fut: asyncio.Future[Any] = asyncio.Future()
        event = UserCreateSession(future=fut, path="/", headers={})

        await engine.put_event(event=event)

        with pytest.raises(ConnectionError, match="Engine is not running"):
            await fut

    @pytest.mark.asyncio
    async def test_put_event_stopped_user_event_invalid_state(
        self, engine: WebTransportEngine, mocker: MockerFixture
    ) -> None:
        await engine.stop_driver_loop()

        mock_fut = mocker.Mock(spec=asyncio.Future)
        mock_fut.done.return_value = False
        mock_fut.set_exception.side_effect = asyncio.InvalidStateError()

        event = UserCreateSession(future=mock_fut, path="/", headers={})
        await engine.put_event(event=event)

        mock_fut.set_exception.assert_called()

    @pytest.mark.asyncio
    async def test_server_handshake_completed(
        self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any, mocker: MockerFixture
    ) -> None:
        engine = WebTransportEngine(
            connection_id="server-conn",
            config=mock_config,
            is_client=False,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        engine._h3_engine = mocker.Mock()
        cast(Mock, engine._h3_engine).initialize_connection.return_value = b"settings"

        engine.start_driver_loop()

        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.01)

        assert engine._state.connection_state == ConnectionState.CONNECTED
        mock_notify_callback.assert_called_with(
            EmitConnectionEvent(event_type=EventType.CONNECTION_ESTABLISHED, data={"connection_id": "server-conn"})
        )

        await engine.stop_driver_loop()

    @pytest.mark.asyncio
    async def test_server_mode_immediate_actions(
        self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any
    ) -> None:
        engine = WebTransportEngine(
            connection_id="s1",
            config=mock_config,
            is_client=False,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        engine._connection_processor = Mock()
        engine._connection_processor.handle_create_session.return_value = []
        engine._session_processor = Mock()
        engine._session_processor.handle_create_stream.return_value = []

        engine.start_driver_loop()

        engine._state.connection_state = ConnectionState.CONNECTING

        fut1: asyncio.Future[Any] = asyncio.Future()
        await engine.put_event(event=UserCreateSession(future=fut1, path="/", headers={}))
        await asyncio.sleep(delay=0.01)
        assert len(engine._pending_user_actions) == 0
        engine._connection_processor.handle_create_session.assert_called_once()

        fut2: asyncio.Future[Any] = asyncio.Future()
        await engine.put_event(event=UserCreateStream(session_id="s", is_unidirectional=True, future=fut2))
        await asyncio.sleep(delay=0.01)
        assert len(engine._pending_user_actions) == 0
        engine._session_processor.handle_create_stream.assert_called_once()

        await engine.stop_driver_loop()

    @pytest.mark.asyncio
    async def test_settings_received_updates_state(self, engine: WebTransportEngine) -> None:
        from pywebtransport import constants

        settings = {
            constants.SETTINGS_WT_INITIAL_MAX_DATA: 1000,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI: 10,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI: 5,
        }

        await engine.put_event(event=SettingsReceived(settings=settings))
        await asyncio.sleep(delay=0.01)

        assert engine._state.peer_initial_max_data == 1000
        assert engine._state.peer_initial_max_streams_bidi == 10
        assert engine._state.peer_initial_max_streams_uni == 5

    @pytest.mark.asyncio
    async def test_transport_datagram_frame_received(self, engine: WebTransportEngine) -> None:
        event = TransportDatagramFrameReceived(data=b"test")
        mock_h3 = cast(Mock, engine._h3_engine)
        await engine.put_event(event=event)
        await asyncio.sleep(delay=0.01)
        mock_h3.handle_transport_event.assert_called_with(event=event, state=engine._state)

    @pytest.mark.asyncio
    async def test_transport_events_delegation(self, engine: WebTransportEngine) -> None:
        events = [
            TransportQuicParametersReceived(remote_max_datagram_frame_size=1024),
            TransportQuicTimerFired(),
            TransportStreamReset(stream_id=1, error_code=0),
            CapsuleReceived(capsule_type=1, capsule_data=b"", stream_id=0),
            ConnectStreamClosed(stream_id=0),
            GoawayReceived(),
        ]

        for ev in events:
            await engine.put_event(event=ev)
            await asyncio.sleep(delay=0.01)

        cast(Mock, engine._connection_processor).handle_transport_parameters_received.assert_called()
        cast(Mock, engine._stream_processor).handle_transport_stream_reset.assert_called()
        cast(Mock, engine._session_processor).handle_capsule_received.assert_called()
        cast(Mock, engine._session_processor).handle_connect_stream_closed.assert_called()
        cast(Mock, engine._connection_processor).handle_goaway_received.assert_called()

    @pytest.mark.asyncio
    async def test_transport_handshake_completed_server_flow(
        self, mock_config: ClientConfig, mock_handler: Any, mock_notify_callback: Any, mocker: MockerFixture
    ) -> None:
        engine = WebTransportEngine(
            connection_id="srv",
            config=mock_config,
            is_client=False,
            protocol_handler=mock_handler,
            owner_notify_callback=mock_notify_callback,
        )
        engine._h3_engine = mocker.Mock()
        cast(Mock, engine._h3_engine).initialize_connection.return_value = b"settings"

        engine.start_driver_loop()

        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.05)

        assert engine._state.connection_state == ConnectionState.CONNECTED
        mock_handler.send_stream_data.assert_called()

        await engine.stop_driver_loop()

    @pytest.mark.asyncio
    async def test_transport_timer_fired_generation(self, engine: WebTransportEngine) -> None:
        await engine.put_event(event=TransportQuicTimerFired())
        await asyncio.sleep(delay=0.01)

        handler = engine._protocol_handler()
        assert handler is not None
        cast(Mock, handler.handle_timer_now).assert_called()
        cast(Mock, handler.schedule_timer_now).assert_called()

    @pytest.mark.asyncio
    async def test_unhandled_event(self, engine: WebTransportEngine, caplog: pytest.LogCaptureFixture) -> None:
        class WeirdEvent(ProtocolEvent):
            pass

        weird_event = cast(ProtocolEvent, WeirdEvent())

        await engine.put_event(event=weird_event)
        await asyncio.sleep(delay=0.01)
        assert "Unhandled event type" in caplog.text

    @pytest.mark.asyncio
    async def test_user_events_delegation(self, engine: WebTransportEngine) -> None:
        events: list[ProtocolEvent] = [
            UserAcceptSession(session_id="s1", future=asyncio.Future()),
            UserCloseSession(session_id="s1", future=asyncio.Future(), error_code=0, reason=""),
            UserConnectionGracefulClose(future=asyncio.Future()),
            UserGetConnectionDiagnostics(future=asyncio.Future()),
            UserGetSessionDiagnostics(session_id="s1", future=asyncio.Future()),
            UserGetStreamDiagnostics(stream_id=1, future=asyncio.Future()),
            UserGrantDataCredit(session_id="s1", max_data=100, future=asyncio.Future()),
            UserGrantStreamsCredit(session_id="s1", max_streams=1, is_unidirectional=True, future=asyncio.Future()),
            UserRejectSession(session_id="s1", status_code=400, future=asyncio.Future()),
            UserResetStream(stream_id=1, error_code=0, future=asyncio.Future()),
            UserSendDatagram(session_id="s1", data=b"", future=asyncio.Future()),
            UserSendStreamData(stream_id=1, data=b"", end_stream=False, future=asyncio.Future()),
            UserStopStream(stream_id=1, error_code=0, future=asyncio.Future()),
            UserStreamRead(stream_id=1, max_bytes=10, future=asyncio.Future()),
        ]
        for ev in events:
            await engine.put_event(event=ev)
            await asyncio.sleep(delay=0.01)

        cast(Mock, engine._session_processor).handle_accept_session.assert_called()
        cast(Mock, engine._session_processor).handle_close_session.assert_called()
        cast(Mock, engine._connection_processor).handle_graceful_close.assert_called()
        cast(Mock, engine._connection_processor).handle_get_connection_diagnostics.assert_called()
        cast(Mock, engine._session_processor).handle_get_session_diagnostics.assert_called()
        cast(Mock, engine._stream_processor).handle_get_stream_diagnostics.assert_called()
        cast(Mock, engine._session_processor).handle_grant_data_credit.assert_called()
        cast(Mock, engine._session_processor).handle_grant_streams_credit.assert_called()
        cast(Mock, engine._session_processor).handle_reject_session.assert_called()
        cast(Mock, engine._stream_processor).handle_reset_stream.assert_called()
        cast(Mock, engine._session_processor).handle_send_datagram.assert_called()
        cast(Mock, engine._stream_processor).handle_send_stream_data.assert_called()
        cast(Mock, engine._stream_processor).handle_stop_stream.assert_called()
        cast(Mock, engine._stream_processor).handle_stream_read.assert_called()

    @pytest.mark.asyncio
    async def test_webtransport_stream_data_received(self, engine: WebTransportEngine) -> None:
        ev = WebTransportStreamDataReceived(stream_id=1, data=b"d", stream_ended=False, control_stream_id=0)
        await engine.put_event(event=ev)
        await asyncio.sleep(delay=0.01)
        cast(Mock, engine._stream_processor).handle_webtransport_stream_data.assert_called_once()


class TestUserActionBuffering:

    @pytest.mark.asyncio
    async def test_user_create_session_buffered_when_connecting(self, engine: WebTransportEngine) -> None:
        assert engine._state.connection_state == ConnectionState.CONNECTING
        future: asyncio.Future[Any] = asyncio.Future()
        event = UserCreateSession(future=future, path="/", headers={})

        await engine.put_event(event=event)
        await asyncio.sleep(delay=0.01)

        conn_proc_mock = cast(Mock, engine._connection_processor)
        conn_proc_mock.handle_create_session.assert_not_called()

        assert len(engine._pending_user_actions) == 1

        engine._state.peer_settings_received = True
        engine._state.handshake_complete = True
        cast(Mock, engine._h3_engine).initialize_connection.return_value = b""

        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.01)

        current_state: Any = engine._state.connection_state
        assert current_state == ConnectionState.CONNECTED
        assert len(engine._pending_user_actions) == 0
        conn_proc_mock.handle_create_session.assert_called_once_with(event=event, state=engine._state)

    @pytest.mark.asyncio
    async def test_user_create_stream_buffered(self, engine: WebTransportEngine) -> None:
        assert engine._state.connection_state == ConnectionState.CONNECTING
        future: asyncio.Future[Any] = asyncio.Future()
        event = UserCreateStream(session_id="s1", is_unidirectional=True, future=future)

        await engine.put_event(event=event)
        await asyncio.sleep(delay=0.01)

        session_proc_mock = cast(Mock, engine._session_processor)
        session_proc_mock.handle_create_stream.assert_not_called()
        assert len(engine._pending_user_actions) == 1

        engine._state.peer_settings_received = True
        engine._state.handshake_complete = True
        cast(Mock, engine._h3_engine).initialize_connection.return_value = b""

        await engine.put_event(event=TransportHandshakeCompleted())
        await asyncio.sleep(delay=0.01)

        assert len(engine._pending_user_actions) == 0
        session_proc_mock.handle_create_stream.assert_called_once()
