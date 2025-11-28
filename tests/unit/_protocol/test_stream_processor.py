"""Unit tests for the pywebtransport._protocol.stream_processor module."""

import asyncio
from collections import deque
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ServerConfig, StreamError, constants
from pywebtransport._protocol.events import (
    CompleteUserFuture,
    EmitStreamEvent,
    FailUserFuture,
    ResetQuicStream,
    SendH3Capsule,
    SendQuicData,
    StopQuicStream,
    TransportStreamReset,
    UserGetStreamDiagnostics,
    UserResetStream,
    UserSendStreamData,
    UserStopStream,
    UserStreamRead,
    WebTransportStreamDataReceived,
)
from pywebtransport._protocol.state import ProtocolState, SessionStateData, StreamStateData
from pywebtransport._protocol.stream_processor import StreamProcessor
from pywebtransport.constants import ErrorCodes
from pywebtransport.types import EventType, SessionState, StreamDirection, StreamState


@pytest.fixture
def client_processor(mock_client_config: MagicMock) -> StreamProcessor:
    return StreamProcessor(is_client=True, config=mock_client_config)


@pytest.fixture
def mock_buffer_cls(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("pywebtransport._protocol.stream_processor.Buffer", autospec=True)


@pytest.fixture
def mock_client_config(mocker: MockerFixture) -> MagicMock:
    config = mocker.create_autospec(ClientConfig, instance=True)
    config.max_stream_write_buffer = 1000
    config.max_total_pending_events = 100
    config.max_pending_events_per_session = 10
    config.flow_control_window_auto_scale = True
    config.flow_control_window_size = 100
    config.stream_flow_control_increment_uni = 5
    config.stream_flow_control_increment_bidi = 5
    return config


@pytest.fixture
def mock_ensure_bytes(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "pywebtransport._protocol.stream_processor.ensure_bytes",
        side_effect=lambda data: (data if isinstance(data, bytes) else str(data).encode("utf-8")),
    )


@pytest.fixture
def mock_future(mocker: MockerFixture) -> MagicMock:
    fut = mocker.create_autospec(asyncio.Future, instance=True)
    fut.done.return_value = False
    return fut


@pytest.fixture
def mock_get_timestamp(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("pywebtransport._protocol.stream_processor.get_timestamp", return_value=123456.0)


@pytest.fixture
def mock_http_to_wt_code(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("pywebtransport._protocol.stream_processor.http_code_to_webtransport_code", return_value=1234)


@pytest.fixture
def mock_server_config(mocker: MockerFixture) -> MagicMock:
    config = mocker.create_autospec(ServerConfig, instance=True)
    config.max_stream_write_buffer = 1000
    config.max_total_pending_events = 100
    config.max_pending_events_per_session = 10
    config.flow_control_window_auto_scale = True
    config.flow_control_window_size = 100
    config.stream_flow_control_increment_uni = 5
    config.stream_flow_control_increment_bidi = 5
    return config


@pytest.fixture
def mock_session_data(mocker: MockerFixture, mock_state: MagicMock) -> SessionStateData:
    session = mocker.create_autospec(SessionStateData, instance=True)
    session.session_id = "sid-1"
    session.control_stream_id = 0
    session.state = SessionState.CONNECTED
    session.peer_max_data = 1000
    session.local_data_sent = 0
    session.local_max_data = 100
    session.peer_data_sent = 51
    session.peer_streams_uni_opened = 0
    session.local_max_streams_uni = 10
    session.peer_streams_bidi_opened = 8
    session.local_max_streams_bidi = 10
    mock_state.sessions = {"sid-1": session}
    return session


@pytest.fixture
def mock_state(mocker: MockerFixture) -> MagicMock:
    state = mocker.create_autospec(ProtocolState, instance=True)
    state.sessions = {}
    state.streams = {}
    state.stream_to_session_map = {}
    state.early_event_buffer = {}
    state.early_event_count = 0
    return state


@pytest.fixture
def mock_stream_data(
    mocker: MockerFixture, mock_state: MagicMock, mock_session_data: SessionStateData
) -> StreamStateData:
    stream = mocker.create_autospec(StreamStateData, instance=True)
    stream.stream_id = 4
    stream.session_id = "sid-1"
    stream.state = StreamState.OPEN
    stream.bytes_sent = 0
    stream.bytes_received = 0
    stream.read_buffer = deque()
    stream.read_buffer_size = 0
    stream.pending_read_requests = deque()
    stream.write_buffer = deque()
    mock_state.streams = {4: stream}
    mock_state.stream_to_session_map = {4: "sid-1"}
    return stream


@pytest.fixture
def mock_wt_to_http_code(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("pywebtransport._protocol.stream_processor.webtransport_code_to_http_code", return_value=0x52E0)


@pytest.fixture
def server_processor(mock_server_config: MagicMock) -> StreamProcessor:
    return StreamProcessor(is_client=False, config=mock_server_config)


class TestStreamProcessor:
    def test_check_and_send_data_credit_autocredit_disabled(
        self, client_processor: StreamProcessor, mock_session_data: SessionStateData, mock_client_config: MagicMock
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = False
        effect = client_processor._check_and_send_data_credit(session_data=mock_session_data)
        assert effect is None

    def test_check_and_send_data_credit_no_increase(
        self, client_processor: StreamProcessor, mock_session_data: SessionStateData, mock_client_config: MagicMock
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = True
        mock_client_config.flow_control_window_size = 100
        mock_session_data.local_max_data = 100
        mock_session_data.peer_data_sent = 49
        effect = client_processor._check_and_send_data_credit(session_data=mock_session_data)
        assert effect is None
        assert mock_session_data.local_max_data == 100

    def test_check_and_send_data_credit_zero_window(
        self, client_processor: StreamProcessor, mock_session_data: SessionStateData, mock_client_config: MagicMock
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = True
        mock_client_config.flow_control_window_size = 0
        effect = client_processor._check_and_send_data_credit(session_data=mock_session_data)
        assert effect is None

    @pytest.mark.parametrize("is_uni", [True, False])
    def test_check_and_send_stream_credit_autocredit_disabled(
        self,
        client_processor: StreamProcessor,
        mock_session_data: SessionStateData,
        mock_client_config: MagicMock,
        is_uni: bool,
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = False
        effect = client_processor._check_and_send_stream_credit(
            session_data=mock_session_data, is_unidirectional=is_uni
        )
        assert effect is None

    def test_check_and_send_stream_credit_uni_increase(
        self,
        client_processor: StreamProcessor,
        mock_session_data: SessionStateData,
        mock_client_config: MagicMock,
        mock_buffer_cls: MagicMock,
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = True
        mock_client_config.stream_flow_control_increment_uni = 10
        mock_session_data.local_max_streams_uni = 10
        mock_session_data.peer_streams_uni_opened = 6

        effect = client_processor._check_and_send_stream_credit(session_data=mock_session_data, is_unidirectional=True)

        assert isinstance(effect, SendH3Capsule)
        assert effect.capsule_type == constants.WT_MAX_STREAMS_UNI_TYPE
        assert mock_session_data.local_max_streams_uni == 16

    def test_check_and_send_stream_credit_zero_target_window_uni(
        self, client_processor: StreamProcessor, mock_session_data: SessionStateData, mock_client_config: MagicMock
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = True
        mock_client_config.stream_flow_control_increment_uni = 0
        effect = client_processor._check_and_send_stream_credit(session_data=mock_session_data, is_unidirectional=True)
        assert effect is None

    @pytest.mark.parametrize("is_uni", [True, False])
    def test_check_and_send_stream_credit_zero_window(
        self,
        client_processor: StreamProcessor,
        mock_session_data: SessionStateData,
        mock_client_config: MagicMock,
        is_uni: bool,
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = True
        if is_uni:
            mock_client_config.stream_flow_control_increment_uni = 0
        else:
            mock_client_config.stream_flow_control_increment_bidi = 0
        effect = client_processor._check_and_send_stream_credit(
            session_data=mock_session_data, is_unidirectional=is_uni
        )
        assert effect is None

    def test_handle_get_stream_diagnostics_not_found(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        mock_state.streams = {}
        event = UserGetStreamDiagnostics(future=mock_future, stream_id=4)
        effects = client_processor.handle_get_stream_diagnostics(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)

    def test_handle_get_stream_diagnostics_success(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.read_buffer = deque([b"sensitive", b"data"])
        mock_stream_data.read_buffer_size = 13
        test_dict = {
            "stream_id": 4,
            "state": StreamState.OPEN,
            "read_buffer": deque([b"sensitive", b"data"]),
            "read_buffer_size": 13,
        }

        with patch(
            "pywebtransport._protocol.stream_processor.dataclasses.asdict", return_value=test_dict
        ) as mock_asdict:
            event = UserGetStreamDiagnostics(future=mock_future, stream_id=4)
            effects = client_processor.handle_get_stream_diagnostics(event=event, state=mock_state)

            mock_asdict.assert_called_once_with(mock_stream_data)
            assert len(effects) == 1
            assert isinstance(effects[0], CompleteUserFuture)
            result_value = effects[0].value
            assert result_value["read_buffer"] == b""
            assert result_value["read_buffer_size"] == 13

    def test_handle_reset_stream_empty_buffer(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_wt_to_http_code: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        mock_stream_data.state = StreamState.OPEN
        mock_stream_data.write_buffer = deque()
        event = UserResetStream(future=mock_future, stream_id=4, error_code=100)

        effects = client_processor.handle_reset_stream(event=event, state=mock_state)

        assert mock_stream_data.state == StreamState.RESET_SENT
        assert ResetQuicStream(stream_id=4, error_code=0x52E0) in effects
        assert CompleteUserFuture(future=mock_future) in effects

    def test_handle_reset_stream_fails_pending_writes(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_wt_to_http_code: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        write_future = mocker.create_autospec(asyncio.Future, instance=True)
        write_future.done.return_value = False
        mock_stream_data.write_buffer = deque([(b"data", write_future, False)])
        event = UserResetStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_reset_stream(event=event, state=mock_state)
        assert len(mock_stream_data.write_buffer) == 0
        fail_effect = next(e for e in effects if isinstance(e, FailUserFuture) and e.future is not mock_future)
        assert fail_effect.future is write_future
        assert isinstance(fail_effect.exception, StreamError)
        assert fail_effect.exception.error_code == 100

    def test_handle_reset_stream_not_found(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        mock_state.streams = {}
        event = UserResetStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_reset_stream(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)

    @pytest.mark.parametrize(
        "state_from, state_to",
        [
            (StreamState.OPEN, StreamState.RESET_SENT),
            (StreamState.HALF_CLOSED_REMOTE, StreamState.CLOSED),
            (StreamState.RESET_RECEIVED, StreamState.CLOSED),
        ],
    )
    def test_handle_reset_stream_state_transitions(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_wt_to_http_code: MagicMock,
        mock_get_timestamp: MagicMock,
        state_from: StreamState,
        state_to: StreamState,
    ) -> None:
        mock_stream_data.state = state_from
        event = UserResetStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_reset_stream(event=event, state=mock_state)
        mock_wt_to_http_code.assert_called_once_with(app_error_code=100)
        assert mock_stream_data.state == state_to
        assert mock_stream_data.closed_at == 123456.0
        assert mock_stream_data.close_code == 100
        assert ResetQuicStream(stream_id=4, error_code=0x52E0) in effects
        assert CompleteUserFuture(future=mock_future) in effects
        if state_to == StreamState.CLOSED:
            assert EmitStreamEvent(stream_id=4, event_type=EventType.STREAM_CLOSED, data={"stream_id": 4}) in effects

    @pytest.mark.parametrize("state", [StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED, StreamState.RESET_SENT])
    def test_handle_reset_stream_wrong_state_no_op(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        state: StreamState,
    ) -> None:
        mock_stream_data.state = state
        event = UserResetStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_reset_stream(event=event, state=mock_state)
        assert effects == [CompleteUserFuture(future=mock_future)]

    def test_handle_send_stream_data_appends_to_write_buffer(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        existing_future = mocker.create_autospec(asyncio.Future, instance=True)
        mock_stream_data.write_buffer = deque([(b"first", existing_future, False)])
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"second", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert effects == []
        assert len(mock_stream_data.write_buffer) == 2
        assert mock_stream_data.write_buffer[1] == (b"second", mock_future, False)

    def test_handle_send_stream_data_buffer_full(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_client_config: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_client_config.max_stream_write_buffer = 100
        existing_future = mocker.create_autospec(asyncio.Future, instance=True)
        mock_stream_data.write_buffer = deque([(b"a" * 90, existing_future, False)])
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"a" * 11, end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)
        assert "write buffer full" in fail_effect.exception.args[0]

    def test_handle_send_stream_data_empty_payload_no_fin(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_session_data: SessionStateData,
    ) -> None:
        mock_session_data.peer_max_data = 1000
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"", end_stream=False)

        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)

        assert effects == [
            SendQuicData(stream_id=4, data=b"", end_stream=False),
            CompleteUserFuture(future=mock_future),
        ]

    def test_handle_send_stream_data_fully_blocked(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_buffer_cls: MagicMock,
    ) -> None:
        mock_session_data.peer_max_data = 100
        mock_session_data.local_data_sent = 100
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert len(mock_stream_data.write_buffer) == 1
        assert any(isinstance(e, SendH3Capsule) and e.capsule_type == constants.WT_DATA_BLOCKED_TYPE for e in effects)

    def test_handle_send_stream_data_invalid_data_type(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_ensure_bytes: MagicMock,
    ) -> None:
        mock_ensure_bytes.side_effect = TypeError("test error")
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"test", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, TypeError)

    def test_handle_send_stream_data_not_found(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        mock_state.streams = {}
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)

    def test_handle_send_stream_data_partial_send_blocked(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_buffer_cls: MagicMock,
    ) -> None:
        mock_session_data.peer_max_data = 100
        mock_session_data.local_data_sent = 98
        available_credit = 2
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert SendQuicData(stream_id=4, data=b"he", end_stream=False) in effects
        assert any(isinstance(e, SendH3Capsule) and e.capsule_type == constants.WT_DATA_BLOCKED_TYPE for e in effects)
        assert mock_session_data.local_data_sent == 100
        assert mock_stream_data.bytes_sent == available_credit
        assert len(mock_stream_data.write_buffer) == 1
        assert mock_stream_data.write_buffer[0] == (b"llo", mock_future, False)

    def test_handle_send_stream_data_session_not_found(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_state.sessions = {}
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)
        assert "Session not found" in fail_effect.exception.args[0]

    def test_handle_send_stream_data_success_end_stream_half_closed(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.state = StreamState.HALF_CLOSED_REMOTE
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=True)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert mock_stream_data.state == StreamState.CLOSED
        assert EmitStreamEvent(stream_id=4, event_type=EventType.STREAM_CLOSED, data={"stream_id": 4}) in effects
        assert CompleteUserFuture(future=mock_future) in effects

    def test_handle_send_stream_data_success_end_stream_open(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.state = StreamState.OPEN
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=True)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert mock_stream_data.state == StreamState.HALF_CLOSED_LOCAL
        assert not any(isinstance(e, EmitStreamEvent) for e in effects)

    def test_handle_send_stream_data_success_fits_credit(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_session_data.peer_max_data = 1000
        mock_session_data.local_data_sent = 0
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert effects == [
            SendQuicData(stream_id=4, data=b"hello", end_stream=False),
            CompleteUserFuture(future=mock_future),
        ]
        assert mock_session_data.local_data_sent == 5
        assert mock_stream_data.bytes_sent == 5
        assert len(mock_stream_data.write_buffer) == 0

    @pytest.mark.parametrize("state", [StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED, StreamState.RESET_SENT])
    def test_handle_send_stream_data_wrong_state(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        state: StreamState,
    ) -> None:
        mock_stream_data.state = state
        event = UserSendStreamData(future=mock_future, stream_id=4, data=b"hello", end_stream=False)
        effects = client_processor.handle_send_stream_data(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)
        assert "is not writable" in fail_effect.exception.args[0]

    def test_handle_stop_stream_fails_pending_reads(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_wt_to_http_code: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        read_future = mocker.create_autospec(asyncio.Future, instance=True)
        read_future.done.return_value = False
        mock_stream_data.pending_read_requests = deque([read_future])
        event = UserStopStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_stop_stream(event=event, state=mock_state)
        assert len(mock_stream_data.pending_read_requests) == 0
        fail_effect = next(e for e in effects if isinstance(e, FailUserFuture) and e.future is not mock_future)
        assert fail_effect.future is read_future
        assert isinstance(fail_effect.exception, StreamError)
        assert fail_effect.exception.error_code == 100

    def test_handle_stop_stream_no_pending_reads(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_wt_to_http_code: MagicMock,
        mock_get_timestamp: MagicMock,
    ) -> None:
        mock_stream_data.state = StreamState.OPEN
        mock_stream_data.pending_read_requests = deque()
        event = UserStopStream(future=mock_future, stream_id=4, error_code=100)

        effects = client_processor.handle_stop_stream(event=event, state=mock_state)

        assert mock_stream_data.state == StreamState.RESET_RECEIVED
        assert CompleteUserFuture(future=mock_future) in effects

    def test_handle_stop_stream_not_found(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        mock_state.streams = {}
        event = UserStopStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_stop_stream(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)

    @pytest.mark.parametrize(
        "state_from, state_to",
        [
            (StreamState.OPEN, StreamState.RESET_RECEIVED),
            (StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED),
            (StreamState.RESET_SENT, StreamState.CLOSED),
        ],
    )
    def test_handle_stop_stream_state_transitions(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mock_wt_to_http_code: MagicMock,
        mock_get_timestamp: MagicMock,
        state_from: StreamState,
        state_to: StreamState,
    ) -> None:
        mock_stream_data.state = state_from
        event = UserStopStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_stop_stream(event=event, state=mock_state)
        mock_wt_to_http_code.assert_called_once_with(app_error_code=100)
        assert mock_stream_data.state == state_to
        assert mock_stream_data.closed_at == 123456.0
        assert mock_stream_data.close_code == 100
        assert StopQuicStream(stream_id=4, error_code=0x52E0) in effects
        assert CompleteUserFuture(future=mock_future) in effects
        if state_to == StreamState.CLOSED:
            assert EmitStreamEvent(stream_id=4, event_type=EventType.STREAM_CLOSED, data={"stream_id": 4}) in effects

    @pytest.mark.parametrize("state", [StreamState.HALF_CLOSED_REMOTE, StreamState.CLOSED, StreamState.RESET_RECEIVED])
    def test_handle_stop_stream_wrong_state_no_op(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        state: StreamState,
    ) -> None:
        mock_stream_data.state = state
        event = UserStopStream(future=mock_future, stream_id=4, error_code=100)
        effects = client_processor.handle_stop_stream(event=event, state=mock_state)
        assert effects == [CompleteUserFuture(future=mock_future)]

    def test_handle_stream_read_appends_pending_request(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.read_buffer = deque()
        mock_stream_data.read_buffer_size = 0
        mock_stream_data.state = StreamState.OPEN
        event = UserStreamRead(future=mock_future, stream_id=4, max_bytes=100)
        effects = client_processor.handle_stream_read(event=event, state=mock_state)
        assert effects == []
        assert len(mock_stream_data.pending_read_requests) == 1
        assert mock_stream_data.pending_read_requests[0] is mock_future

    def test_handle_stream_read_eof(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.read_buffer = deque()
        mock_stream_data.read_buffer_size = 0
        mock_stream_data.state = StreamState.HALF_CLOSED_REMOTE
        event = UserStreamRead(future=mock_future, stream_id=4, max_bytes=100)
        effects = client_processor.handle_stream_read(event=event, state=mock_state)
        assert effects == [CompleteUserFuture(future=mock_future, value=b"")]

    def test_handle_stream_read_fails_on_reset(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.read_buffer = deque()
        mock_stream_data.read_buffer_size = 0
        mock_stream_data.state = StreamState.RESET_RECEIVED
        event = UserStreamRead(future=mock_future, stream_id=4, max_bytes=100)
        effects = client_processor.handle_stream_read(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)
        assert "receive side closed" in fail_effect.exception.args[0]

    def test_handle_stream_read_not_found(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_future: MagicMock
    ) -> None:
        mock_state.streams = {}
        event = UserStreamRead(future=mock_future, stream_id=4, max_bytes=100)
        effects = client_processor.handle_stream_read(event=event, state=mock_state)
        assert len(effects) == 1
        fail_effect = effects[0]
        assert isinstance(fail_effect, FailUserFuture)
        assert isinstance(fail_effect.exception, StreamError)

    def test_handle_stream_read_reads_from_buffer(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.read_buffer = deque([b"hello", b" world"])
        mock_stream_data.read_buffer_size = 11
        event = UserStreamRead(future=mock_future, stream_id=4, max_bytes=5)
        effects = client_processor.handle_stream_read(event=event, state=mock_state)
        assert effects == [CompleteUserFuture(future=mock_future, value=b"hello")]
        assert list(mock_stream_data.read_buffer) == [b" world"]
        assert mock_stream_data.read_buffer_size == 6

    def test_handle_stream_read_reads_from_buffer_all(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.read_buffer = deque([b"hello", b" world"])
        mock_stream_data.read_buffer_size = 11
        event = UserStreamRead(future=mock_future, stream_id=4, max_bytes=0)
        effects = client_processor.handle_stream_read(event=event, state=mock_state)
        assert effects == [CompleteUserFuture(future=mock_future, value=b"hello world")]
        assert len(mock_stream_data.read_buffer) == 0
        assert mock_stream_data.read_buffer_size == 0

    def test_handle_transport_stream_reset_fails_pending_futures(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_http_to_wt_code: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        read_future = mocker.create_autospec(asyncio.Future, instance=True)
        read_future.done.return_value = False
        write_future = mocker.create_autospec(asyncio.Future, instance=True)
        write_future.done.return_value = False
        mock_stream_data.pending_read_requests = deque([read_future])
        mock_stream_data.write_buffer = deque([(b"data", write_future, False)])
        event = TransportStreamReset(stream_id=4, error_code=ErrorCodes.H3_NO_ERROR)

        effects = client_processor.handle_transport_stream_reset(event=event, state=mock_state)

        mock_http_to_wt_code.assert_not_called()
        assert mock_stream_data.close_code == ErrorCodes.H3_NO_ERROR
        assert len(mock_stream_data.pending_read_requests) == 0
        assert len(mock_stream_data.write_buffer) == 0
        failed_futures = {e.future for e in effects if isinstance(e, FailUserFuture)}
        assert failed_futures == {read_future, write_future}
        assert all(isinstance(e.exception, StreamError) for e in effects if isinstance(e, FailUserFuture))

    def test_handle_transport_stream_reset_maps_app_error(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_http_to_wt_code: MagicMock,
    ) -> None:
        event = TransportStreamReset(stream_id=4, error_code=ErrorCodes.WT_APPLICATION_ERROR_FIRST)

        effects = client_processor.handle_transport_stream_reset(event=event, state=mock_state)

        mock_http_to_wt_code.assert_called_once_with(http_error_code=ErrorCodes.WT_APPLICATION_ERROR_FIRST)
        assert mock_stream_data.close_code == 1234
        assert mock_stream_data.state == StreamState.CLOSED
        assert EmitStreamEvent(stream_id=4, event_type=EventType.STREAM_CLOSED, data={"stream_id": 4}) in effects

    def test_handle_transport_stream_reset_maps_http_error_value_error(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_http_to_wt_code: MagicMock,
    ) -> None:
        mock_http_to_wt_code.side_effect = ValueError("Invalid code")
        event = TransportStreamReset(stream_id=4, error_code=ErrorCodes.WT_APPLICATION_ERROR_FIRST)

        _ = client_processor.handle_transport_stream_reset(event=event, state=mock_state)

        assert mock_stream_data.close_code == ErrorCodes.WT_APPLICATION_ERROR_FIRST

    def test_handle_transport_stream_reset_maps_reserved_http_error(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_http_to_wt_code: MagicMock,
    ) -> None:
        mock_http_to_wt_code.side_effect = ValueError("test")
        event = TransportStreamReset(stream_id=4, error_code=ErrorCodes.WT_APPLICATION_ERROR_FIRST)

        _ = client_processor.handle_transport_stream_reset(event=event, state=mock_state)

        assert mock_stream_data.close_code == ErrorCodes.WT_APPLICATION_ERROR_FIRST

    def test_handle_transport_stream_reset_no_op_if_closed(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_stream_data: StreamStateData
    ) -> None:
        mock_stream_data.state = StreamState.CLOSED
        event = TransportStreamReset(stream_id=4, error_code=100)

        effects = client_processor.handle_transport_stream_reset(event=event, state=mock_state)

        assert effects == []

    def test_handle_transport_stream_reset_with_done_futures(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mocker: MockerFixture,
    ) -> None:
        read_future = mocker.create_autospec(asyncio.Future, instance=True)
        read_future.done.return_value = True
        write_future = mocker.create_autospec(asyncio.Future, instance=True)
        write_future.done.return_value = True
        mock_stream_data.pending_read_requests = deque([read_future])
        mock_stream_data.write_buffer = deque([(b"data", write_future, False)])
        event = TransportStreamReset(stream_id=4, error_code=ErrorCodes.H3_NO_ERROR)

        effects = client_processor.handle_transport_stream_reset(event=event, state=mock_state)

        assert not any(isinstance(e, FailUserFuture) for e in effects)

    def test_handle_webtransport_stream_data_autocredit_data(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_buffer_cls: MagicMock,
        mock_client_config: MagicMock,
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = True
        mock_client_config.flow_control_window_size = 100
        mock_session_data.local_max_data = 100
        mock_session_data.peer_data_sent = 51
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_session_data.local_max_data == 156
        assert any(isinstance(e, SendH3Capsule) and e.capsule_type == constants.WT_MAX_DATA_TYPE for e in effects)
        assert list(mock_stream_data.read_buffer) == [b"hello"]
        assert mock_stream_data.read_buffer_size == 5

    def test_handle_webtransport_stream_data_autocredit_data_disabled(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_client_config: MagicMock,
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = False
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert not any(isinstance(e, SendH3Capsule) for e in effects)

    def test_handle_webtransport_stream_data_autocredit_data_no_increase(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_client_config: MagicMock,
    ) -> None:
        mock_client_config.flow_control_window_auto_scale = True
        mock_client_config.flow_control_window_size = 100
        mock_session_data.local_max_data = 100
        mock_session_data.peer_data_sent = 40
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_session_data.local_max_data == 100
        assert not any(isinstance(e, SendH3Capsule) for e in effects)

    def test_handle_webtransport_stream_data_client_no_session_data(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_stream_data: StreamStateData
    ) -> None:
        mock_state.sessions = {}
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_stream_data.bytes_received == 0
        assert effects == []

    def test_handle_webtransport_stream_data_client_unknown_stream(
        self, client_processor: StreamProcessor, mock_state: MagicMock
    ) -> None:
        mock_state.streams = {}
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []

    def test_handle_webtransport_stream_data_end_stream_closes_half_local(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_get_timestamp: MagicMock,
    ) -> None:
        mock_stream_data.state = StreamState.HALF_CLOSED_LOCAL
        mock_stream_data.read_buffer = deque()
        mock_stream_data.read_buffer_size = 0
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=True)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_stream_data.state == StreamState.CLOSED
        assert mock_stream_data.closed_at == 123456.0
        assert EmitStreamEvent(stream_id=4, event_type=EventType.STREAM_CLOSED, data={"stream_id": 4}) in effects

    def test_handle_webtransport_stream_data_end_stream_data_pending(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
    ) -> None:
        mock_stream_data.state = StreamState.HALF_CLOSED_LOCAL
        mock_stream_data.read_buffer = deque([b"pending"])
        mock_stream_data.read_buffer_size = 7
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=True)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_stream_data.state == StreamState.HALF_CLOSED_REMOTE
        assert not any(isinstance(e, EmitStreamEvent) for e in effects)

    def test_handle_webtransport_stream_data_end_stream_open(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
    ) -> None:
        mock_stream_data.state = StreamState.OPEN
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=True)

        _ = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_stream_data.state == StreamState.HALF_CLOSED_REMOTE

    def test_handle_webtransport_stream_data_end_stream_wakes_pending_reads(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.state = StreamState.OPEN
        mock_stream_data.pending_read_requests = deque([mock_future])
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"", stream_ended=True)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert CompleteUserFuture(future=mock_future, value=b"") in effects
        assert len(mock_stream_data.pending_read_requests) == 0

    def test_handle_webtransport_stream_data_fulfills_pending_read(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.pending_read_requests = deque([mock_future])
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert CompleteUserFuture(future=mock_future, value=b"hello") in effects
        assert len(mock_stream_data.pending_read_requests) == 0
        assert len(mock_stream_data.read_buffer) == 0
        assert mock_stream_data.read_buffer_size == 0

    def test_handle_webtransport_stream_data_ignore_if_closed(
        self, client_processor: StreamProcessor, mock_state: MagicMock, mock_stream_data: StreamStateData
    ) -> None:
        mock_stream_data.state = StreamState.CLOSED
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []

    def test_handle_webtransport_stream_data_no_pending_reads(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
    ) -> None:
        mock_stream_data.pending_read_requests = deque()
        mock_stream_data.read_buffer = deque([b"existing"])
        mock_stream_data.read_buffer_size = 8
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        _ = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert len(mock_stream_data.read_buffer) == 2
        assert mock_stream_data.read_buffer_size == 13

    def test_handle_webtransport_stream_data_server_autocredit_streams(
        self,
        server_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_buffer_cls: MagicMock,
    ) -> None:
        mock_state.stream_to_session_map[0] = "sid-1"
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=0, data=b"hello", stream_ended=False)
        with patch(
            "pywebtransport._protocol.stream_processor.get_stream_direction_from_id",
            return_value=StreamDirection.BIDIRECTIONAL,
        ):
            effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_session_data.local_max_streams_bidi == 14
        assert any(
            isinstance(e, SendH3Capsule) and e.capsule_type == constants.WT_MAX_STREAMS_BIDI_TYPE for e in effects
        )

    def test_handle_webtransport_stream_data_server_autocredit_streams_no_increase(
        self,
        server_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_server_config: MagicMock,
    ) -> None:
        mock_server_config.flow_control_window_auto_scale = True
        mock_server_config.stream_flow_control_increment_bidi = 5
        mock_session_data.local_max_streams_bidi = 20
        mock_session_data.peer_streams_bidi_opened = 8
        mock_state.stream_to_session_map[0] = "sid-1"
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=0, data=b"hello", stream_ended=False)
        with patch(
            "pywebtransport._protocol.stream_processor.get_stream_direction_from_id",
            return_value=StreamDirection.BIDIRECTIONAL,
        ):
            effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert mock_session_data.local_max_streams_bidi == 20
        assert not any(
            isinstance(e, SendH3Capsule) and e.capsule_type == constants.WT_MAX_STREAMS_BIDI_TYPE for e in effects
        )

    def test_handle_webtransport_stream_data_server_creates_new_stream_bidi(
        self,
        server_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_get_timestamp: MagicMock,
    ) -> None:
        mock_state.streams = {}
        mock_state.stream_to_session_map[0] = "sid-1"
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=0, data=b"hello", stream_ended=False)
        with patch(
            "pywebtransport._protocol.stream_processor.get_stream_direction_from_id",
            return_value=StreamDirection.BIDIRECTIONAL,
        ) as mock_get_dir:
            effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)
            mock_get_dir.assert_called_once_with(stream_id=8, is_client=False)

        assert 8 in mock_state.streams
        new_stream = mock_state.streams[8]
        assert isinstance(new_stream, StreamStateData)
        assert new_stream.session_id == "sid-1"
        assert new_stream.direction == StreamDirection.BIDIRECTIONAL
        assert new_stream.bytes_received == 5
        assert list(new_stream.read_buffer) == [b"hello"]
        assert new_stream.read_buffer_size == 5
        assert mock_session_data.peer_streams_bidi_opened == 9
        assert (
            EmitStreamEvent(
                stream_id=8,
                event_type=EventType.STREAM_OPENED,
                data={"stream_id": 8, "session_id": "sid-1", "direction": StreamDirection.BIDIRECTIONAL},
            )
            in effects
        )

    def test_handle_webtransport_stream_data_server_creates_new_stream_uni(
        self,
        server_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_get_timestamp: MagicMock,
    ) -> None:
        mock_state.streams = {}
        mock_state.stream_to_session_map[0] = "sid-1"
        event = WebTransportStreamDataReceived(stream_id=10, control_stream_id=0, data=b"hello", stream_ended=False)
        with patch(
            "pywebtransport._protocol.stream_processor.get_stream_direction_from_id",
            return_value=StreamDirection.RECEIVE_ONLY,
        ) as mock_get_dir:
            effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)
            mock_get_dir.assert_called_once_with(stream_id=10, is_client=False)

        assert 10 in mock_state.streams
        new_stream = mock_state.streams[10]
        assert isinstance(new_stream, StreamStateData)
        assert new_stream.session_id == "sid-1"
        assert new_stream.direction == StreamDirection.RECEIVE_ONLY
        assert new_stream.bytes_received == 5
        assert list(new_stream.read_buffer) == [b"hello"]
        assert new_stream.read_buffer_size == 5
        assert mock_session_data.peer_streams_uni_opened == 1
        assert (
            EmitStreamEvent(
                stream_id=10,
                event_type=EventType.STREAM_OPENED,
                data={"stream_id": 10, "session_id": "sid-1", "direction": StreamDirection.RECEIVE_ONLY},
            )
            in effects
        )

    def test_handle_webtransport_stream_data_server_early_buffering(
        self, server_processor: StreamProcessor, mock_state: MagicMock, mock_get_timestamp: MagicMock
    ) -> None:
        mock_state.sessions = {}
        mock_state.stream_to_session_map = {}
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=99, data=b"hello", stream_ended=False)

        effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []
        assert mock_state.early_event_count == 1
        assert mock_state.early_event_buffer == {99: [(123456.0, event)]}

    def test_handle_webtransport_stream_data_server_early_buffering_global_full(
        self, server_processor: StreamProcessor, mock_state: MagicMock, mock_server_config: MagicMock
    ) -> None:
        mock_server_config.max_total_pending_events = 10
        mock_state.sessions = {}
        mock_state.stream_to_session_map = {}
        mock_state.early_event_count = 10
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=99, data=b"hello", stream_ended=False)

        effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == [ResetQuicStream(stream_id=8, error_code=constants.ErrorCodes.WT_BUFFERED_STREAM_REJECTED)]

    def test_handle_webtransport_stream_data_server_early_buffering_session_full(
        self, server_processor: StreamProcessor, mock_state: MagicMock, mock_server_config: MagicMock
    ) -> None:
        mock_server_config.max_total_pending_events = 100
        mock_server_config.max_pending_events_per_session = 1
        mock_state.sessions = {}
        mock_state.stream_to_session_map = {}
        mock_state.early_event_buffer = {99: ["existing_event"]}
        mock_state.early_event_count = 1
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=99, data=b"hello", stream_ended=False)

        effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == [ResetQuicStream(stream_id=8, error_code=constants.ErrorCodes.WT_BUFFERED_STREAM_REJECTED)]

    def test_handle_webtransport_stream_data_server_rejects_send_only(
        self, server_processor: StreamProcessor, mock_state: MagicMock, mock_session_data: SessionStateData
    ) -> None:
        mock_state.streams = {}
        mock_state.stream_to_session_map[0] = "sid-1"
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)
        with patch(
            "pywebtransport._protocol.stream_processor.get_stream_direction_from_id",
            return_value=StreamDirection.SEND_ONLY,
        ):
            effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []
        assert 4 not in mock_state.streams

    def test_handle_webtransport_stream_data_server_stream_limit_reached(
        self, server_processor: StreamProcessor, mock_state: MagicMock, mock_session_data: SessionStateData
    ) -> None:
        mock_state.streams = {}
        mock_state.stream_to_session_map[0] = "sid-1"
        mock_session_data.peer_streams_bidi_opened = 10
        mock_session_data.local_max_streams_bidi = 10
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=0, data=b"hello", stream_ended=False)
        with patch(
            "pywebtransport._protocol.stream_processor.get_stream_direction_from_id",
            return_value=StreamDirection.BIDIRECTIONAL,
        ):
            effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []
        assert 8 not in mock_state.streams

    def test_handle_webtransport_stream_data_server_stream_limit_reached_uni(
        self, server_processor: StreamProcessor, mock_state: MagicMock, mock_session_data: SessionStateData
    ) -> None:
        mock_state.streams = {}
        mock_state.stream_to_session_map[0] = "sid-1"
        mock_session_data.peer_streams_uni_opened = 10
        mock_session_data.local_max_streams_uni = 10
        event = WebTransportStreamDataReceived(stream_id=10, control_stream_id=0, data=b"hello", stream_ended=False)
        with patch(
            "pywebtransport._protocol.stream_processor.get_stream_direction_from_id",
            return_value=StreamDirection.RECEIVE_ONLY,
        ):
            effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []
        assert 10 not in mock_state.streams

    def test_handle_webtransport_stream_data_server_unknown_session(
        self, server_processor: StreamProcessor, mock_state: MagicMock
    ) -> None:
        mock_state.streams = {}
        mock_state.stream_to_session_map[0] = "sid-1"
        mock_state.sessions = {}
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []
        assert 8 not in mock_state.streams

    def test_handle_webtransport_stream_data_server_wrong_session_state(
        self, server_processor: StreamProcessor, mock_state: MagicMock, mock_session_data: SessionStateData
    ) -> None:
        mock_state.streams = {}
        mock_state.stream_to_session_map[0] = "sid-1"
        mock_session_data.state = SessionState.CONNECTING
        event = WebTransportStreamDataReceived(stream_id=8, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = server_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert effects == []
        assert 8 not in mock_state.streams

    def test_handle_webtransport_stream_data_skips_done_futures(
        self,
        client_processor: StreamProcessor,
        mock_state: MagicMock,
        mock_session_data: SessionStateData,
        mock_stream_data: StreamStateData,
        mock_future: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        done_future = mocker.create_autospec(asyncio.Future, instance=True)
        done_future.done.return_value = True
        mock_stream_data.pending_read_requests = deque([done_future, mock_future])
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"hello", stream_ended=False)

        effects = client_processor.handle_webtransport_stream_data(event=event, state=mock_state)

        assert CompleteUserFuture(future=mock_future, value=b"hello") in effects
        assert len(mock_stream_data.pending_read_requests) == 0
        assert len(mock_stream_data.read_buffer) == 0
        assert mock_stream_data.read_buffer_size == 0

    def test_read_from_buffer_aggregation(
        self, client_processor: StreamProcessor, mock_stream_data: StreamStateData
    ) -> None:
        mock_stream_data.read_buffer = deque([b"a", b"b", b"c"])
        mock_stream_data.read_buffer_size = 3

        data = client_processor._read_from_buffer(stream_data=mock_stream_data, max_bytes=2)

        assert data == b"ab"
        assert list(mock_stream_data.read_buffer) == [b"c"]
        assert mock_stream_data.read_buffer_size == 1

    def test_read_from_buffer_split(self, client_processor: StreamProcessor, mock_stream_data: StreamStateData) -> None:
        mock_stream_data.read_buffer = deque([b"hello"])
        mock_stream_data.read_buffer_size = 5

        data = client_processor._read_from_buffer(stream_data=mock_stream_data, max_bytes=2)

        assert data == b"he"
        assert list(mock_stream_data.read_buffer) == [b"llo"]
        assert mock_stream_data.read_buffer_size == 3
