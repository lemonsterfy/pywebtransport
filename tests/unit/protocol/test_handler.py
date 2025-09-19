"""Unit tests for the pywebtransport.protocol.handler module."""

import asyncio
import logging
from typing import cast
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from aioquic.buffer import Buffer, encode_uint_var
from aioquic.quic.connection import QuicConnection, QuicConnectionState
from aioquic.quic.events import QuicEvent, StreamReset
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    ConnectionError,
    ConnectionState,
    Event,
    EventType,
    FlowControlError,
    ProtocolError,
    ServerConfig,
    SessionState,
    StreamDirection,
    StreamState,
    TimeoutError,
    constants,
)
from pywebtransport.connection import WebTransportConnection
from pywebtransport.constants import ErrorCodes
from pywebtransport.protocol.events import (
    CapsuleReceived,
    DatagramReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.protocol.h3_engine import WebTransportH3Engine
from pywebtransport.protocol.handler import WebTransportProtocolHandler
from pywebtransport.protocol.session_info import StreamInfo, WebTransportSessionInfo


@pytest.fixture
def client_config() -> ClientConfig:
    return ClientConfig.create()


@pytest.fixture
async def handler(
    mock_quic: MagicMock,
    mock_connection: MagicMock,
    mock_h3_engine: MagicMock,
    mock_utils: dict[str, MagicMock],
) -> WebTransportProtocolHandler:
    h = WebTransportProtocolHandler(quic_connection=mock_quic, is_client=True, connection=mock_connection)
    h.connection_established()
    if h._cleanup_pending_events_task:
        h._cleanup_pending_events_task.cancel()
        try:
            await h._cleanup_pending_events_task
        except asyncio.CancelledError:
            pass

    async def dummy_coro() -> None:
        pass

    task = asyncio.create_task(dummy_coro())
    h._cleanup_pending_events_task = task
    return h


@pytest.fixture
def mock_connection(mocker: MockerFixture, client_config: ClientConfig) -> MagicMock:
    mock = mocker.create_autospec(WebTransportConnection, instance=True)
    mock.config = client_config
    return cast(MagicMock, mock)


@pytest.fixture
def mock_h3_engine(mocker: MockerFixture) -> MagicMock:
    mock_engine_instance = mocker.create_autospec(WebTransportH3Engine, instance=True)
    _ = mocker.patch(
        "pywebtransport.protocol.handler.WebTransportH3Engine",
        return_value=mock_engine_instance,
    )
    mock_engine_instance.on = MagicMock()
    mock_engine_instance.off = MagicMock()
    return cast(MagicMock, mock_engine_instance)


@pytest.fixture
def mock_quic(mocker: MockerFixture) -> MagicMock:
    mock = mocker.create_autospec(QuicConnection, instance=True)
    mock.configuration = MagicMock()
    mock.configuration.server_name = "test.server"
    mock._streams = {}
    mock._quic_logger = None
    mock._state = QuicConnectionState.CONNECTED
    return cast(MagicMock, mock)


@pytest.fixture
def mock_utils(mocker: MockerFixture) -> dict[str, MagicMock]:
    return {
        "generate_session_id": mocker.patch(
            "pywebtransport.protocol.handler.generate_session_id",
            return_value="session-1234",
        ),
        "get_timestamp": mocker.patch("pywebtransport.protocol.handler.get_timestamp", return_value=1234567890.0),
    }


@pytest.fixture
def server_config(mocker: MockerFixture) -> ServerConfig:
    mock_path = mocker.patch("pywebtransport.config.Path")
    mock_path.return_value.exists.return_value = True
    return ServerConfig.create(certfile="dummy.crt", keyfile="dummy.key")


@pytest.mark.asyncio
class TestCapsuleHandling:
    @pytest.fixture
    async def handler_with_session(self, handler: WebTransportProtocolHandler) -> WebTransportProtocolHandler:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info
        handler._session_control_streams[0] = "session-1234"
        return handler

    async def test_on_capsule_received_close_session(self, handler_with_session: WebTransportProtocolHandler) -> None:
        buf = Buffer(capacity=1024)
        buf.push_uint32(42)
        buf.push_bytes("Bye".encode("utf-8"))
        payload = buf.data
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.CLOSE_WEBTRANSPORT_SESSION_TYPE,
            capsule_data=payload,
        )
        mock_handler: AsyncMock = AsyncMock()
        handler_with_session.on(event_type=EventType.SESSION_CLOSED, handler=mock_handler)

        await handler_with_session._on_capsule_received(event)

        assert handler_with_session.get_session_info(session_id="session-1234") is None
        mock_handler.assert_called_once()
        emitted_event = mock_handler.call_args.args[0]
        assert emitted_event.data["code"] == 42
        assert emitted_event.data["reason"] == "Bye"

    async def test_on_capsule_received_drain_session(self, handler_with_session: WebTransportProtocolHandler) -> None:
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.DRAIN_WEBTRANSPORT_SESSION_TYPE,
            capsule_data=b"",
        )
        mock_handler: AsyncMock = AsyncMock()
        handler_with_session.on(event_type=EventType.SESSION_DRAINING, handler=mock_handler)

        await handler_with_session._on_capsule_received(event)

        mock_handler.assert_called_once()

    @pytest.mark.parametrize(
        "capsule_type, payload_data, expected_event, check_attr, new_value",
        [
            (
                constants.WT_MAX_DATA_TYPE,
                encode_uint_var(9000),
                EventType.SESSION_MAX_DATA_UPDATED,
                "peer_max_data",
                9000,
            ),
            (
                constants.WT_MAX_STREAMS_BIDI_TYPE,
                encode_uint_var(200),
                EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                "peer_max_streams_bidi",
                200,
            ),
            (
                constants.WT_MAX_STREAMS_UNI_TYPE,
                encode_uint_var(300),
                EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                "peer_max_streams_uni",
                300,
            ),
        ],
    )
    async def test_on_capsule_received_flow_control(
        self,
        handler_with_session: WebTransportProtocolHandler,
        capsule_type: int,
        payload_data: bytes,
        expected_event: EventType,
        check_attr: str,
        new_value: int,
    ) -> None:
        event = CapsuleReceived(stream_id=0, capsule_type=capsule_type, capsule_data=payload_data)
        session_info = handler_with_session.get_session_info(session_id="session-1234")
        assert session_info is not None
        mock_handler: AsyncMock = AsyncMock()
        handler_with_session.on(event_type=expected_event, handler=mock_handler)

        await handler_with_session._on_capsule_received(event)

        assert getattr(session_info, check_attr) == new_value
        mock_handler.assert_called_once()
        emitted_event = mock_handler.call_args.args[0]
        assert emitted_event.data["session_id"] == "session-1234"

    @pytest.mark.parametrize(
        "capsule_type, initial_value_attr, new_value",
        [
            (constants.WT_MAX_DATA_TYPE, "peer_max_data", 50),
            (constants.WT_MAX_STREAMS_BIDI_TYPE, "peer_max_streams_bidi", 5),
            (constants.WT_MAX_STREAMS_UNI_TYPE, "peer_max_streams_uni", 5),
        ],
    )
    async def test_on_capsule_received_flow_control_decrease_error(
        self,
        handler_with_session: WebTransportProtocolHandler,
        capsule_type: int,
        initial_value_attr: str,
        new_value: int,
    ) -> None:
        session_info = handler_with_session.get_session_info(session_id="session-1234")
        assert session_info is not None
        setattr(session_info, initial_value_attr, 100)
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=capsule_type,
            capsule_data=encode_uint_var(new_value),
        )

        with pytest.raises(ProtocolError, match="Flow control limit decreased"):
            await handler_with_session._on_capsule_received(event)

    @pytest.mark.parametrize(
        "capsule_type, update_event_type, initial_value_attr",
        [
            (constants.WT_MAX_DATA_TYPE, EventType.SESSION_MAX_DATA_UPDATED, "peer_max_data"),
            (
                constants.WT_MAX_STREAMS_BIDI_TYPE,
                EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
                "peer_max_streams_bidi",
            ),
            (
                constants.WT_MAX_STREAMS_UNI_TYPE,
                EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
                "peer_max_streams_uni",
            ),
        ],
    )
    async def test_on_capsule_received_flow_control_equal_limit(
        self,
        handler_with_session: WebTransportProtocolHandler,
        capsule_type: int,
        update_event_type: EventType,
        initial_value_attr: str,
    ) -> None:
        session_info = handler_with_session.get_session_info(session_id="session-1234")
        assert session_info is not None
        initial_value = 100
        setattr(session_info, initial_value_attr, initial_value)
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=capsule_type,
            capsule_data=encode_uint_var(initial_value),
        )
        update_spy = AsyncMock()
        handler_with_session.on(event_type=update_event_type, handler=update_spy)

        await handler_with_session._on_capsule_received(event)

        assert getattr(session_info, initial_value_attr) == initial_value
        update_spy.assert_not_called()

    async def test_on_capsule_received_for_unknown_session(self, handler: WebTransportProtocolHandler) -> None:
        event = CapsuleReceived(stream_id=999, capsule_type=constants.WT_MAX_DATA_TYPE, capsule_data=b"\x01")

        await handler._on_capsule_received(event)

    async def test_on_capsule_received_parse_error(
        self,
        handler_with_session: WebTransportProtocolHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.WT_MAX_DATA_TYPE,
            capsule_data=b"\xff",
        )

        with caplog.at_level(logging.WARNING):
            await handler_with_session._on_capsule_received(event)

        assert "Could not parse flow control capsule" in caplog.text

    async def test_on_capsule_received_unicode_error(
        self,
        handler_with_session: WebTransportProtocolHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.CLOSE_WEBTRANSPORT_SESSION_TYPE,
            capsule_data=b"\x00\x00\x00\x01\xff",
        )
        closed_spy = AsyncMock()
        handler_with_session.on(event_type=EventType.SESSION_CLOSED, handler=closed_spy)
        with caplog.at_level(logging.WARNING):
            await handler_with_session._on_capsule_received(event)
        assert "invalid UTF-8 reason string" in caplog.text
        closed_spy.assert_called_once()
        assert closed_spy.call_args.args[0].data["reason"] == "\ufffd"


