"""Unit tests for the pywebtransport.protocol._session_tracker module."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aioquic._buffer import Buffer
from aioquic.buffer import encode_uint_var
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError, Event, ProtocolError, ServerConfig, constants
from pywebtransport.constants import ErrorCodes
from pywebtransport.protocol import WebTransportSessionInfo
from pywebtransport.protocol._session_tracker import _ProtocolSessionTracker
from pywebtransport.protocol.events import CapsuleReceived, HeadersReceived
from pywebtransport.protocol.h3_engine import WebTransportH3Engine
from pywebtransport.types import EventType, SessionState


@pytest.fixture
def client_tracker(
    mock_config: MagicMock,
    mock_quic: MagicMock,
    mock_h3_engine: MagicMock,
    mock_emit: AsyncMock,
    mock_trigger_transmission: MagicMock,
    mock_cleanup_streams: MagicMock,
    mock_abort_stream: MagicMock,
) -> _ProtocolSessionTracker:
    return _ProtocolSessionTracker(
        config=mock_config,
        is_client=True,
        quic=mock_quic,
        h3=mock_h3_engine,
        stats={"sessions_created": 0},
        emit_event=mock_emit,
        trigger_transmission=mock_trigger_transmission,
        cleanup_streams_for_session_by_id=mock_cleanup_streams,
        abort_stream=mock_abort_stream,
    )


@pytest.fixture
def mock_abort_stream() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_cleanup_streams() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_config() -> Any:
    config = MagicMock(spec=ClientConfig)
    config.initial_max_data = 1024
    config.initial_max_streams_bidi = 10
    config.initial_max_streams_uni = 5
    config.flow_control_window_size = 512
    config.flow_control_window_auto_scale = False
    config.stream_flow_control_increment_bidi = 2
    config.stream_flow_control_increment_uni = 1
    return config


@pytest.fixture
def mock_emit() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_h3_engine(mocker: MockerFixture) -> MagicMock:
    mock = mocker.create_autospec(WebTransportH3Engine, instance=True)
    cast(MagicMock, mock.get_server_name).return_value = "example.com"
    return mock


@pytest.fixture
def mock_quic(mocker: MockerFixture) -> MagicMock:
    mock = mocker.create_autospec(MagicMock, instance=True)
    mock.reset_stream = MagicMock()
    mock.send_stream_data = MagicMock()
    return mock


@pytest.fixture
def mock_server_config() -> Any:
    config = MagicMock(spec=ServerConfig)
    config.max_sessions = 10
    config.initial_max_data = 1024
    config.initial_max_streams_bidi = 10
    config.initial_max_streams_uni = 5
    config.flow_control_window_size = 512
    config.flow_control_window_auto_scale = False
    config.stream_flow_control_increment_bidi = 2
    config.stream_flow_control_increment_uni = 1
    return config


@pytest.fixture
def mock_trigger_transmission() -> MagicMock:
    return MagicMock()


@pytest.fixture
def ready_session(client_tracker: _ProtocolSessionTracker, mock_config: MagicMock) -> WebTransportSessionInfo:
    session_info = WebTransportSessionInfo(
        session_id="test-session",
        control_stream_id=0,
        state=SessionState.CONNECTING,
        path="/",
        created_at=0.0,
    )
    client_tracker._register_session(session_id="test-session", session_info=session_info)
    session_info.state = SessionState.CONNECTED
    return session_info


@pytest.fixture
def server_tracker(
    mock_server_config: MagicMock,
    mock_quic: MagicMock,
    mock_h3_engine: MagicMock,
    mock_emit: AsyncMock,
    mock_trigger_transmission: MagicMock,
    mock_cleanup_streams: MagicMock,
    mock_abort_stream: MagicMock,
) -> _ProtocolSessionTracker:
    return _ProtocolSessionTracker(
        config=mock_server_config,
        is_client=False,
        quic=mock_quic,
        h3=mock_h3_engine,
        stats={"sessions_created": 0},
        emit_event=mock_emit,
        trigger_transmission=mock_trigger_transmission,
        cleanup_streams_for_session_by_id=mock_cleanup_streams,
        abort_stream=mock_abort_stream,
    )


class TestProtocolSessionTrackerClient:
    def test_accept_session_raises_error(self, client_tracker: _ProtocolSessionTracker) -> None:
        with pytest.raises(ProtocolError, match="Only servers can accept"):
            client_tracker.accept_webtransport_session(stream_id=0, session_id="s1")

    @pytest.mark.asyncio
    async def test_create_session_authority_precedence(
        self, client_tracker: _ProtocolSessionTracker, mock_h3_engine: MagicMock
    ) -> None:
        cast(MagicMock, mock_h3_engine.get_next_available_stream_id).return_value = 0
        await client_tracker.create_webtransport_session(path="/", headers={"host": "specific.com"})
        sent_headers = cast(MagicMock, mock_h3_engine.send_headers).call_args.kwargs["headers"]
        assert sent_headers[":authority"] == "specific.com"

    @pytest.mark.asyncio
    async def test_create_session_limit_reached(self, client_tracker: _ProtocolSessionTracker) -> None:
        client_tracker._peer_max_sessions = 0
        with pytest.raises(ConnectionError, match="session limit"):
            await client_tracker.create_webtransport_session(path="/test")

    @pytest.mark.asyncio
    async def test_create_session_localhost_fallback(
        self, client_tracker: _ProtocolSessionTracker, mock_h3_engine: MagicMock
    ) -> None:
        cast(MagicMock, mock_h3_engine.get_server_name).return_value = None
        cast(MagicMock, mock_h3_engine.get_next_available_stream_id).return_value = 0
        await client_tracker.create_webtransport_session(path="/")
        sent_headers = cast(MagicMock, mock_h3_engine.send_headers).call_args.kwargs["headers"]
        assert sent_headers[":authority"] == "localhost"

    @pytest.mark.asyncio
    async def test_create_session_no_limit(self, client_tracker: _ProtocolSessionTracker) -> None:
        client_tracker._peer_max_sessions = None
        mock_h3_engine = cast(MagicMock, client_tracker._h3)
        mock_h3_engine.get_next_available_stream_id.return_value = 0
        await client_tracker.create_webtransport_session(path="/test")
        mock_h3_engine.send_headers.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_session_success(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_h3_engine: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        cast(MagicMock, mock_h3_engine.get_next_available_stream_id).return_value = 0
        session_id, stream_id = await client_tracker.create_webtransport_session(path="/test")

        assert session_id in client_tracker._sessions
        assert stream_id == 0
        cast(MagicMock, mock_h3_engine.send_headers).assert_called_once()
        mock_trigger_transmission.assert_called_once()
        assert client_tracker._stats["sessions_created"] == 1

    @pytest.mark.asyncio
    async def test_client_handle_headers_on_unknown_stream(
        self, client_tracker: _ProtocolSessionTracker, mock_emit: AsyncMock
    ) -> None:
        event = HeadersReceived(stream_id=999, headers={":status": "200"}, stream_ended=False)
        result = await client_tracker.handle_headers_received(event=event, connection=None)
        assert result is None
        mock_emit.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "headers, expected_reason",
        [
            ({":status": "404"}, "HTTP status 404"),
            ({}, "HTTP status unknown"),
        ],
    )
    async def test_handle_headers_received_failure(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        mock_cleanup_streams: MagicMock,
        ready_session: WebTransportSessionInfo,
        headers: dict[str, str],
        expected_reason: str,
    ) -> None:
        ready_session.state = SessionState.CONNECTING
        event = HeadersReceived(stream_id=0, headers=headers, stream_ended=False)
        result = await client_tracker.handle_headers_received(event=event, connection=None)
        assert result is None
        mock_emit.assert_awaited_once_with(
            EventType.SESSION_CLOSED,
            {"session_id": "test-session", "code": 1, "reason": expected_reason},
        )
        mock_cleanup_streams.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_handle_headers_received_session_not_found(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        ready_session: WebTransportSessionInfo,
    ) -> None:
        client_tracker._sessions.pop("test-session")
        event = HeadersReceived(stream_id=0, headers={":status": "200"}, stream_ended=False)
        await client_tracker.handle_headers_received(event=event, connection=None)
        mock_emit.assert_awaited_once()
        assert mock_emit.await_args is not None
        assert mock_emit.await_args.args[0] == EventType.SESSION_CLOSED

    @pytest.mark.asyncio
    async def test_handle_headers_received_success(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        ready_session: WebTransportSessionInfo,
    ) -> None:
        ready_session.state = SessionState.CONNECTING
        event = HeadersReceived(stream_id=0, headers={":status": "200"}, stream_ended=False)
        result = await client_tracker.handle_headers_received(event=event, connection=None)
        assert result == "test-session"
        assert ready_session.state == SessionState.CONNECTED
        mock_emit.assert_awaited_once_with(EventType.SESSION_READY, ready_session.to_dict())


class TestProtocolSessionTrackerCommon:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("reason", ["test", None])
    async def test_close_session(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_h3_engine: MagicMock,
        mock_quic: MagicMock,
        mock_cleanup_streams: MagicMock,
        ready_session: WebTransportSessionInfo,
        reason: str | None,
    ) -> None:
        client_tracker.close_webtransport_session(session_id="test-session", code=123, reason=reason)
        await asyncio.sleep(0)

        cast(MagicMock, mock_h3_engine.send_capsule).assert_called_once()
        mock_quic.send_stream_data.assert_called_once_with(stream_id=0, data=b"", end_stream=True)
        mock_cleanup_streams.assert_called_once_with("test-session")
        assert "test-session" not in client_tracker._sessions

    @pytest.mark.parametrize("session_id", ["non-existent", "test-session"])
    def test_close_session_idempotent(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_h3_engine: MagicMock,
        ready_session: WebTransportSessionInfo,
        session_id: str,
    ) -> None:
        ready_session.state = SessionState.CLOSED
        client_tracker.close_webtransport_session(session_id=session_id)
        cast(MagicMock, mock_h3_engine.send_capsule).assert_not_called()

    def test_getters(self, client_tracker: _ProtocolSessionTracker, ready_session: WebTransportSessionInfo) -> None:
        assert client_tracker.get_all_sessions() == [ready_session]
        assert client_tracker.get_session_by_control_stream(stream_id=0) == "test-session"
        assert client_tracker.get_session_info(session_id="test-session") is ready_session

    @pytest.mark.asyncio
    async def test_handle_capsule_buffer_read_error(
        self,
        client_tracker: _ProtocolSessionTracker,
        ready_session: WebTransportSessionInfo,
        mocker: MockerFixture,
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.protocol._session_tracker.logger")
        event = CapsuleReceived(stream_id=0, capsule_type=constants.WT_MAX_DATA_TYPE, capsule_data=b"")
        await client_tracker.handle_capsule_received(event=event)
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_capsule_close_session(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        mock_cleanup_streams: MagicMock,
    ) -> None:
        client_tracker._session_control_streams[0] = "s1"
        client_tracker._sessions["s1"] = MagicMock()
        buf = Buffer(capacity=1024)
        buf.push_uint32(42)
        buf.push_bytes("closed".encode("utf-8"))
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.CLOSE_WEBTRANSPORT_SESSION_TYPE,
            capsule_data=buf.data,
        )

        await client_tracker.handle_capsule_received(event=event)
        mock_emit.assert_awaited_once_with(
            EventType.SESSION_CLOSED,
            {"session_id": "s1", "code": 42, "reason": "closed"},
        )
        mock_cleanup_streams.assert_called_once_with("s1")

    @pytest.mark.asyncio
    async def test_handle_capsule_close_session_invalid_utf8(
        self, client_tracker: _ProtocolSessionTracker, mock_emit: AsyncMock, mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.protocol._session_tracker.logger")
        client_tracker._session_control_streams[0] = "s1"
        client_tracker._sessions["s1"] = MagicMock()
        buf = Buffer(capacity=1024)
        buf.push_uint32(42)
        buf.push_bytes(b"\x80")
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.CLOSE_WEBTRANSPORT_SESSION_TYPE,
            capsule_data=buf.data,
        )
        await client_tracker.handle_capsule_received(event=event)
        assert mock_emit.await_args is not None
        assert mock_emit.await_args.args[1]["reason"] == "\ufffd"

    @pytest.mark.asyncio
    async def test_handle_capsule_drain_session(
        self, client_tracker: _ProtocolSessionTracker, mock_emit: AsyncMock
    ) -> None:
        client_tracker._session_control_streams[0] = "s1"
        client_tracker._sessions["s1"] = MagicMock()
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.DRAIN_WEBTRANSPORT_SESSION_TYPE,
            capsule_data=b"",
        )
        await client_tracker.handle_capsule_received(event=event)
        mock_emit.assert_awaited_once_with(EventType.SESSION_DRAINING, {"session_id": "s1"})

    @pytest.mark.asyncio
    async def test_handle_capsule_flow_control_no_update(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        ready_session: WebTransportSessionInfo,
    ) -> None:
        ready_session.peer_max_data = 100
        event = CapsuleReceived(
            stream_id=0,
            capsule_type=constants.WT_MAX_DATA_TYPE,
            capsule_data=encode_uint_var(100),
        )
        await client_tracker.handle_capsule_received(event=event)
        mock_emit.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "capsule_type, attr_name",
        [
            (constants.WT_MAX_DATA_TYPE, "peer_max_data"),
            (constants.WT_MAX_STREAMS_BIDI_TYPE, "peer_max_streams_bidi"),
            (constants.WT_MAX_STREAMS_UNI_TYPE, "peer_max_streams_uni"),
        ],
    )
    async def test_handle_capsule_flow_control_decrease_raises_error(
        self,
        client_tracker: _ProtocolSessionTracker,
        ready_session: WebTransportSessionInfo,
        capsule_type: int,
        attr_name: str,
    ) -> None:
        setattr(ready_session, attr_name, 200)
        event = CapsuleReceived(stream_id=0, capsule_type=capsule_type, capsule_data=encode_uint_var(100))
        with pytest.raises(ProtocolError, match="Flow control limit decreased"):
            await client_tracker.handle_capsule_received(event=event)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "capsule_type, initial_attr, new_value, event_type",
        [
            (
                constants.WT_MAX_DATA_TYPE,
                "peer_max_data",
                200,
                EventType.SESSION_MAX_DATA_UPDATED,
            ),
            (
                constants.WT_MAX_STREAMS_BIDI_TYPE,
                "peer_max_streams_bidi",
                20,
                EventType.SESSION_MAX_STREAMS_BIDI_UPDATED,
            ),
            (
                constants.WT_MAX_STREAMS_UNI_TYPE,
                "peer_max_streams_uni",
                10,
                EventType.SESSION_MAX_STREAMS_UNI_UPDATED,
            ),
        ],
    )
    async def test_handle_capsule_flow_control_update(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        ready_session: WebTransportSessionInfo,
        capsule_type: int,
        initial_attr: str,
        new_value: int,
        event_type: EventType,
    ) -> None:
        setattr(ready_session, initial_attr, 0)
        event = CapsuleReceived(stream_id=0, capsule_type=capsule_type, capsule_data=encode_uint_var(new_value))
        await client_tracker.handle_capsule_received(event=event)
        mock_emit.assert_awaited_once()
        assert mock_emit.await_args is not None
        assert mock_emit.await_args.args[0] == event_type
        assert getattr(ready_session, initial_attr) == new_value

    @pytest.mark.asyncio
    async def test_handle_capsule_received_inconsistent_state(self, client_tracker: _ProtocolSessionTracker) -> None:
        client_tracker._session_control_streams[0] = "test-session"
        event = CapsuleReceived(stream_id=0, capsule_type=constants.WT_MAX_DATA_TYPE, capsule_data=b"")
        await client_tracker.handle_capsule_received(event=event)

    @pytest.mark.asyncio
    async def test_handle_capsule_received_no_session(self, client_tracker: _ProtocolSessionTracker) -> None:
        event = CapsuleReceived(stream_id=99, capsule_type=constants.WT_MAX_DATA_TYPE, capsule_data=b"")
        await client_tracker.handle_capsule_received(event=event)

    @pytest.mark.asyncio
    async def test_handle_capsule_unknown_type(self, client_tracker: _ProtocolSessionTracker) -> None:
        client_tracker._session_control_streams[0] = "s1"
        client_tracker._sessions["s1"] = MagicMock()
        event = CapsuleReceived(stream_id=0, capsule_type=0xFFFF, capsule_data=b"")
        await client_tracker.handle_capsule_received(event=event)

    @pytest.mark.asyncio
    async def test_handle_stream_reset(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        mock_cleanup_streams: MagicMock,
        ready_session: WebTransportSessionInfo,
    ) -> None:
        await client_tracker.handle_stream_reset(stream_id=0, error_code=123)

        mock_emit.assert_awaited_once_with(
            EventType.SESSION_CLOSED,
            {"session_id": "test-session", "code": 123, "reason": "Control stream reset"},
        )
        mock_cleanup_streams.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_handle_stream_reset_non_control_stream(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        mock_cleanup_streams: MagicMock,
    ) -> None:
        await client_tracker.handle_stream_reset(stream_id=999, error_code=123)
        mock_emit.assert_not_awaited()
        mock_cleanup_streams.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_data", [None, {}, {"settings": None}])
    async def test_on_settings_received_invalid_event(
        self, client_tracker: _ProtocolSessionTracker, event_data: Any
    ) -> None:
        event = Event(type=EventType.SETTINGS_RECEIVED, data=event_data)
        await client_tracker._on_settings_received(event)
        assert client_tracker._peer_max_sessions is None

    @pytest.mark.asyncio
    async def test_on_settings_received(
        self,
        client_tracker: _ProtocolSessionTracker,
        ready_session: WebTransportSessionInfo,
    ) -> None:
        settings = {
            constants.SETTINGS_WT_MAX_SESSIONS: 10,
            constants.SETTINGS_WT_INITIAL_MAX_DATA: 2048,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI: 20,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI: 10,
        }
        event = Event(type=EventType.SETTINGS_RECEIVED, data={"settings": settings})
        await client_tracker._on_settings_received(event)

        assert client_tracker._peer_max_sessions == 10
        assert client_tracker._peer_initial_max_data == 2048
        assert client_tracker._peer_initial_max_streams_bidi == 20
        assert client_tracker._peer_initial_max_streams_uni == 10
        assert ready_session.peer_max_data == 2048
        assert ready_session.peer_max_streams_bidi == 20
        assert ready_session.peer_max_streams_uni == 10

    @pytest.mark.parametrize(
        "is_data, is_unidirectional, expected_type",
        [
            (True, False, constants.WT_DATA_BLOCKED_TYPE),
            (False, True, constants.WT_STREAMS_BLOCKED_UNI_TYPE),
            (False, False, constants.WT_STREAMS_BLOCKED_BIDI_TYPE),
        ],
    )
    def test_send_blocked_capsule(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_h3_engine: MagicMock,
        is_data: bool,
        is_unidirectional: bool,
        expected_type: int,
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=0.0,
        )
        client_tracker._send_blocked_capsule(
            session_info=session_info,
            is_data=is_data,
            is_unidirectional=is_unidirectional,
        )
        cast(MagicMock, mock_h3_engine.send_capsule).assert_called_once()
        sent_capsule_data = cast(MagicMock, mock_h3_engine.send_capsule).call_args.kwargs["capsule_data"]
        buf = Buffer(data=sent_capsule_data)
        decoded_capsule_type = buf.pull_uint_var()
        assert decoded_capsule_type == expected_type

    def test_teardown(self, client_tracker: _ProtocolSessionTracker, mock_h3_engine: MagicMock) -> None:
        client_tracker.teardown()
        cast(MagicMock, mock_h3_engine.off).assert_called_once_with(
            event_type=EventType.SETTINGS_RECEIVED,
            handler=client_tracker._on_settings_received,
        )

    # This test previously caused the pytest error due to the missing parametrize
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "update_attr, capsule_type",
        [
            ("peer_data_sent", constants.WT_MAX_DATA_TYPE),
            ("peer_streams_bidi_opened", constants.WT_MAX_STREAMS_BIDI_TYPE),
            ("peer_streams_uni_opened", constants.WT_MAX_STREAMS_UNI_TYPE),
        ],
    )
    async def test_update_local_flow_control(
        self,
        client_tracker: _ProtocolSessionTracker,
        ready_session: WebTransportSessionInfo,
        mock_h3_engine: MagicMock,
        mock_config: MagicMock,
        mocker: MockerFixture,
        update_attr: str,
        capsule_type: int,
    ) -> None:
        mocker.patch("pywebtransport.protocol._session_tracker.get_timestamp", return_value=1.0)
        ready_session.peer_data_sent = 0
        ready_session.peer_streams_bidi_opened = 0
        ready_session.peer_streams_uni_opened = 0

        if "data" in update_attr:
            ready_session.peer_data_sent = ready_session.local_max_data
        elif "bidi" in update_attr:
            ready_session.peer_streams_bidi_opened = ready_session.local_max_streams_bidi
        else:
            ready_session.peer_streams_uni_opened = ready_session.local_max_streams_uni

        await client_tracker.update_local_flow_control(session_id="test-session")
        cast(MagicMock, mock_h3_engine.send_capsule).assert_called_once()
        sent_capsule_data = cast(MagicMock, mock_h3_engine.send_capsule).call_args.kwargs["capsule_data"]
        buf = Buffer(data=sent_capsule_data)
        decoded_capsule_type = buf.pull_uint_var()
        assert decoded_capsule_type == capsule_type

    @pytest.mark.asyncio
    async def test_update_local_flow_control_auto_scale(
        self,
        client_tracker: _ProtocolSessionTracker,
        ready_session: WebTransportSessionInfo,
        mock_config: MagicMock,
    ) -> None:
        mock_config.flow_control_window_auto_scale = True
        ready_session.peer_data_sent = ready_session.local_max_data
        await client_tracker.update_local_flow_control(session_id="test-session")
        assert ready_session.local_max_data == mock_config.initial_max_data * 2

    @pytest.mark.asyncio
    async def test_update_local_flow_control_no_increase_and_not_sent(
        self,
        client_tracker: _ProtocolSessionTracker,
        ready_session: WebTransportSessionInfo,
        mock_h3_engine: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        mock_config.flow_control_window_auto_scale = False
        ready_session.local_max_data = 1_000_000
        ready_session.peer_data_sent = ready_session.local_max_data - mock_config.flow_control_window_size

        await client_tracker.update_local_flow_control(session_id="test-session")
        cast(MagicMock, mock_h3_engine.send_capsule).assert_not_called()

    @pytest.mark.asyncio
    async def test_update_local_flow_control_no_session(
        self, client_tracker: _ProtocolSessionTracker, mock_h3_engine: MagicMock
    ) -> None:
        await client_tracker.update_local_flow_control(session_id="non-existent")
        cast(MagicMock, mock_h3_engine.send_capsule).assert_not_called()

    @pytest.mark.asyncio
    async def test_update_local_flow_control_no_window(
        self,
        client_tracker: _ProtocolSessionTracker,
        mock_h3_engine: MagicMock,
        mock_config: MagicMock,
        ready_session: WebTransportSessionInfo,
    ) -> None:
        mock_config.flow_control_window_size = 0
        ready_session.peer_data_sent = ready_session.local_max_data
        await client_tracker.update_local_flow_control(session_id="test-session")
        cast(MagicMock, mock_h3_engine.send_capsule).assert_not_called()


class TestProtocolSessionTrackerServer:
    @pytest.mark.asyncio
    async def test_accept_session_success(
        self,
        server_tracker: _ProtocolSessionTracker,
        mock_h3_engine: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTING,
            path="/",
            created_at=0.0,
        )
        server_tracker._sessions["s1"] = session_info

        server_tracker.accept_webtransport_session(stream_id=0, session_id="s1")
        await asyncio.sleep(0)

        cast(MagicMock, mock_h3_engine.send_headers).assert_called_once_with(stream_id=0, headers={":status": "200"})
        mock_trigger_transmission.assert_called_once()
        assert session_info.state == SessionState.CONNECTED

    @pytest.mark.parametrize(
        "session_id, stream_id",
        [
            ("s1", 4),
            ("s2", 0),
            ("s2", 4),
        ],
    )
    def test_accept_session_failure(
        self, server_tracker: _ProtocolSessionTracker, session_id: str, stream_id: int
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTING,
            path="/",
            created_at=0.0,
        )
        server_tracker._sessions["s1"] = session_info
        with pytest.raises(ProtocolError, match="No pending session found"):
            server_tracker.accept_webtransport_session(stream_id=stream_id, session_id=session_id)

    @pytest.mark.asyncio
    async def test_create_session_raises_error(self, server_tracker: _ProtocolSessionTracker) -> None:
        with pytest.raises(ProtocolError, match="Only clients can create"):
            await server_tracker.create_webtransport_session(path="/test")

    @pytest.mark.asyncio
    async def test_handle_headers_received_connect(
        self,
        server_tracker: _ProtocolSessionTracker,
        mock_emit: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        event = HeadersReceived(
            stream_id=0,
            headers={":method": "CONNECT", ":protocol": "webtransport"},
            stream_ended=False,
        )
        mock_conn = MagicMock()
        result = await server_tracker.handle_headers_received(event=event, connection=mock_conn)
        assert result is not None
        assert server_tracker._stats["sessions_created"] == 1
        mock_emit.assert_awaited_once()
        assert mock_emit.await_args is not None
        event_name, event_data = mock_emit.await_args.args
        assert event_name == EventType.SESSION_REQUEST
        assert event_data["connection"] is mock_conn

    @pytest.mark.asyncio
    async def test_handle_headers_received_connect_no_path(
        self, server_tracker: _ProtocolSessionTracker, mock_emit: AsyncMock
    ) -> None:
        event = HeadersReceived(
            stream_id=0,
            headers={
                ":method": "CONNECT",
                ":protocol": "webtransport",
                "other-header": "value",
            },
            stream_ended=False,
        )
        await server_tracker.handle_headers_received(event=event, connection=None)
        assert mock_emit.await_args is not None
        assert mock_emit.await_args.args[1]["path"] == "/"

    @pytest.mark.asyncio
    async def test_handle_headers_received_invalid_method(
        self, server_tracker: _ProtocolSessionTracker, mock_h3_engine: MagicMock
    ) -> None:
        event = HeadersReceived(stream_id=0, headers={":method": "GET"}, stream_ended=False)
        result = await server_tracker.handle_headers_received(event=event, connection=None)
        assert result is None
        cast(MagicMock, mock_h3_engine.send_headers).assert_called_once_with(
            stream_id=0, headers={":status": "404"}, end_stream=True
        )

    @pytest.mark.asyncio
    async def test_handle_headers_received_limit_exceeded(
        self, server_tracker: _ProtocolSessionTracker, mock_quic: MagicMock
    ) -> None:
        if isinstance(server_tracker._config, ServerConfig):
            server_tracker._config.max_sessions = 0
        event = HeadersReceived(
            stream_id=0,
            headers={":method": "CONNECT", ":protocol": "webtransport"},
            stream_ended=False,
        )
        result = await server_tracker.handle_headers_received(event=event, connection=None)
        assert result is None
        mock_quic.reset_stream.assert_called_once_with(stream_id=0, error_code=ErrorCodes.H3_REQUEST_REJECTED)

    @pytest.mark.asyncio
    async def test_handle_headers_received_send_rejection_fails(
        self,
        server_tracker: _ProtocolSessionTracker,
        mock_h3_engine: MagicMock,
        mock_abort_stream: MagicMock,
    ) -> None:
        cast(MagicMock, mock_h3_engine.send_headers).side_effect = Exception("error")
        event = HeadersReceived(stream_id=0, headers={":method": "GET"}, stream_ended=False)
        await server_tracker.handle_headers_received(event=event, connection=None)
        mock_abort_stream.assert_called_once_with(stream_id=0, error_code=ErrorCodes.H3_REQUEST_REJECTED)

    @pytest.mark.asyncio
    async def test_handle_headers_received_wrong_method_with_protocol(
        self, server_tracker: _ProtocolSessionTracker, mock_h3_engine: MagicMock
    ) -> None:
        event = HeadersReceived(
            stream_id=0,
            headers={":method": "GET", ":protocol": "webtransport"},
            stream_ended=False,
        )
        result = await server_tracker.handle_headers_received(event=event, connection=None)
        assert result is None
        cast(MagicMock, mock_h3_engine.send_headers).assert_called_once_with(
            stream_id=0, headers={":status": "404"}, end_stream=True
        )
