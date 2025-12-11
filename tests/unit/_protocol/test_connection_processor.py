"""Unit tests for the pywebtransport._protocol.connection_processor module."""

import asyncio
from collections import deque
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError, ErrorCodes, ProtocolError, ServerConfig, constants
from pywebtransport._protocol.connection_processor import ConnectionProcessor
from pywebtransport._protocol.events import (
    CleanupH3Stream,
    CloseQuicConnection,
    CompleteUserFuture,
    ConnectionClose,
    CreateH3Session,
    EmitConnectionEvent,
    EmitSessionEvent,
    FailUserFuture,
    GoawayReceived,
    HeadersReceived,
    InternalBindH3Session,
    InternalCleanupResources,
    InternalFailH3Session,
    SendH3Capsule,
    SendH3Goaway,
    SendH3Headers,
    TransportConnectionTerminated,
    TransportQuicParametersReceived,
    UserConnectionGracefulClose,
    UserCreateSession,
    UserGetConnectionDiagnostics,
)
from pywebtransport._protocol.state import ProtocolState, SessionInitData, SessionStateData
from pywebtransport._protocol.state import StreamStateData as StreamStateDataInternal
from pywebtransport.types import ConnectionState, EventType, SessionState, StreamState


class TestConnectionProcessor:

    @pytest.fixture
    def client_processor(self, mock_config: MagicMock) -> ConnectionProcessor:
        return ConnectionProcessor(is_client=True, config=mock_config, connection_id="test-conn-id")

    @pytest.fixture
    def mock_config(self, mocker: MockerFixture) -> MagicMock:
        config = mocker.create_autospec(ClientConfig, instance=True)
        config.initial_max_data = 1024
        config.initial_max_streams_bidi = 10
        config.initial_max_streams_uni = 10
        config.max_sessions = 50
        return config

    @pytest.fixture
    def mock_future(self, mocker: MockerFixture) -> MagicMock:
        fut = mocker.create_autospec(asyncio.Future, instance=True)
        fut.done.return_value = False
        return fut

    @pytest.fixture
    def mock_generate_session_id(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch(
            "pywebtransport._protocol.connection_processor.generate_session_id", return_value="mock-session-id-1"
        )

    @pytest.fixture
    def mock_get_timestamp(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("pywebtransport._protocol.connection_processor.get_timestamp", return_value=123456.0)

    @pytest.fixture
    def mock_state(self, mocker: MockerFixture) -> MagicMock:
        state = mocker.create_autospec(ProtocolState, instance=True)
        state.connection_state = ConnectionState.CONNECTED
        state.is_client = True
        state.connected_at = 123456.0
        state.closed_at = None
        state.max_datagram_size = 1200
        state.remote_max_datagram_frame_size = 1100
        state.peer_initial_max_data = 2048
        state.peer_initial_max_streams_bidi = 5
        state.peer_initial_max_streams_uni = 5
        state.sessions = {}
        state.streams = {}
        state.stream_to_session_map = {}
        state.pending_create_session_futures = {}
        state.pending_session_configs = {}
        state.early_event_buffer = {}
        state.local_goaway_sent = False
        return state

    @pytest.fixture
    def server_processor(self, mocker: MockerFixture) -> ConnectionProcessor:
        mock_server_config = mocker.create_autospec(ServerConfig, instance=True)
        mock_server_config.initial_max_data = 1024
        mock_server_config.initial_max_streams_bidi = 10
        mock_server_config.initial_max_streams_uni = 10
        mock_server_config.max_sessions = 10
        return ConnectionProcessor(is_client=False, config=mock_server_config, connection_id="test-conn-id")

    def test_handle_cleanup_resources(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mocker: MockerFixture
    ) -> None:
        event = InternalCleanupResources()

        mock_session_closed = mocker.MagicMock(spec=SessionStateData)
        mock_session_closed.control_stream_id = 0
        mock_session_closed.state = SessionState.CLOSED
        mock_session_closed.active_streams = {2, 3}

        mock_session_open = mocker.MagicMock(spec=SessionStateData)
        mock_session_open.state = SessionState.CONNECTED
        mock_session_open.active_streams = {1}

        mock_stream_closed = mocker.MagicMock(spec=StreamStateDataInternal)
        mock_stream_closed.state = StreamState.CLOSED

        mock_stream_open = mocker.MagicMock(spec=StreamStateDataInternal)
        mock_stream_open.state = StreamState.OPEN

        mock_state.sessions = {"closed-sid": mock_session_closed, "open-sid": mock_session_open}
        mock_state.streams = {1: mock_stream_open, 2: mock_stream_closed, 3: mock_stream_open}
        mock_state.stream_to_session_map = {0: "closed-sid", 1: "open-sid", 2: "closed-sid", 3: "closed-sid"}

        effects = client_processor.handle_cleanup_resources(event=event, state=mock_state)

        assert "closed-sid" not in mock_state.sessions
        assert "open-sid" in mock_state.sessions
        assert 2 not in mock_state.streams
        assert 3 not in mock_state.streams
        assert 1 in mock_state.streams

        assert 0 not in mock_state.stream_to_session_map
        assert 2 not in mock_state.stream_to_session_map
        assert 3 not in mock_state.stream_to_session_map
        assert 1 in mock_state.stream_to_session_map

        cleanup_effects = [e for e in effects if isinstance(e, CleanupH3Stream)]
        assert sorted([e.stream_id for e in cleanup_effects]) == [0, 2, 3]

    def test_handle_cleanup_resources_closed_orphan_streams(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mocker: MockerFixture
    ) -> None:
        event = InternalCleanupResources()
        mock_stream_closed = mocker.MagicMock(spec=StreamStateDataInternal)
        mock_stream_closed.state = StreamState.CLOSED
        mock_state.sessions = {}
        mock_state.streams = {100: mock_stream_closed}
        mock_state.stream_to_session_map = {100: "orphan-sid"}

        effects = client_processor.handle_cleanup_resources(event=event, state=mock_state)

        assert 100 not in mock_state.streams
        assert 100 not in mock_state.stream_to_session_map
        cleanup_effects = [e for e in effects if isinstance(e, CleanupH3Stream)]
        assert [e.stream_id for e in cleanup_effects] == [100]

    def test_handle_cleanup_resources_race_conditions_and_empty_active(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mocker: MockerFixture
    ) -> None:
        event = InternalCleanupResources()

        sess_no_ctrl = mocker.MagicMock(spec=SessionStateData)
        sess_no_ctrl.state = SessionState.CLOSED
        sess_no_ctrl.control_stream_id = None
        sess_no_ctrl.active_streams = {10}

        sess_empty_streams = mocker.MagicMock(spec=SessionStateData)
        sess_empty_streams.state = SessionState.CLOSED
        sess_empty_streams.control_stream_id = 99
        sess_empty_streams.active_streams = set()

        mock_state.sessions = {"no-ctrl": sess_no_ctrl, "empty-streams": sess_empty_streams}
        mock_state.streams = {}
        mock_state.stream_to_session_map = {99: "empty-streams", 10: "no-ctrl"}

        effects = client_processor.handle_cleanup_resources(event=event, state=mock_state)

        assert "no-ctrl" not in mock_state.sessions
        assert "empty-streams" not in mock_state.sessions

        cleanup_ids = sorted([e.stream_id for e in effects if isinstance(e, CleanupH3Stream)])
        assert cleanup_ids == [10, 99]

    def test_handle_cleanup_resources_race_condition_simulation(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mocker: MockerFixture
    ) -> None:
        event = InternalCleanupResources()

        mock_dict = MagicMock()
        mock_dict.items.return_value = [("race-sid", mocker.MagicMock(state=SessionState.CLOSED))]
        mock_dict.pop.return_value = None

        mock_state.sessions = mock_dict
        mock_state.streams = {}

        effects = client_processor.handle_cleanup_resources(event=event, state=mock_state)

        assert not effects
        mock_dict.pop.assert_called_with("race-sid", None)

    def test_handle_connection_close(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        event = ConnectionClose(future=mock_future, error_code=1000, reason="Test close")
        mock_state.connection_state = ConnectionState.CONNECTED

        effects = client_processor.handle_connection_close(event=event, state=mock_state)

        assert mock_state.connection_state == ConnectionState.CLOSING
        assert mock_state.closed_at == 123456.0
        assert effects == [
            CloseQuicConnection(error_code=1000, reason="Test close"),
            CompleteUserFuture(future=mock_future),
        ]

    def test_handle_connection_close_already_closed(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        event = ConnectionClose(future=mock_future, error_code=1000, reason="Test close")
        mock_state.connection_state = ConnectionState.CLOSED

        effects = client_processor.handle_connection_close(event=event, state=mock_state)

        mock_get_timestamp.assert_not_called()
        assert mock_state.connection_state == ConnectionState.CLOSED
        assert effects == [CompleteUserFuture(future=mock_future)]

    def test_handle_connection_terminated(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mocker: MockerFixture
    ) -> None:
        event = TransportConnectionTerminated(error_code=500, reason_phrase="QUIC Down")
        mock_state.connection_state = ConnectionState.CONNECTED

        fut1 = mocker.create_autospec(asyncio.Future, instance=True)
        fut1.done.return_value = False

        mock_stream = mocker.MagicMock(spec=StreamStateDataInternal)
        mock_stream.pending_read_requests = deque()
        mock_stream.write_buffer = deque()

        mock_state.pending_create_session_futures = {4: fut1}
        mock_state.streams = {10: mock_stream}

        effects = client_processor.handle_connection_terminated(event=event, state=mock_state)

        assert mock_state.connection_state == ConnectionState.CLOSED
        assert not mock_state.pending_create_session_futures

        fail_effects = [e for e in effects if isinstance(e, FailUserFuture)]
        assert len(fail_effects) == 1
        assert fail_effects[0].future is fut1

        emit_effects = [e for e in effects if isinstance(e, EmitConnectionEvent)]
        assert len(emit_effects) == 1
        assert emit_effects[0].event_type == EventType.CONNECTION_CLOSED

    def test_handle_connection_terminated_already_closed(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        event = TransportConnectionTerminated(error_code=500, reason_phrase="QUIC Down")
        mock_state.connection_state = ConnectionState.CLOSED

        effects = client_processor.handle_connection_terminated(event=event, state=mock_state)

        assert effects == []

    def test_handle_connection_terminated_mixed_futures(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mocker: MockerFixture
    ) -> None:
        event = TransportConnectionTerminated(error_code=500, reason_phrase="QUIC Down")
        mock_state.connection_state = ConnectionState.CONNECTED

        fut_pending = mocker.create_autospec(asyncio.Future, instance=True)
        fut_pending.done.return_value = False
        fut_done = mocker.create_autospec(asyncio.Future, instance=True)
        fut_done.done.return_value = True

        read_pending = mocker.create_autospec(asyncio.Future, instance=True)
        read_pending.done.return_value = False
        read_done = mocker.create_autospec(asyncio.Future, instance=True)
        read_done.done.return_value = True

        write_pending = mocker.create_autospec(asyncio.Future, instance=True)
        write_pending.done.return_value = False
        write_done = mocker.create_autospec(asyncio.Future, instance=True)
        write_done.done.return_value = True

        mock_stream = mocker.MagicMock(spec=StreamStateDataInternal)
        mock_stream.pending_read_requests = deque([read_done, read_pending])
        mock_stream.write_buffer = deque([(b"", write_done, False), (b"", write_pending, False)])

        mock_state.pending_create_session_futures = {4: fut_pending, 5: fut_done}
        mock_state.streams = {10: mock_stream}

        effects = client_processor.handle_connection_terminated(event=event, state=mock_state)

        fail_effects = [e for e in effects if isinstance(e, FailUserFuture)]
        failed_futures = {e.future for e in fail_effects}

        assert fut_pending in failed_futures
        assert fut_done not in failed_futures
        assert read_pending in failed_futures
        assert read_done not in failed_futures
        assert write_pending in failed_futures
        assert write_done not in failed_futures
        assert len(fail_effects) == 3

    def test_handle_create_session_client_not_connected(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        event = UserCreateSession(future=mock_future, path="/test", headers={":path": "/test"})
        mock_state.connection_state = ConnectionState.CONNECTING

        effects = client_processor.handle_create_session(event=event, state=mock_state)

        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert fail_effect.future is mock_future
        assert isinstance(fail_effect.exception, ConnectionError)
        assert fail_effect.exception.args[0] == "Cannot create session, connection state is connecting"

    def test_handle_create_session_client_success(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_config: MagicMock,
        mock_generate_session_id: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        event = UserCreateSession(future=mock_future, path="/test", headers={":path": "/test"})
        mock_state.connection_state = ConnectionState.CONNECTED

        effects = client_processor.handle_create_session(event=event, state=mock_state)

        assert effects == [
            CreateH3Session(
                session_id="mock-session-id-1", path="/test", headers={":path": "/test"}, create_future=mock_future
            )
        ]

        assert "mock-session-id-1" in mock_state.pending_session_configs
        init_data = mock_state.pending_session_configs["mock-session-id-1"]
        assert isinstance(init_data, SessionInitData)
        assert init_data.path == "/test"
        assert init_data.created_at == 123456.0

    def test_handle_create_session_server_fails(
        self, server_processor: ConnectionProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        event = UserCreateSession(future=mock_future, path="/test", headers={":path": "/test"})

        effects = server_processor.handle_create_session(event=event, state=mock_state)

        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert fail_effect.future is mock_future
        assert isinstance(fail_effect.exception, ProtocolError)
        assert fail_effect.exception.args[0] == "Server cannot create sessions using this method"

    def test_handle_get_connection_diagnostics(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        event = UserGetConnectionDiagnostics(future=mock_future)
        mock_state.sessions = {"a": 1, "b": 2}
        mock_state.streams = {"c": 3}

        effects = client_processor.handle_get_connection_diagnostics(event=event, state=mock_state)

        expected_diagnostics = {
            "connection_id": "test-conn-id",
            "state": ConnectionState.CONNECTED,
            "is_client": True,
            "connected_at": 123456.0,
            "closed_at": None,
            "max_datagram_size": 1200,
            "remote_max_datagram_frame_size": 1100,
            "session_count": 2,
            "stream_count": 1,
        }
        assert effects == [CompleteUserFuture(future=mock_future, value=expected_diagnostics)]

    def test_handle_goaway_received(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_get_timestamp: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        event = GoawayReceived()
        mock_state.connection_state = ConnectionState.CONNECTED
        session1 = mocker.MagicMock(spec=SessionStateData, control_stream_id=4)
        session1.state = SessionState.CONNECTED
        session2 = mocker.MagicMock(spec=SessionStateData, control_stream_id=8)
        session2.state = SessionState.CLOSED
        mock_state.sessions = {"sid-1": session1, "sid-2": session2}

        effects = client_processor.handle_goaway_received(event=event, state=mock_state)

        assert mock_state.connection_state == ConnectionState.CLOSING
        assert mock_state.closed_at == 123456.0
        assert session1.state == SessionState.DRAINING
        assert session2.state == SessionState.CLOSED
        assert effects == [
            SendH3Capsule(stream_id=4, capsule_type=constants.DRAIN_WEBTRANSPORT_SESSION_TYPE, capsule_data=b""),
            EmitSessionEvent(session_id="sid-1", event_type=EventType.SESSION_DRAINING, data={"session_id": "sid-1"}),
        ]

    def test_handle_goaway_received_already_closing(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mock_get_timestamp: MagicMock
    ) -> None:
        event = GoawayReceived()
        mock_state.connection_state = ConnectionState.CLOSING
        mock_state.sessions = {}

        effects = client_processor.handle_goaway_received(event=event, state=mock_state)

        mock_get_timestamp.assert_not_called()
        assert mock_state.connection_state == ConnectionState.CLOSING
        assert effects == []

    def test_handle_goaway_received_no_sessions(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mock_get_timestamp: MagicMock
    ) -> None:
        event = GoawayReceived()
        mock_state.connection_state = ConnectionState.CONNECTED
        mock_state.sessions = {}

        effects = client_processor.handle_goaway_received(event=event, state=mock_state)

        assert mock_state.connection_state == ConnectionState.CLOSING
        assert mock_state.closed_at == 123456.0
        assert effects == []

    def test_handle_graceful_close(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        event = UserConnectionGracefulClose(future=mock_future)
        mock_state.connection_state = ConnectionState.CONNECTED
        mock_state.local_goaway_sent = False

        effects = client_processor.handle_graceful_close(event=event, state=mock_state)

        assert mock_state.connection_state == ConnectionState.CLOSING
        assert mock_state.local_goaway_sent is True
        assert effects == [SendH3Goaway(), CompleteUserFuture(future=mock_future)]

    def test_handle_graceful_close_already_sent(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        event = UserConnectionGracefulClose(future=mock_future)
        mock_state.connection_state = ConnectionState.CLOSING
        mock_state.local_goaway_sent = True

        effects = client_processor.handle_graceful_close(event=event, state=mock_state)

        assert effects == [CompleteUserFuture(future=mock_future)]

    def test_handle_graceful_close_not_sent_but_closing(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        event = UserConnectionGracefulClose(future=mock_future)
        mock_state.connection_state = ConnectionState.CLOSING
        mock_state.local_goaway_sent = False

        effects = client_processor.handle_graceful_close(event=event, state=mock_state)

        assert mock_state.local_goaway_sent is True
        assert mock_state.connection_state == ConnectionState.CLOSING
        mock_get_timestamp.assert_not_called()
        assert effects == [SendH3Goaway(), CompleteUserFuture(future=mock_future)]

    def test_handle_headers_received_client_fail_404(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_get_timestamp: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        headers = {":status": "404"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_session = mocker.MagicMock(spec=SessionStateData)
        mock_session.state = SessionState.CONNECTING
        mock_state.stream_to_session_map = {4: "sid-1"}
        mock_state.sessions = {"sid-1": mock_session}
        mock_state.pending_create_session_futures = {4: mock_future}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert mock_session.state == SessionState.CLOSED
        assert mock_session.closed_at == 123456.0
        assert "sid-1" not in mock_state.sessions
        assert 4 not in mock_state.stream_to_session_map
        assert 4 not in mock_state.pending_create_session_futures
        assert len(effects) == 2
        assert effects[0] == EmitSessionEvent(
            session_id="sid-1",
            event_type=EventType.SESSION_CLOSED,
            data={
                "session_id": "sid-1",
                "error_code": ErrorCodes.H3_REQUEST_REJECTED,
                "reason": "Session creation failed with status 404",
            },
        )
        assert isinstance(effects[1], FailUserFuture)
        assert effects[1].future is mock_future
        assert isinstance(effects[1].exception, ConnectionError)

    def test_handle_headers_received_client_fail_404_future_done(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_get_timestamp: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        headers = {":status": "404"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_session = mocker.MagicMock(spec=SessionStateData)
        mock_session.state = SessionState.CONNECTING

        done_future = mocker.create_autospec(asyncio.Future, instance=True)
        done_future.done.return_value = True

        mock_state.stream_to_session_map = {4: "sid-1"}
        mock_state.sessions = {"sid-1": mock_session}
        mock_state.pending_create_session_futures = {4: done_future}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert len(effects) == 1
        assert isinstance(effects[0], EmitSessionEvent)
        assert effects[0].event_type == EventType.SESSION_CLOSED
        assert not any(isinstance(e, FailUserFuture) for e in effects)

    def test_handle_headers_received_client_fail_no_future(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_get_timestamp: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        headers = {":status": "404"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_session = mocker.MagicMock(spec=SessionStateData)
        mock_session.state = SessionState.CONNECTING
        mock_state.stream_to_session_map = {4: "sid-1"}
        mock_state.sessions = {"sid-1": mock_session}
        mock_state.pending_create_session_futures = {}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert len(effects) == 1
        assert isinstance(effects[0], EmitSessionEvent)
        assert effects[0].event_type == EventType.SESSION_CLOSED
        assert "sid-1" not in mock_state.sessions

    def test_handle_headers_received_client_future_already_done(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_get_timestamp: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        headers = {":status": "200"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_session = mocker.MagicMock(spec=SessionStateData)
        mock_session.state = SessionState.CONNECTING

        done_future = mocker.create_autospec(asyncio.Future, instance=True)
        done_future.done.return_value = True

        mock_state.stream_to_session_map = {4: "sid-1"}
        mock_state.sessions = {"sid-1": mock_session}
        mock_state.pending_create_session_futures = {4: done_future}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert mock_session.state == SessionState.CONNECTED
        assert 4 not in mock_state.pending_create_session_futures
        assert len(effects) == 1
        assert isinstance(effects[0], EmitSessionEvent)
        assert effects[0].event_type == EventType.SESSION_READY

    def test_handle_headers_received_client_no_future(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_get_timestamp: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        headers = {":status": "200"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_session = mocker.MagicMock(spec=SessionStateData)
        mock_session.state = SessionState.CONNECTING
        mock_state.stream_to_session_map = {4: "sid-1"}
        mock_state.sessions = {"sid-1": mock_session}
        mock_state.pending_create_session_futures = {}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert len(effects) == 1
        assert isinstance(effects[0], EmitSessionEvent)
        assert effects[0].event_type == EventType.SESSION_READY

    def test_handle_headers_received_client_session_data_missing(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        headers = {":status": "200"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.stream_to_session_map = {4: "sid-missing"}
        mock_state.sessions = {}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == []

    def test_handle_headers_received_client_success_200(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_get_timestamp: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        headers = {":status": "200"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_session = mocker.MagicMock(spec=SessionStateData)
        mock_session.state = SessionState.CONNECTING
        mock_state.stream_to_session_map = {4: "sid-1"}
        mock_state.sessions = {"sid-1": mock_session}
        mock_state.pending_create_session_futures = {4: mock_future}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert mock_session.state == SessionState.CONNECTED
        assert mock_session.ready_at == 123456.0
        assert 4 not in mock_state.pending_create_session_futures
        assert effects == [
            EmitSessionEvent(
                session_id="sid-1",
                event_type=EventType.SESSION_READY,
                data={
                    "session_id": "sid-1",
                    "ready_at": 123456.0,
                    "control_stream_id": mock_session.control_stream_id,
                    "path": mock_session.path,
                    "headers": mock_session.headers,
                },
            ),
            CompleteUserFuture(future=mock_future, value="sid-1"),
        ]

    def test_handle_headers_received_client_unknown_stream(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        headers = {":status": "200"}
        event = HeadersReceived(headers=headers, stream_id=99, stream_ended=False)
        mock_state.stream_to_session_map = {}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == []

    def test_handle_headers_received_client_wrong_session_state(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mocker: MockerFixture
    ) -> None:
        headers = {":status": "200"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_session = mocker.MagicMock(spec=SessionStateData)
        mock_session.state = SessionState.CONNECTED
        mock_state.stream_to_session_map = {4: "sid-1"}
        mock_state.sessions = {"sid-1": mock_session}

        effects = client_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == []

    def test_handle_headers_received_server_default_path(
        self,
        server_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_generate_session_id: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        headers = {":method": "CONNECT", ":protocol": "webtransport"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.connection_state = ConnectionState.CONNECTED

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert len(effects) == 1
        effect = effects[0]
        assert isinstance(effect, EmitSessionEvent)
        assert effect.data["path"] == "/"
        assert "mock-session-id-1" in mock_state.sessions
        assert mock_state.sessions["mock-session-id-1"].path == "/"

    def test_handle_headers_received_server_existing_stream(
        self, server_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        headers = {":method": "CONNECT"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.stream_to_session_map = {4: "sid-1"}

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == []

    def test_handle_headers_received_server_new_session(
        self,
        server_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_generate_session_id: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        headers = {":method": "CONNECT", ":protocol": "webtransport", ":path": "/chat"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.connection_state = ConnectionState.CONNECTED

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == [
            EmitSessionEvent(
                session_id="mock-session-id-1",
                event_type=EventType.SESSION_REQUEST,
                data={"session_id": "mock-session-id-1", "control_stream_id": 4, "path": "/chat", "headers": headers},
            )
        ]
        assert "mock-session-id-1" in mock_state.sessions
        assert mock_state.stream_to_session_map[4] == "mock-session-id-1"
        new_session = mock_state.sessions["mock-session-id-1"]
        assert isinstance(new_session, SessionStateData)
        assert new_session.state == SessionState.CONNECTING
        assert new_session.control_stream_id == 4

    def test_handle_headers_received_server_not_connected(
        self, server_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        headers = {":method": "CONNECT", ":protocol": "webtransport", ":path": "/chat"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.connection_state = ConnectionState.CONNECTING

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == [SendH3Headers(stream_id=4, status=429)]
        assert not mock_state.sessions

    def test_handle_headers_received_server_rejects_limit(
        self, server_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        headers = {":method": "CONNECT", ":protocol": "webtransport", ":path": "/chat"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.connection_state = ConnectionState.CONNECTED
        mock_state.sessions = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7, "h": 8, "i": 9, "j": 10}

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == [SendH3Headers(stream_id=4, status=429)]
        assert len(mock_state.sessions) == 10

    def test_handle_headers_received_server_rejects_wrong_method(
        self, server_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        headers = {":method": "GET", ":protocol": "webtransport"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.connection_state = ConnectionState.CONNECTED

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == [SendH3Headers(stream_id=4, status=400)]
        assert not mock_state.sessions

    def test_handle_headers_received_server_rejects_wrong_protocol(
        self, server_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        headers = {":method": "CONNECT", ":protocol": "http"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.connection_state = ConnectionState.CONNECTED

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert effects == [SendH3Headers(stream_id=4, status=400)]
        assert not mock_state.sessions

    def test_handle_headers_received_server_unlimited_sessions(
        self, server_processor: ConnectionProcessor, mock_state: MagicMock, mock_generate_session_id: MagicMock
    ) -> None:
        server_processor._config.max_sessions = 0
        headers = {":method": "CONNECT", ":protocol": "webtransport", ":path": "/chat"}
        event = HeadersReceived(headers=headers, stream_id=4, stream_ended=False)
        mock_state.connection_state = ConnectionState.CONNECTED
        mock_state.sessions = {str(i): i for i in range(100)}

        effects = server_processor.handle_headers_received(event=event, state=mock_state)

        assert isinstance(effects[0], EmitSessionEvent)
        assert len(mock_state.sessions) == 101
        assert "mock-session-id-1" in mock_state.sessions

    def test_handle_internal_bind_h3_session(
        self,
        client_processor: ConnectionProcessor,
        mock_state: MagicMock,
        mock_future: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        init_data = SessionInitData(path="/test", headers={":path": "/test"}, created_at=123456.0)
        mock_state.pending_session_configs = {"mock-session-id-1": init_data}

        event = InternalBindH3Session(session_id="mock-session-id-1", control_stream_id=4, future=mock_future)

        effects = client_processor.handle_internal_bind_h3_session(event=event, state=mock_state)

        assert not effects
        assert "mock-session-id-1" not in mock_state.pending_session_configs
        assert "mock-session-id-1" in mock_state.sessions
        assert mock_state.stream_to_session_map[4] == "mock-session-id-1"
        assert mock_state.pending_create_session_futures[4] is mock_future

        session = mock_state.sessions["mock-session-id-1"]
        assert session.state == SessionState.CONNECTING
        assert session.control_stream_id == 4

    def test_handle_internal_bind_h3_session_missing_config(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        mock_state.pending_session_configs = {}
        event = InternalBindH3Session(session_id="mock-session-id-1", control_stream_id=4, future=mock_future)

        effects = client_processor.handle_internal_bind_h3_session(event=event, state=mock_state)

        assert len(effects) == 1
        assert isinstance(effects[0], FailUserFuture)
        assert "Session init data for mock-session-id-1 not found" in str(effects[0].exception)

    def test_handle_internal_fail_h3_session(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        init_data = SessionInitData(path="/", headers={}, created_at=0.0)
        mock_state.pending_session_configs = {"mock-session-id-1": init_data}

        error = ValueError("H3 Error")
        event = InternalFailH3Session(session_id="mock-session-id-1", exception=error, future=mock_future)

        effects = client_processor.handle_internal_fail_h3_session(event=event, state=mock_state)

        assert len(effects) == 1
        assert isinstance(effects[0], FailUserFuture)
        assert effects[0].exception is error
        assert "mock-session-id-1" not in mock_state.pending_session_configs

    def test_handle_transport_parameters_received(
        self, client_processor: ConnectionProcessor, mock_state: MagicMock
    ) -> None:
        event = TransportQuicParametersReceived(remote_max_datagram_frame_size=1500)

        effects = client_processor.handle_transport_parameters_received(event=event, state=mock_state)

        assert effects == []
        assert mock_state.remote_max_datagram_frame_size == 1500