@pytest.mark.asyncio
class TestFlowControlUpdates:
    @pytest.fixture
    async def handler_with_session(self, handler: WebTransportProtocolHandler) -> WebTransportProtocolHandler:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info
        handler._session_control_streams[0] = "session-1234"
        return handler

    async def test_update_local_flow_control_no_session(self, handler: WebTransportProtocolHandler) -> None:
        await handler._update_local_flow_control(session_id="non-existent")

    async def test_update_local_flow_control_sends_nothing_when_not_needed(
        self,
        handler_with_session: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
    ) -> None:
        handler = handler_with_session
        session_info = handler.get_session_info(session_id="session-1234")
        assert session_info is not None
        session_info.local_max_data = handler._config.flow_control_window_size
        session_info.peer_data_sent = 0
        session_info.local_max_streams_bidi = 100
        session_info.peer_streams_bidi_opened = 10
        session_info.local_max_streams_uni = 100
        session_info.peer_streams_uni_opened = 10

        await handler._update_local_flow_control(session_id="session-1234")

        mock_h3_engine.send_capsule.assert_not_called()

    @pytest.mark.parametrize("auto_scale", [True, False])
    async def test_update_local_flow_control_sends_max_data(
        self,
        handler_with_session: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
        auto_scale: bool,
    ) -> None:
        handler = handler_with_session
        handler._config.flow_control_window_size = 1000
        handler._config.flow_control_window_auto_scale = auto_scale
        session_info = handler.get_session_info(session_id="session-1234")
        assert session_info is not None
        session_info.local_max_data = 1000
        session_info.peer_data_sent = 501
        session_info.local_max_streams_bidi = 100
        session_info.local_max_streams_uni = 100

        await handler._update_local_flow_control(session_id="session-1234")

        mock_h3_engine.send_capsule.assert_called_once()
        kwargs = mock_h3_engine.send_capsule.call_args.kwargs
        buf = Buffer(data=kwargs["capsule_data"])
        capsule_type = buf.pull_uint_var()
        _ = buf.pull_uint_var()
        new_limit = buf.pull_uint_var()
        assert capsule_type == constants.WT_MAX_DATA_TYPE
        if auto_scale:
            assert new_limit == 2000
        else:
            assert new_limit == 1501

    @pytest.mark.parametrize("stream_type", ["bidi", "uni"])
    async def test_update_local_flow_control_sends_max_streams(
        self,
        handler_with_session: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
        stream_type: str,
    ) -> None:
        handler = handler_with_session
        session_info = handler.get_session_info(session_id="session-1234")
        assert session_info is not None
        session_info.local_max_data = handler._config.flow_control_window_size
        session_info.peer_data_sent = 0
        if stream_type == "bidi":
            session_info.local_max_streams_bidi = 5
            session_info.peer_streams_bidi_opened = 5
            session_info.local_max_streams_uni = 100
            expected_capsule_type = constants.WT_MAX_STREAMS_BIDI_TYPE
        else:
            session_info.local_max_streams_uni = 5
            session_info.peer_streams_uni_opened = 5
            session_info.local_max_streams_bidi = 100
            expected_capsule_type = constants.WT_MAX_STREAMS_UNI_TYPE

        await handler._update_local_flow_control(session_id="session-1234")

        mock_h3_engine.send_capsule.assert_called_once()
        kwargs = mock_h3_engine.send_capsule.call_args.kwargs
        buf = Buffer(data=kwargs["capsule_data"])
        capsule_type = buf.pull_uint_var()
        assert capsule_type == expected_capsule_type


class TestInitialization:
    def test_create_factory_method(self, mock_quic: MagicMock) -> None:
        handler = WebTransportProtocolHandler.create(quic_connection=mock_quic)
        assert isinstance(handler, WebTransportProtocolHandler)

    def test_init_client_no_connection(self, mock_quic: MagicMock, mock_h3_engine: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, is_client=True, connection=None)

        assert handler._is_client is True
        assert handler.connection is None

    def test_init_server_no_connection(self, mock_quic: MagicMock, mock_h3_engine: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, is_client=False, connection=None)

        assert handler._is_client is False


@pytest.mark.asyncio
class TestStreamStateTransitions:
    @pytest.fixture
    async def handler_with_stream(
        self, handler: WebTransportProtocolHandler
    ) -> tuple[WebTransportProtocolHandler, StreamInfo]:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info
        handler._session_control_streams[0] = "session-1234"
        stream_info = handler._register_stream(
            session_id="session-1234",
            stream_id=4,
            direction=StreamDirection.BIDIRECTIONAL,
        )
        return handler, stream_info

    async def test_receive_end_stream_half_closes(
        self, handler_with_stream: tuple[WebTransportProtocolHandler, StreamInfo]
    ) -> None:
        handler, stream_info = handler_with_stream

        handler._update_stream_state_on_receive_end(stream_id=4)

        assert stream_info.state == StreamState.HALF_CLOSED_REMOTE

    async def test_receive_then_send_end_stream_closes(
        self, handler_with_stream: tuple[WebTransportProtocolHandler, StreamInfo]
    ) -> None:
        handler, stream_info = handler_with_stream

        handler._update_stream_state_on_receive_end(stream_id=4)
        assert stream_info.state == StreamState.HALF_CLOSED_REMOTE

        handler.send_webtransport_stream_data(stream_id=4, data=b"", end_stream=True)
        assert 4 not in handler._streams

    async def test_send_end_stream_half_closes(
        self, handler_with_stream: tuple[WebTransportProtocolHandler, StreamInfo]
    ) -> None:
        handler, stream_info = handler_with_stream

        handler.send_webtransport_stream_data(stream_id=4, data=b"", end_stream=True)

        assert stream_info.state == StreamState.HALF_CLOSED_LOCAL

    async def test_send_then_receive_end_stream_closes(
        self, handler_with_stream: tuple[WebTransportProtocolHandler, StreamInfo]
    ) -> None:
        handler, stream_info = handler_with_stream

        handler.send_webtransport_stream_data(stream_id=4, data=b"", end_stream=True)
        assert stream_info.state == StreamState.HALF_CLOSED_LOCAL

        handler._update_stream_state_on_receive_end(stream_id=4)
        assert 4 not in handler._streams


@pytest.mark.asyncio
class TestWebTransportProtocolHandlerClient:
    @pytest.fixture
    def client_handler(
        self,
        mock_quic: MagicMock,
        mock_connection: MagicMock,
        mock_h3_engine: MagicMock,
        mock_utils: dict[str, MagicMock],
    ) -> WebTransportProtocolHandler:
        return WebTransportProtocolHandler(quic_connection=mock_quic, is_client=True, connection=mock_connection)

    async def test_accept_webtransport_session_raises_on_client(
        self, client_handler: WebTransportProtocolHandler
    ) -> None:
        with pytest.raises(ProtocolError, match="Only servers can accept"):
            client_handler.accept_webtransport_session(stream_id=0, session_id="s-1")

    async def test_close_webtransport_session(
        self, client_handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        client_handler._sessions["session-1234"] = session_info
        mock_session_closed_handler: AsyncMock = AsyncMock()
        client_handler.on(
            event_type=EventType.SESSION_CLOSED,
            handler=mock_session_closed_handler,
        )

        client_handler.close_webtransport_session(session_id="session-1234", code=123, reason="Test")
        await asyncio.sleep(0)

        mock_h3_engine.send_capsule.assert_called_once()
        assert client_handler.get_session_info(session_id="session-1234") is None
        mock_session_closed_handler.assert_called_once()
        emitted_event = mock_session_closed_handler.call_args.args[0]
        assert emitted_event.data["session_id"] == "session-1234"

    async def test_close_webtransport_session_already_closed(
        self, client_handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CLOSED,
            path="/",
            created_at=123.0,
        )
        client_handler._sessions["session-1234"] = session_info

        client_handler.close_webtransport_session(session_id="session-1234")

        mock_h3_engine.send_capsule.assert_not_called()

    async def test_close_webtransport_session_not_found(
        self, client_handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        client_handler.close_webtransport_session(session_id="non-existent")
        mock_h3_engine.send_capsule.assert_not_called()

    async def test_create_webtransport_session_authority_fallback(
        self,
        client_handler: WebTransportProtocolHandler,
        mock_quic: MagicMock,
        mock_h3_engine: MagicMock,
    ) -> None:
        mock_quic.get_next_available_stream_id.return_value = 0
        mock_quic.configuration.server_name = None

        await client_handler.create_webtransport_session(path="/test")

        mock_h3_engine.send_headers.assert_called_once()
        headers = mock_h3_engine.send_headers.call_args.kwargs["headers"]
        assert headers[":authority"] == "localhost"

    async def test_create_webtransport_session_limit_reached(self, client_handler: WebTransportProtocolHandler) -> None:
        client_handler._peer_max_sessions = 0

        with pytest.raises(ConnectionError, match="server's session limit"):
            await client_handler.create_webtransport_session(path="/test")

    async def test_create_webtransport_session_success(
        self,
        client_handler: WebTransportProtocolHandler,
        mock_quic: MagicMock,
        mock_h3_engine: MagicMock,
    ) -> None:
        mock_quic.get_next_available_stream_id.return_value = 0

        session_id, stream_id = await client_handler.create_webtransport_session(path="/test")

        assert session_id == "session-1234"
        assert stream_id == 0
        mock_h3_engine.send_headers.assert_called_once()
        headers = mock_h3_engine.send_headers.call_args.kwargs["headers"]
        assert headers[":method"] == "CONNECT"
        assert headers[":path"] == "/test"
        session_info = client_handler.get_session_info(session_id="session-1234")
        assert session_info is not None
        assert session_info.state == SessionState.CONNECTING

    async def test_establish_session_timeout(
        self, client_handler: WebTransportProtocolHandler, mocker: MockerFixture
    ) -> None:
        client_handler.connection_established()
        mocker.patch.object(client_handler, "wait_for", side_effect=asyncio.TimeoutError)
        mocker.patch.object(
            client_handler,
            "create_webtransport_session",
            return_value=("session-1234", 0),
        )

        with pytest.raises(asyncio.TimeoutError):
            await client_handler.establish_session(path="/", timeout=0.1)

    async def test_handle_session_headers_failure(
        self, client_handler: WebTransportProtocolHandler, mock_quic: MagicMock
    ) -> None:
        mock_quic.get_next_available_stream_id.return_value = 0
        session_id, stream_id = await client_handler.create_webtransport_session(path="/test")
        headers_event = HeadersReceived(stream_id=stream_id, headers={":status": "404"}, stream_ended=True)
        mock_session_closed_handler: AsyncMock = AsyncMock()
        client_handler.on(
            event_type=EventType.SESSION_CLOSED,
            handler=mock_session_closed_handler,
        )

        await client_handler._handle_session_headers(event=headers_event)

        assert client_handler.get_session_info(session_id=session_id) is None
        mock_session_closed_handler.assert_called_once()
        emitted_event = mock_session_closed_handler.call_args.args[0]
        assert emitted_event.data["session_id"] == session_id
        assert "404" in emitted_event.data["reason"]

    async def test_handle_session_headers_inconsistent_state(self, client_handler: WebTransportProtocolHandler) -> None:
        client_handler._session_control_streams[0] = "ghost-session"
        ready_spy = AsyncMock()
        client_handler.on(event_type=EventType.SESSION_READY, handler=ready_spy)
        headers_event = HeadersReceived(stream_id=0, headers={":status": "200"}, stream_ended=False)
        await client_handler._handle_session_headers(event=headers_event)
        ready_spy.assert_not_called()

    async def test_handle_session_headers_success(
        self, client_handler: WebTransportProtocolHandler, mock_quic: MagicMock
    ) -> None:
        mock_quic.get_next_available_stream_id.return_value = 0
        session_id, stream_id = await client_handler.create_webtransport_session(path="/test")
        headers_event = HeadersReceived(stream_id=stream_id, headers={":status": "200"}, stream_ended=False)
        mock_session_ready_handler: AsyncMock = AsyncMock()
        client_handler.on(event_type=EventType.SESSION_READY, handler=mock_session_ready_handler)

        await client_handler._handle_session_headers(event=headers_event)

        session_info = client_handler.get_session_info(session_id=session_id)
        assert session_info is not None
        assert session_info.state == SessionState.CONNECTED
        mock_session_ready_handler.assert_called_once()
        emitted_event = mock_session_ready_handler.call_args.args[0]
        assert emitted_event.data["session_id"] == session_id

    async def test_initialization_client(
        self, client_handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        assert client_handler._is_client is True
        assert client_handler.connection_state == "idle"
        mock_h3_engine.on.assert_has_calls(
            [
                call(
                    event_type=EventType.SETTINGS_RECEIVED,
                    handler=client_handler._on_settings_received,
                ),
                call(
                    event_type=EventType.CAPSULE_RECEIVED,
                    handler=client_handler._capsule_received_handler,
                ),
            ],
            any_order=True,
        )


@pytest.mark.asyncio
class TestWebTransportProtocolHandlerCommon:
    @pytest.fixture
    async def handler_for_close_test(
        self,
        mock_quic: MagicMock,
        mock_connection: MagicMock,
        mock_h3_engine: MagicMock,
        mocker: MockerFixture,
    ) -> tuple[WebTransportProtocolHandler, MagicMock]:
        h = WebTransportProtocolHandler(quic_connection=mock_quic, is_client=True, connection=mock_connection)
        h.connection_established()

        async def dummy_coro() -> None:
            pass

        task = asyncio.create_task(dummy_coro())
        cancel_spy = mocker.spy(task, "cancel")
        h._cleanup_pending_events_task = task
        return h, cancel_spy

    async def test_abort_stream(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_stream = MagicMock()
        mock_stream.sender._reset_error_code = None
        mock_stream.receiver.is_finished = False
        mock_quic._streams[4] = mock_stream
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_send_data_on_stream",
            return_value=True,
        )
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_receive_data_on_stream",
            return_value=True,
        )
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.webtransport_code_to_http_code",
            return_value=0x1337,
        )

        handler.abort_stream(stream_id=4, error_code=ErrorCodes.APP_INVALID_REQUEST)

        mock_quic.reset_stream.assert_called_with(stream_id=4, error_code=0x1337)
        mock_quic.stop_stream.assert_called_with(stream_id=4, error_code=0x1337)

    async def test_abort_stream_already_cleaned_up(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock
    ) -> None:
        handler.abort_stream(stream_id=99, error_code=1)

        mock_quic.reset_stream.assert_not_called()

    async def test_abort_stream_is_idempotent_for_reset(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock
    ) -> None:
        mock_stream = MagicMock()
        mock_stream.sender._reset_error_code = 1
        mock_stream.receiver.is_finished = False
        mock_quic._streams[4] = mock_stream

        handler.abort_stream(stream_id=4, error_code=2)

        mock_quic.reset_stream.assert_not_called()
        mock_quic.stop_stream.assert_called_once()

    async def test_abort_stream_is_idempotent_for_stop(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock
    ) -> None:
        mock_stream = MagicMock()
        mock_stream.sender._reset_error_code = None
        mock_stream.receiver.is_finished = True
        mock_quic._streams[4] = mock_stream

        handler.abort_stream(stream_id=4, error_code=2)

        mock_quic.reset_stream.assert_called_once()
        mock_quic.stop_stream.assert_not_called()

    async def test_abort_stream_quic_layer_failure(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_stream = MagicMock()
        mock_stream.sender._reset_error_code = None
        mock_quic._streams[4] = mock_stream
        mock_quic.reset_stream.side_effect = ValueError("QUIC error")
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_send_data_on_stream",
            return_value=True,
        )

        handler.abort_stream(stream_id=4, error_code=1)

        mock_quic.reset_stream.assert_called_once()

    async def test_abort_stream_with_invalid_code_conversion(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_stream = MagicMock()
        mock_stream.sender._reset_error_code = None
        mock_stream.receiver.is_finished = False
        mock_quic._streams[4] = mock_stream
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_send_data_on_stream",
            return_value=True,
        )
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.webtransport_code_to_http_code",
            side_effect=ValueError,
        )

        handler.abort_stream(stream_id=4, error_code=999)

        mock_quic.reset_stream.assert_called_with(stream_id=4, error_code=ErrorCodes.INTERNAL_ERROR)

    async def test_cleanup_pending_events_loop(
        self,
        mock_quic: MagicMock,
        mock_connection: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        timestamps = [1000.0, 1004.0]
        mocker.patch("pywebtransport.protocol.handler.get_timestamp", side_effect=timestamps)
        mocker.patch("asyncio.sleep", side_effect=StopAsyncIteration)
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, is_client=True, connection=mock_connection)
        handler._config.pending_event_ttl = 5.0
        abort_spy = mocker.spy(handler, "abort_stream")
        stale_event = WebTransportStreamDataReceived(stream_id=4, session_id=1, data=b"", stream_ended=True)
        fresh_event = DatagramReceived(stream_id=2, data=b"fresh")
        handler._pending_events[1] = [(timestamps[0] - 10, stale_event)]
        handler._pending_events[2] = [(timestamps[0], fresh_event)]
        handler._pending_events_count = 2

        with pytest.raises(StopAsyncIteration):
            await handler._cleanup_pending_events_loop()

        assert 1 not in handler._pending_events
        assert 2 in handler._pending_events
        abort_spy.assert_called_once_with(stream_id=4, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)

    async def test_close_cancels_tasks_and_clears_handlers(
        self,
        handler_for_close_test: tuple[WebTransportProtocolHandler, MagicMock],
        mock_h3_engine: MagicMock,
    ) -> None:
        handler, cancel_spy = handler_for_close_test

        await handler.close()

        cancel_spy.assert_called_once()
        mock_h3_engine.off.assert_called()

    async def test_close_noop_if_already_closed(
        self, handler_for_close_test: tuple[WebTransportProtocolHandler, MagicMock]
    ) -> None:
        handler, cancel_spy = handler_for_close_test
        handler._connection_state = ConnectionState.CLOSED

        await handler.close()

        cancel_spy.assert_not_called()

    async def test_connection_established_when_already_connected(self, handler: WebTransportProtocolHandler) -> None:
        handler._connection_state = ConnectionState.CONNECTED
        handler.connection_established()

    async def test_connection_property_dead_ref(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        conn = WebTransportConnection(config=client_config)
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, is_client=True, connection=conn)

        assert handler.connection is conn
        del conn
        assert handler.connection is None

    @pytest.mark.parametrize(
        "is_unidirectional, expected_capsule_type",
        [
            (False, constants.WT_STREAMS_BLOCKED_BIDI_TYPE),
            (True, constants.WT_STREAMS_BLOCKED_UNI_TYPE),
        ],
    )
    async def test_create_stream_flow_control_error(
        self,
        handler: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
        is_unidirectional: bool,
        expected_capsule_type: int,
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        session_info.peer_max_streams_uni = 0
        session_info.peer_max_streams_bidi = 0
        handler._sessions["session-1234"] = session_info
        handler._session_control_streams[0] = "session-1234"

        with pytest.raises(FlowControlError):
            handler.create_webtransport_stream(session_id="session-1234", is_unidirectional=is_unidirectional)

        mock_h3_engine.send_capsule.assert_called_once()
        kwargs = mock_h3_engine.send_capsule.call_args.kwargs
        buf = Buffer(data=kwargs["capsule_data"])
        capsule_type = buf.pull_uint_var()
        assert capsule_type == expected_capsule_type

    async def test_create_stream_for_non_existent_session(self, handler: WebTransportProtocolHandler) -> None:
        with pytest.raises(ProtocolError, match="not found or not ready"):
            handler.create_webtransport_stream(session_id="non-existent")

    async def test_create_stream_session_not_ready(self, handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTING,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info

        with pytest.raises(ProtocolError, match="not found or not ready"):
            handler.create_webtransport_stream(session_id="session-1234")

    async def test_create_stream_success(self, handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        session_info.peer_max_streams_bidi = 100
        handler._sessions["session-1234"] = session_info
        handler._session_control_streams[0] = "session-1234"
        mock_h3_engine.create_webtransport_stream.return_value = 4

        stream_id = handler.create_webtransport_stream(session_id="session-1234", is_unidirectional=False)

        assert stream_id == 4
        mock_h3_engine.create_webtransport_stream.assert_called_with(session_id=0, is_unidirectional=False)
        assert stream_id in handler._streams
        stream_info = handler._streams[stream_id]
        assert stream_info.direction == StreamDirection.BIDIRECTIONAL

    async def test_establish_session_not_connected(self, handler: WebTransportProtocolHandler) -> None:
        handler._connection_state = ConnectionState.CLOSED

        with pytest.raises(ConnectionError, match="Protocol not connected"):
            await handler.establish_session(path="/")

    async def test_get_all_sessions(self, handler: WebTransportProtocolHandler) -> None:
        handler._sessions["session-1"] = WebTransportSessionInfo(
            session_id="session-1",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/a",
            created_at=1,
        )
        handler._sessions["session-2"] = WebTransportSessionInfo(
            session_id="session-2",
            stream_id=4,
            state=SessionState.CONNECTED,
            path="/b",
            created_at=2,
        )

        sessions = handler.get_all_sessions()

        assert len(sessions) == 2
        assert {s.session_id for s in sessions} == {"session-1", "session-2"}

    @pytest.mark.parametrize(
        "state, errors, connected_at, expected_status",
        [
            (ConnectionState.CONNECTED, 0, 123.0, "healthy"),
            (ConnectionState.CLOSED, 0, 123.0, "unhealthy"),
            (ConnectionState.CONNECTED, 2, 123.0, "degraded"),
            (ConnectionState.IDLE, 0, None, "unhealthy"),
        ],
    )
    async def test_get_health_status(
        self,
        handler: WebTransportProtocolHandler,
        state: ConnectionState,
        errors: int,
        connected_at: float | None,
        expected_status: str,
    ) -> None:
        handler._connection_state = state
        handler._stats["errors"] = errors
        handler._stats["sessions_created"] = 10
        handler._stats["connected_at"] = connected_at

        status = handler.get_health_status()

        assert status["status"] == expected_status
        if connected_at is None:
            assert status["uptime"] == 0.0

    async def test_get_health_status_no_sessions_created(self, handler: WebTransportProtocolHandler) -> None:
        handler._stats["sessions_created"] = 0
        status = handler.get_health_status()
        assert status["error_rate"] == 0.0

    async def test_handle_datagram_pending_global_buffer_full(
        self,
        handler: WebTransportProtocolHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        handler._config.max_total_pending_events = 0

        with caplog.at_level(logging.WARNING):
            event = DatagramReceived(stream_id=0, data=b"hello")
            await handler._handle_datagram_received(event=event)

        assert "Global pending event buffer full" in caplog.text
        assert len(handler._pending_events) == 0

    async def test_handle_datagram_pending_session_buffer_full(
        self,
        handler: WebTransportProtocolHandler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        handler._config.max_pending_events_per_session = 0

        with caplog.at_level(logging.WARNING):
            event = DatagramReceived(stream_id=0, data=b"hello")
            await handler._handle_datagram_received(event=event)

        assert "Pending event buffer full for session stream 0" in caplog.text
        assert not handler._pending_events.get(0)

    async def test_handle_h3_event_ignores_unknown_event(
        self, handler: WebTransportProtocolHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        class UnknownH3Event(H3Event):
            pass

        with caplog.at_level(logging.DEBUG):
            await handler._handle_h3_event(h3_event=UnknownH3Event())

        assert "Ignoring unhandled H3 event" in caplog.text

    async def test_handle_quic_event_when_closed(self, handler: WebTransportProtocolHandler) -> None:
        await handler.close()
        await handler.handle_quic_event(event=QuicEvent())

    async def test_handle_stream_data_for_connecting_session_is_not_buffered(
        self, handler: WebTransportProtocolHandler
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTING,
            path="/",
            created_at=123.0,
        )
        handler._register_session(session_id="session-1234", session_info=session_info)
        event = WebTransportStreamDataReceived(stream_id=4, session_id=0, data=b"hello", stream_ended=True)

        await handler._handle_webtransport_stream_data(event=event)

        assert not handler._pending_events

    async def test_handle_stream_data_pending_global_buffer_full(
        self,
        handler: WebTransportProtocolHandler,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        handler._config.max_total_pending_events = 0
        abort_spy = mocker.spy(handler, "abort_stream")

        with caplog.at_level(logging.WARNING):
            event = WebTransportStreamDataReceived(stream_id=4, session_id=0, data=b"hello", stream_ended=True)
            await handler._handle_webtransport_stream_data(event=event)

        assert "Global pending event buffer full" in caplog.text
        abort_spy.assert_called_with(stream_id=4, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)

    async def test_handle_stream_data_pending_session_buffer_full(
        self,
        handler: WebTransportProtocolHandler,
        caplog: pytest.LogCaptureFixture,
        mocker: MockerFixture,
    ) -> None:
        handler._config.max_pending_events_per_session = 0
        abort_spy = mocker.spy(handler, "abort_stream")

        with caplog.at_level(logging.WARNING):
            event = WebTransportStreamDataReceived(stream_id=4, session_id=0, data=b"hello", stream_ended=True)
            await handler._handle_webtransport_stream_data(event=event)

        assert "Pending event buffer full" in caplog.text
        abort_spy.assert_called_with(stream_id=4, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED)

    async def test_handle_stream_reset_on_control_stream(self, handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info
        handler._session_control_streams[0] = "session-1234"
        reset_event = StreamReset(stream_id=0, error_code=123)
        mock_session_closed_handler: AsyncMock = AsyncMock()
        handler.on(
            event_type=EventType.SESSION_CLOSED,
            handler=mock_session_closed_handler,
        )

        await handler.handle_quic_event(event=reset_event)

        assert handler.get_session_info(session_id="session-1234") is None
        mock_session_closed_handler.assert_called_once()
        emitted_event = mock_session_closed_handler.call_args.args[0]
        assert emitted_event.data["session_id"] == "session-1234"
        assert emitted_event.data["reason"] == "Control stream reset"

    @pytest.mark.parametrize("settings_data", [{}, {"settings": None}])
    async def test_on_settings_received_no_settings(
        self, handler: WebTransportProtocolHandler, settings_data: dict
    ) -> None:
        event = Event(type=EventType.SETTINGS_RECEIVED, data=settings_data)

        await handler._on_settings_received(event)
        assert handler._peer_max_sessions is None

    async def test_on_settings_received_no_connection(self, mock_quic: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic)
        handler._connection_ref = None
        event = Event(type=EventType.SETTINGS_RECEIVED, data={"settings": {}})
        await handler._on_settings_received(event)

    async def test_on_settings_received_updates_peer_limits(self, handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="pre-existing",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["pre-existing"] = session_info
        settings = {
            constants.SETTINGS_WT_MAX_SESSIONS: 50,
            constants.SETTINGS_WT_INITIAL_MAX_DATA: 10000,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI: 10,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI: 20,
        }
        event = Event(type=EventType.SETTINGS_RECEIVED, data={"settings": settings})

        await handler._on_settings_received(event)

        assert handler._peer_max_sessions == 50
        assert handler._peer_initial_max_data == 10000
        assert handler._peer_initial_max_streams_bidi == 10
        assert handler._peer_initial_max_streams_uni == 20
        assert session_info.peer_max_data == 10000
        assert session_info.peer_max_streams_bidi == 10

    async def test_pending_events_buffering_and_processing(self, handler: WebTransportProtocolHandler) -> None:
        stream_data_event = WebTransportStreamDataReceived(stream_id=4, session_id=0, data=b"hello", stream_ended=True)
        datagram_event = DatagramReceived(stream_id=0, data=b"world")

        await handler._handle_webtransport_stream_data(event=stream_data_event)
        await handler._handle_datagram_received(event=datagram_event)

        assert not handler._streams
        assert len(handler._pending_events[0]) == 2

        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTING,
            path="/",
            created_at=123.0,
        )
        handler._register_session(session_id="session-1234", session_info=session_info)
        mock_stream_opened_handler: AsyncMock = AsyncMock()
        mock_datagram_handler: AsyncMock = AsyncMock()
        handler.on(event_type=EventType.STREAM_OPENED, handler=mock_stream_opened_handler)
        handler.on(event_type=EventType.DATAGRAM_RECEIVED, handler=mock_datagram_handler)

        handler._process_pending_events(connect_stream_id=0)
        await asyncio.sleep(0)

        assert not handler._pending_events
        assert 4 in handler._streams
        mock_stream_opened_handler.assert_called_once()
        mock_datagram_handler.assert_called_once()
        emitted_event = mock_stream_opened_handler.call_args.args[0]
        assert emitted_event.data["stream_id"] == 4
        assert emitted_event.data["initial_payload"]["data"] == b"hello"
        emitted_event_datagram = mock_datagram_handler.call_args.args[0]
        assert emitted_event_datagram.data["data"] == b"world"

    async def test_process_buffered_events_unknown_event(self, handler: WebTransportProtocolHandler) -> None:
        handler._pending_events[0] = [(123.0, CapsuleReceived(stream_id=0, capsule_type=1, capsule_data=b""))]
        handler._pending_events_count = 1
        handler._process_pending_events(connect_stream_id=0)
        await asyncio.sleep(0)
        assert not handler._pending_events

    async def test_process_pending_events_no_events(self, handler: WebTransportProtocolHandler) -> None:
        handler._process_pending_events(connect_stream_id=99)

    async def test_read_stream_complete_success(self, handler: WebTransportProtocolHandler) -> None:
        async def emit_data() -> None:
            await asyncio.sleep(0.01)
            await handler.emit(event_type="stream_data_received:4", data={"data": b"part1"})
            await handler.emit(
                event_type="stream_data_received:4",
                data={"data": b"part2", "end_stream": True},
            )

        task = asyncio.create_task(handler.read_stream_complete(stream_id=4, timeout=1.0))
        await emit_data()

        result = await task
        assert result == b"part1part2"

    async def test_read_stream_complete_timeout(self, handler: WebTransportProtocolHandler) -> None:
        with pytest.raises(TimeoutError):
            await handler.read_stream_complete(stream_id=4, timeout=0.01)

    async def test_recover_session_failure(self, handler: WebTransportProtocolHandler, mocker: MockerFixture) -> None:
        original_session = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CLOSED,
            path="/recover",
            headers={},
            created_at=123.0,
        )
        handler._sessions["session-1234"] = original_session
        create_mock = mocker.patch.object(
            handler,
            "create_webtransport_session",
            autospec=True,
            side_effect=ConnectionError("Failed to connect"),
        )
        sleep_mock = mocker.patch("asyncio.sleep", new_callable=AsyncMock)

        result = await handler.recover_session(session_id="session-1234", max_retries=2)

        assert result is False
        assert create_mock.call_count == 2
        sleep_mock.assert_called_once_with(1.0)

    async def test_recover_session_generic_exception(
        self, handler: WebTransportProtocolHandler, mocker: MockerFixture
    ) -> None:
        original_session = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CLOSED, path="/", created_at=123.0
        )
        handler._sessions["s1"] = original_session
        mocker.patch.object(handler, "create_webtransport_session", side_effect=RuntimeError("Generic error"))
        result = await handler.recover_session(session_id="s1", max_retries=1)
        assert result is False

    async def test_recover_session_not_found(self, handler: WebTransportProtocolHandler) -> None:
        result = await handler.recover_session(session_id="non-existent")

        assert result is False

    async def test_recover_session_success(self, handler: WebTransportProtocolHandler, mocker: MockerFixture) -> None:
        original_session = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CLOSED,
            path="/recover",
            headers={"x-foo": "bar"},
            created_at=123.0,
        )
        handler._sessions["session-1234"] = original_session
        create_mock = mocker.patch.object(
            handler,
            "create_webtransport_session",
            autospec=True,
            return_value=("new-session", 4),
        )

        result = await handler.recover_session(session_id="session-1234")

        assert result is True
        create_mock.assert_called_once_with(path="/recover", headers={"x-foo": "bar"})

    async def test_send_data_for_stream_with_no_session(self, handler: WebTransportProtocolHandler) -> None:
        handler._register_stream(session_id="s1", stream_id=4, direction=StreamDirection.BIDIRECTIONAL)
        handler._sessions.pop("s1", None)
        with pytest.raises(ProtocolError, match="No session found for stream"):
            handler.send_webtransport_stream_data(stream_id=4, data=b"foo")

    async def test_send_webtransport_datagram(
        self, handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info

        handler.send_webtransport_datagram(session_id="session-1234", data=b"ping")

        mock_h3_engine.send_datagram.assert_called_once_with(stream_id=0, data=b"ping")
        assert handler.stats["datagrams_sent"] == 1

    async def test_send_webtransport_datagram_session_not_found(self, handler: WebTransportProtocolHandler) -> None:
        with pytest.raises(ProtocolError, match="not found or not ready"):
            handler.send_webtransport_datagram(session_id="non-existent", data=b"ping")

    async def test_send_webtransport_datagram_session_not_ready(self, handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTING,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info

        with pytest.raises(ProtocolError, match="not found or not ready"):
            handler.send_webtransport_datagram(session_id="session-1234", data=b"ping")

    async def test_send_webtransport_stream_data_flow_control_error(self, handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        session_info.peer_max_data = 100
        handler._sessions["session-1234"] = session_info
        handler._register_stream(
            session_id="session-1234",
            stream_id=4,
            direction=StreamDirection.BIDIRECTIONAL,
        )

        with pytest.raises(FlowControlError, match="Session data limit reached"):
            handler.send_webtransport_stream_data(stream_id=4, data=b"a" * 101)

    @pytest.mark.parametrize("state", [StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED])
    async def test_send_webtransport_stream_data_on_unwritable_stream(
        self, handler: WebTransportProtocolHandler, state: StreamState
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info
        stream = handler._register_stream(
            session_id="session-1234",
            stream_id=4,
            direction=StreamDirection.BIDIRECTIONAL,
        )
        stream.state = state

        with pytest.raises(ProtocolError, match="not found or not writable"):
            handler.send_webtransport_stream_data(stream_id=4, data=b"foo")

    async def test_trigger_transmission_no_connection(self, mock_quic: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, connection=None)
        handler.abort_stream(stream_id=4, error_code=1)


@pytest.mark.asyncio
class TestWebTransportProtocolHandlerServer:
    @pytest.fixture
    def server_handler(
        self,
        mock_quic: MagicMock,
        server_config: ServerConfig,
        mock_h3_engine: MagicMock,
        mock_utils: dict[str, MagicMock],
        mocker: MockerFixture,
    ) -> WebTransportProtocolHandler:
        mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_conn.config = server_config
        return WebTransportProtocolHandler(quic_connection=mock_quic, is_client=False, connection=mock_conn)

    async def test_accept_session_with_mismatched_stream_id(self, server_handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTING, path="/", created_at=123.0
        )
        server_handler._sessions["s1"] = session_info

        with pytest.raises(ProtocolError, match="No pending session found"):
            server_handler.accept_webtransport_session(stream_id=4, session_id="s1")

    async def test_accept_webtransport_session(
        self, server_handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        headers_event = HeadersReceived(
            stream_id=0,
            headers={":method": "CONNECT", ":protocol": "webtransport"},
            stream_ended=False,
        )
        await server_handler._handle_session_headers(event=headers_event)
        session_id = "session-1234"
        session_info_before = server_handler.get_session_info(session_id=session_id)
        assert session_info_before is not None
        assert session_info_before.state == SessionState.CONNECTING
        mock_session_ready_handler: AsyncMock = AsyncMock()
        server_handler.on(event_type=EventType.SESSION_READY, handler=mock_session_ready_handler)

        server_handler.accept_webtransport_session(stream_id=0, session_id=session_id)
        await asyncio.sleep(0)

        mock_h3_engine.send_headers.assert_called_with(stream_id=0, headers={":status": "200"})
        session_info_after = server_handler.get_session_info(session_id=session_id)
        assert session_info_after is not None
        assert session_info_after.state == SessionState.CONNECTED
        mock_session_ready_handler.assert_called_once()

    async def test_accept_webtransport_session_with_invalid_id(
        self, server_handler: WebTransportProtocolHandler
    ) -> None:
        with pytest.raises(ProtocolError, match="No pending session found"):
            server_handler.accept_webtransport_session(stream_id=0, session_id="non-existent")

    async def test_handle_session_headers_connect_request(self, server_handler: WebTransportProtocolHandler) -> None:
        headers = {":method": "CONNECT", ":protocol": "webtransport", ":path": "/chat"}
        headers_event = HeadersReceived(stream_id=0, headers=headers, stream_ended=False)
        mock_session_request_handler: AsyncMock = AsyncMock()
        server_handler.on(
            event_type=EventType.SESSION_REQUEST,
            handler=mock_session_request_handler,
        )

        await server_handler._handle_session_headers(event=headers_event)

        mock_session_request_handler.assert_called_once()
        emitted_event = mock_session_request_handler.call_args.args[0]
        session_id = emitted_event.data["session_id"]
        assert session_id == "session-1234"
        session_info = server_handler.get_session_info(session_id=session_id)
        assert session_info is not None
        assert session_info.state == SessionState.CONNECTING
        assert session_info.path == "/chat"
        assert session_info.stream_id == 0

    async def test_handle_session_headers_connect_request_no_connection(
        self, mock_quic: MagicMock, server_config: ServerConfig
    ) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, is_client=False, connection=None)
        handler._config = server_config
        request_spy = AsyncMock()
        handler.on(event_type=EventType.SESSION_REQUEST, handler=request_spy)

        headers_event = HeadersReceived(
            stream_id=0,
            headers={":method": "CONNECT", ":protocol": "webtransport"},
            stream_ended=False,
        )
        await handler._handle_session_headers(event=headers_event)

        request_spy.assert_called_once()
        assert "connection" not in request_spy.call_args.args[0].data

    async def test_handle_session_headers_non_connect_and_send_fails(
        self,
        server_handler: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        abort_spy = mocker.spy(server_handler, "abort_stream")
        mock_h3_engine.send_headers.side_effect = Exception("Send failed")
        headers_event = HeadersReceived(stream_id=0, headers={":method": "GET", ":path": "/"}, stream_ended=True)

        await server_handler._handle_session_headers(event=headers_event)

        abort_spy.assert_called_with(stream_id=0, error_code=ErrorCodes.H3_REQUEST_REJECTED)

    async def test_handle_session_headers_non_connect_request(
        self, server_handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        headers_event = HeadersReceived(stream_id=0, headers={":method": "GET", ":path": "/"}, stream_ended=True)

        await server_handler._handle_session_headers(event=headers_event)

        mock_h3_engine.send_headers.assert_called_with(stream_id=0, headers={":status": "404"}, end_stream=True)
        assert not server_handler._sessions

    async def test_handle_session_headers_rejects_when_limit_reached(
        self, server_handler: WebTransportProtocolHandler, mock_quic: MagicMock
    ) -> None:
        cast(ServerConfig, server_handler._config).max_sessions = 1
        server_handler._sessions["existing-session"] = WebTransportSessionInfo(
            session_id="existing",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=1,
        )
        headers_event = HeadersReceived(
            stream_id=4,
            headers={":method": "CONNECT", ":protocol": "webtransport"},
            stream_ended=False,
        )

        await server_handler._handle_session_headers(event=headers_event)

        mock_quic.reset_stream.assert_called_once_with(stream_id=4, error_code=ErrorCodes.H3_REQUEST_REJECTED)
        assert len(server_handler._sessions) == 1


@pytest.mark.asyncio
class TestCoverageGaps:
    async def test_abort_receive_only_stream(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_stream = MagicMock()
        mock_stream.receiver.is_finished = False
        mock_quic._streams[5] = mock_stream
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_send_data_on_stream",
            return_value=False,
        )
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_receive_data_on_stream",
            return_value=True,
        )
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.webtransport_code_to_http_code",
            return_value=0xDEADBEEF,
        )

        handler.abort_stream(stream_id=5, error_code=1)

        mock_quic.reset_stream.assert_not_called()
        mock_quic.stop_stream.assert_called_once_with(stream_id=5, error_code=0xDEADBEEF)

    async def test_capsule_handler_ignores_non_capsule_events(self, handler: WebTransportProtocolHandler) -> None:
        await handler._capsule_received_handler(Event(type=EventType.SESSION_REQUEST, data={}))

    async def test_cleanup_session_idempotent(self, handler: WebTransportProtocolHandler) -> None:
        handler._cleanup_session(session_id="non-existent")

    async def test_cleanup_session_with_pre_cleaned_stream(self, handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=1
        )
        handler._register_session(session_id="s1", session_info=session_info)
        stream_info = handler._register_stream(session_id="s1", stream_id=4, direction=StreamDirection.BIDIRECTIONAL)
        assert 4 in handler._session_owned_streams["s1"]
        handler._streams.pop(4)
        handler._cleanup_session(session_id="s1")
        assert "s1" not in handler._sessions
        assert stream_info is not None

    async def test_cleanup_stream_without_session_owner(self, handler: WebTransportProtocolHandler) -> None:
        handler._register_stream(session_id="s1", stream_id=4, direction=StreamDirection.BIDIRECTIONAL)
        handler._data_stream_to_session.pop(4)

        handler._cleanup_stream(stream_id=4)

        assert 4 not in handler._streams

    async def test_close_before_connection_established(self, mock_quic: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic)
        await handler.close()
        assert handler._cleanup_pending_events_task is None

    async def test_close_without_cleanup_task(self, mock_quic: MagicMock, mock_h3_engine: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic)
        handler._config.pending_event_ttl = 0

        handler.connection_established()
        await handler.close()

        assert handler._cleanup_pending_events_task is None
        mock_h3_engine.off.assert_called()

    async def test_handle_datagram_no_connection(self, mock_quic: MagicMock, mock_h3_engine: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, connection=None)
        event = DatagramReceived(stream_id=0, data=b"hello")

        await handler._handle_datagram_received(event=event)

    async def test_handle_session_headers_no_record_activity(
        self, mock_quic: MagicMock, mock_connection: MagicMock
    ) -> None:
        del mock_connection.record_activity
        handler = WebTransportProtocolHandler(quic_connection=mock_quic, connection=mock_connection, is_client=True)
        await handler._handle_session_headers(
            event=HeadersReceived(stream_id=0, headers={":status": "200"}, stream_ended=False)
        )

    @pytest.mark.parametrize("state", [QuicConnectionState.CLOSING, QuicConnectionState.DRAINING])
    async def test_handle_orphan_stream_data_during_closing(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock, state: QuicConnectionState
    ) -> None:
        mock_quic._state = state
        handler._config.pending_event_ttl = 0
        event = WebTransportStreamDataReceived(stream_id=4, session_id=99, data=b"", stream_ended=True)
        await handler._handle_webtransport_stream_data(event=event)

    async def test_handle_orphan_stream_data_without_buffering(
        self, handler: WebTransportProtocolHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        handler._config.pending_event_ttl = 0
        event = WebTransportStreamDataReceived(stream_id=4, session_id=99, data=b"", stream_ended=True)

        with caplog.at_level(logging.ERROR):
            await handler._handle_webtransport_stream_data(event=event)

        assert "No session mapping found" in caplog.text

    async def test_handle_stream_reset_on_data_stream(self, handler: WebTransportProtocolHandler) -> None:
        handler._register_stream(session_id="s1", stream_id=4, direction=StreamDirection.BIDIRECTIONAL)
        await handler.handle_quic_event(event=StreamReset(stream_id=4, error_code=123))
        assert 4 not in handler._streams

    async def test_handle_stream_reset_on_non_session_stream(self, handler: WebTransportProtocolHandler) -> None:
        reset_event = StreamReset(stream_id=999, error_code=123)
        closed_spy = AsyncMock()
        handler.on(event_type=EventType.SESSION_CLOSED, handler=closed_spy)

        await handler.handle_quic_event(event=reset_event)

        closed_spy.assert_not_called()

    async def test_read_stream_complete_reentrant_handler(self, handler: WebTransportProtocolHandler) -> None:
        future = asyncio.get_running_loop().create_future()
        chunks: list[bytes] = []
        handler_event: Event | None = None

        async def data_handler(event: Event) -> None:
            nonlocal handler_event
            if future.done():
                return
            handler_event = event
            if event.data and event.data.get("data"):
                chunks.append(event.data.get("data", b""))
            if event.data and event.data.get("end_stream"):
                future.set_result(None)

        handler.on(event_type="stream_data_received:4", handler=data_handler)

        await handler.emit(
            event_type="stream_data_received:4",
            data={"data": b"part1", "end_stream": True},
        )
        await asyncio.sleep(0)

        assert future.done()
        assert handler_event is not None
        if handler_event:
            await data_handler(handler_event)
        assert b"".join(chunks) == b"part1"

    async def test_teardown_with_no_h3_engine(self, mock_quic: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic)
        handler._h3 = None  # type: ignore[assignment]
        await handler.close()

    async def test_update_flow_control_with_window_disabled(
        self, handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
            local_max_streams_bidi=100,
            local_max_streams_uni=100,
        )
        handler._sessions["s1"] = session_info
        handler._config.flow_control_window_size = 0

        await handler._update_local_flow_control(session_id="s1")

        mock_h3_engine.send_capsule.assert_not_called()

    @pytest.mark.parametrize(
        "update_func_name",
        ["_update_stream_state_on_receive_end", "_update_stream_state_on_send_end"],
    )
    async def test_update_stream_state_with_invalid_id(
        self, handler: WebTransportProtocolHandler, update_func_name: str
    ) -> None:
        update_func = getattr(handler, update_func_name)
        update_func(stream_id=999)

    async def test_create_unidirectional_stream_on_first_data(self, handler: WebTransportProtocolHandler) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234", stream_id=0, state=SessionState.CONNECTING, path="/", created_at=123.0
        )
        handler._register_session(session_id="session-1234", session_info=session_info)
        event = WebTransportStreamDataReceived(stream_id=3, session_id=0, data=b"hello", stream_ended=True)
        opened_spy = AsyncMock()
        handler.on(event_type=EventType.STREAM_OPENED, handler=opened_spy)

        await handler._handle_webtransport_stream_data(event=event)

        opened_spy.assert_called_once()
        stream_info = handler._streams[3]
        assert stream_info.direction == StreamDirection.RECEIVE_ONLY
        assert session_info.peer_streams_uni_opened == 1


@pytest.mark.asyncio
class TestFinalCoveragePush:
    async def test_abort_send_only_stream(
        self, handler: WebTransportProtocolHandler, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_stream = MagicMock()
        mock_stream.sender._reset_error_code = None
        mock_quic._streams[1] = mock_stream
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_send_data_on_stream",
            return_value=True,
        )
        mocker.patch(
            "pywebtransport.protocol.handler.protocol_utils.can_receive_data_on_stream",
            return_value=False,
        )

        handler.abort_stream(stream_id=1, error_code=1)

        mock_quic.reset_stream.assert_called_once()
        mock_quic.stop_stream.assert_not_called()

    async def test_close_with_completed_cleanup_task(self, mock_quic: MagicMock, mock_h3_engine: MagicMock) -> None:
        handler = WebTransportProtocolHandler(quic_connection=mock_quic)
        handler.connection_established()
        assert handler._cleanup_pending_events_task is not None

        async def dummy_coro() -> None:
            pass

        handler._cleanup_pending_events_task = asyncio.create_task(dummy_coro())
        await asyncio.sleep(0)

        await handler.close()

    async def test_send_blocked_capsule_on_send_data(
        self,
        handler: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=123.0
        )
        session_info.peer_max_data = 10
        handler._sessions["s1"] = session_info
        handler._register_stream(session_id="s1", stream_id=4, direction=StreamDirection.BIDIRECTIONAL)

        with pytest.raises(FlowControlError):
            handler.send_webtransport_stream_data(stream_id=4, data=b"x" * 11)

        mock_h3_engine.send_capsule.assert_called_once()
        kwargs = mock_h3_engine.send_capsule.call_args.kwargs
        buf = Buffer(data=kwargs["capsule_data"])
        capsule_type = buf.pull_uint_var()
        assert capsule_type == constants.WT_DATA_BLOCKED_TYPE

    @pytest.mark.parametrize("state", [StreamState.HALF_CLOSED_LOCAL, StreamState.HALF_CLOSED_REMOTE])
    async def test_update_stream_state_to_closed(
        self, handler: WebTransportProtocolHandler, state: StreamState
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="session-1234",
            stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=123.0,
        )
        handler._sessions["session-1234"] = session_info
        stream_info = handler._register_stream(
            session_id="session-1234", stream_id=4, direction=StreamDirection.BIDIRECTIONAL
        )
        stream_info.state = state

        if state == StreamState.HALF_CLOSED_LOCAL:
            handler._update_stream_state_on_receive_end(stream_id=4)
        else:
            handler.send_webtransport_stream_data(stream_id=4, data=b"", end_stream=True)
        assert 4 not in handler._streams
