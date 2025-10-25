"""Unit tests for the pywebtransport.protocol._stream_tracker module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ProtocolError
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import FlowControlError
from pywebtransport.protocol import StreamInfo, WebTransportSessionInfo
from pywebtransport.protocol._session_tracker import _ProtocolSessionTracker
from pywebtransport.protocol._stream_tracker import _ProtocolStreamTracker
from pywebtransport.protocol.events import WebTransportStreamDataReceived
from pywebtransport.types import EventType, SessionState, StreamDirection, StreamState


@pytest.fixture
def mock_emit() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_h3_engine() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_quic(mocker: MockerFixture) -> MagicMock:
    mock = mocker.create_autospec(MagicMock, instance=True)
    mock._streams = {}
    mock.reset_stream = MagicMock()
    mock.stop_stream = MagicMock()
    return mock


@pytest.fixture
def mock_session_tracker() -> MagicMock:
    return MagicMock(spec=_ProtocolSessionTracker)


@pytest.fixture
def mock_trigger_transmission() -> MagicMock:
    return MagicMock()


@pytest.fixture
def tracker(
    mock_quic: MagicMock,
    mock_h3_engine: MagicMock,
    mock_session_tracker: MagicMock,
    mock_emit: AsyncMock,
    mock_trigger_transmission: MagicMock,
) -> _ProtocolStreamTracker:
    return _ProtocolStreamTracker(
        is_client=True,
        quic=mock_quic,
        h3=mock_h3_engine,
        stats={"streams_created": 0},
        session_tracker=mock_session_tracker,
        emit_event=mock_emit,
        trigger_transmission=mock_trigger_transmission,
    )


class TestStreamTrackerCleanup:
    def test_abort_receive_only_stream(self, tracker: _ProtocolStreamTracker, mock_quic: MagicMock) -> None:
        stream_mock = MagicMock()
        stream_mock.sender._reset_error_code = None
        stream_mock.receiver.is_finished = False
        mock_quic._streams[3] = stream_mock

        tracker.abort_stream(stream_id=3, error_code=123)
        mock_quic.reset_stream.assert_not_called()
        mock_quic.stop_stream.assert_called_once()

    def test_abort_stream(self, tracker: _ProtocolStreamTracker, mock_quic: MagicMock) -> None:
        stream_mock = MagicMock()
        stream_mock.sender._reset_error_code = None
        stream_mock.receiver.is_finished = False
        mock_quic._streams[4] = stream_mock

        tracker.abort_stream(stream_id=4, error_code=123)
        mock_quic.reset_stream.assert_called_once()
        mock_quic.stop_stream.assert_called_once()

    def test_abort_stream_invalid_app_error_code(self, tracker: _ProtocolStreamTracker, mock_quic: MagicMock) -> None:
        stream_mock = MagicMock()
        stream_mock.sender._reset_error_code = None
        stream_mock.receiver.is_finished = False
        mock_quic._streams[4] = stream_mock

        tracker.abort_stream(stream_id=4, error_code=2**32)
        mock_quic.reset_stream.assert_called_once_with(stream_id=4, error_code=2**32)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("is_tracked", [True, False])
    async def test_abort_stream_no_quic_stream(
        self,
        tracker: _ProtocolStreamTracker,
        mock_quic: MagicMock,
        mock_emit: AsyncMock,
        is_tracked: bool,
    ) -> None:
        stream_id = 99
        if is_tracked:
            tracker._streams[stream_id] = MagicMock()

        tracker.abort_stream(stream_id=stream_id, error_code=123)
        await asyncio.sleep(0)

        mock_quic.reset_stream.assert_not_called()
        if is_tracked:
            assert stream_id not in tracker._streams
            mock_emit.assert_awaited_once_with(EventType.STREAM_CLOSED, {"stream_id": stream_id})
        else:
            mock_emit.assert_not_awaited()

    def test_abort_stream_partially_closed(self, tracker: _ProtocolStreamTracker, mock_quic: MagicMock) -> None:
        stream_mock = MagicMock()
        stream_mock.sender._reset_error_code = 1
        stream_mock.receiver.is_finished = True
        mock_quic._streams[4] = stream_mock

        tracker.abort_stream(stream_id=4, error_code=123)
        mock_quic.reset_stream.assert_not_called()
        mock_quic.stop_stream.assert_not_called()

    def test_abort_stream_quic_layer_error(
        self, tracker: _ProtocolStreamTracker, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.protocol._stream_tracker.logger")
        stream_mock = MagicMock()
        stream_mock.sender._reset_error_code = None
        stream_mock.receiver.is_finished = False
        mock_quic._streams[4] = stream_mock
        mock_quic.reset_stream.side_effect = ValueError("error")

        tracker.abort_stream(stream_id=4, error_code=123)
        mock_logger.warning.assert_called_once()

    def test_abort_stream_unmappable_error_code(
        self, tracker: _ProtocolStreamTracker, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "pywebtransport.protocol.utils.webtransport_code_to_http_code",
            side_effect=ValueError,
        )
        stream_mock = MagicMock()
        stream_mock.sender._reset_error_code = None
        stream_mock.receiver.is_finished = False
        mock_quic._streams[4] = stream_mock
        tracker.abort_stream(stream_id=4, error_code=123)
        mock_quic.reset_stream.assert_called_once_with(stream_id=4, error_code=ErrorCodes.INTERNAL_ERROR)

    @pytest.mark.asyncio
    async def test_cleanup_streams_for_empty_session(self, tracker: _ProtocolStreamTracker) -> None:
        tracker._session_owned_streams["s1"] = set()
        tracker.cleanup_streams_for_session_by_id(session_id="s1")
        await asyncio.sleep(0)
        assert "s1" not in tracker._session_owned_streams

    @pytest.mark.asyncio
    async def test_cleanup_streams_for_session(self, tracker: _ProtocolStreamTracker) -> None:
        tracker._streams[4] = MagicMock()
        tracker._streams[8] = MagicMock()
        tracker._session_owned_streams["s1"] = {4, 8}
        tracker.cleanup_streams_for_session_by_id(session_id="s1")
        await asyncio.sleep(0)
        assert not tracker._session_owned_streams.get("s1")

    @pytest.mark.asyncio
    async def test_handle_stream_reset(self, tracker: _ProtocolStreamTracker, mock_emit: AsyncMock) -> None:
        tracker._streams[4] = MagicMock()
        tracker.handle_stream_reset(stream_id=4)
        await asyncio.sleep(0)
        mock_emit.assert_awaited_once_with(EventType.STREAM_CLOSED, {"stream_id": 4})

    @pytest.mark.asyncio
    async def test_handle_stream_reset_unknown_stream(
        self, tracker: _ProtocolStreamTracker, mock_emit: AsyncMock
    ) -> None:
        tracker.handle_stream_reset(stream_id=99)
        await asyncio.sleep(0)
        mock_emit.assert_not_awaited()


class TestStreamTrackerCreation:
    def test_create_stream_invalid_session(
        self, tracker: _ProtocolStreamTracker, mock_session_tracker: MagicMock
    ) -> None:
        mock_session_tracker.get_session_info.return_value = None
        with pytest.raises(ProtocolError, match="not found or not ready"):
            tracker.create_webtransport_stream(session_id="s1")

    @pytest.mark.parametrize("is_unidirectional", [True, False])
    def test_create_stream_flow_control_error(
        self,
        tracker: _ProtocolStreamTracker,
        mock_session_tracker: MagicMock,
        is_unidirectional: bool,
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=0.0,
        )
        session_info.peer_max_streams_uni = 0
        session_info.peer_max_streams_bidi = 0
        mock_session_tracker.get_session_info.return_value = session_info

        with pytest.raises(FlowControlError):
            tracker.create_webtransport_stream(session_id="s1", is_unidirectional=is_unidirectional)
        mock_session_tracker._send_blocked_capsule.assert_called_once()

    def test_create_stream_success(
        self,
        tracker: _ProtocolStreamTracker,
        mock_h3_engine: MagicMock,
        mock_session_tracker: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=0.0,
        )
        session_info.peer_max_streams_bidi = 1
        mock_session_tracker.get_session_info.return_value = session_info
        mock_h3_engine.create_webtransport_stream.return_value = 4

        stream_id = tracker.create_webtransport_stream(session_id="s1", is_unidirectional=False)

        assert stream_id == 4
        assert stream_id in tracker._streams
        mock_trigger_transmission.assert_called_once()

    def test_create_unidirectional_stream_success(
        self, tracker: _ProtocolStreamTracker, mock_session_tracker: MagicMock
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=0.0,
        )
        session_info.peer_max_streams_uni = 1
        mock_session_tracker.get_session_info.return_value = session_info

        tracker.create_webtransport_stream(session_id="s1", is_unidirectional=True)
        assert session_info.local_streams_uni_opened == 1


class TestStreamTrackerDataHandling:
    @pytest.mark.asyncio
    async def test_handle_data_no_session(
        self, tracker: _ProtocolStreamTracker, mock_session_tracker: MagicMock
    ) -> None:
        mock_session_tracker.get_session_by_control_stream.return_value = None
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"data", stream_ended=False)
        result = await tracker.handle_webtransport_stream_data(event=event)
        assert result is event

    @pytest.mark.asyncio
    async def test_handle_data_no_session_info(
        self, tracker: _ProtocolStreamTracker, mock_session_tracker: MagicMock
    ) -> None:
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = None
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"data", stream_ended=False)
        result = await tracker.handle_webtransport_stream_data(event=event)
        assert result is event

    @pytest.mark.asyncio
    async def test_handle_existing_stream_data(
        self,
        tracker: _ProtocolStreamTracker,
        mock_session_tracker: MagicMock,
        mock_emit: AsyncMock,
    ) -> None:
        tracker._data_stream_to_session[4] = "s1"
        tracker._streams[4] = MagicMock()
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = MagicMock()
        event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"data", stream_ended=True)

        await tracker.handle_webtransport_stream_data(event=event)

        mock_emit.assert_awaited_once()
        assert mock_emit.await_args is not None
        assert mock_emit.await_args.args[0] == EventType.STREAM_DATA_RECEIVED

    @pytest.mark.asyncio
    async def test_handle_new_bidi_stream_data_from_peer(
        self, tracker: _ProtocolStreamTracker, mock_session_tracker: MagicMock
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=0.0,
        )
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = session_info
        event = WebTransportStreamDataReceived(stream_id=1, control_stream_id=0, data=b"data", stream_ended=False)

        await tracker.handle_webtransport_stream_data(event=event)
        assert session_info.peer_streams_bidi_opened == 1

    @pytest.mark.asyncio
    async def test_handle_new_stream_data(
        self,
        tracker: _ProtocolStreamTracker,
        mock_session_tracker: MagicMock,
        mock_emit: AsyncMock,
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=0.0,
        )
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = session_info
        event = WebTransportStreamDataReceived(stream_id=5, control_stream_id=0, data=b"data", stream_ended=False)

        result = await tracker.handle_webtransport_stream_data(event=event)

        assert result is None
        assert 5 in tracker._streams
        mock_emit.assert_awaited_once()
        assert mock_emit.await_args is not None
        assert mock_emit.await_args.args[0] == EventType.STREAM_OPENED
        mock_session_tracker.update_local_flow_control.assert_awaited_once_with(session_id="s1")

    @pytest.mark.asyncio
    async def test_handle_new_uni_stream_data_from_peer(
        self, tracker: _ProtocolStreamTracker, mock_session_tracker: MagicMock
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=0.0,
        )
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = session_info
        event = WebTransportStreamDataReceived(stream_id=2, control_stream_id=0, data=b"data", stream_ended=False)

        await tracker.handle_webtransport_stream_data(event=event)
        assert session_info.peer_streams_uni_opened == 1


class TestStreamTrackerState:
    @pytest.mark.asyncio
    async def test_cleanup_stream(self, tracker: _ProtocolStreamTracker, mock_emit: AsyncMock) -> None:
        tracker._streams[4] = MagicMock()
        tracker._data_stream_to_session[4] = "s1"
        tracker._session_owned_streams["s1"] = {4, 8}

        tracker._cleanup_stream(stream_id=4)
        await asyncio.sleep(0)
        assert 4 not in tracker._streams
        assert 4 not in tracker._data_stream_to_session
        assert tracker._session_owned_streams["s1"] == {8}
        mock_emit.assert_awaited_once_with(EventType.STREAM_CLOSED, {"stream_id": 4})

    @pytest.mark.asyncio
    async def test_cleanup_stream_orphan_id(self, tracker: _ProtocolStreamTracker, mock_emit: AsyncMock) -> None:
        tracker._streams[4] = MagicMock()
        tracker._data_stream_to_session[4] = "s2"
        tracker._session_owned_streams["s1"] = {8}

        tracker._cleanup_stream(stream_id=4)
        await asyncio.sleep(0)
        mock_emit.assert_awaited_once_with(EventType.STREAM_CLOSED, {"stream_id": 4})

    @pytest.mark.parametrize(
        "initial_state, expected_state, cleanup_called",
        [
            (StreamState.OPEN, StreamState.HALF_CLOSED_LOCAL, False),
            (StreamState.HALF_CLOSED_REMOTE, StreamState.CLOSED, True),
        ],
    )
    def test_update_stream_state_on_send_end(
        self,
        tracker: _ProtocolStreamTracker,
        mocker: MockerFixture,
        initial_state: StreamState,
        expected_state: StreamState,
        cleanup_called: bool,
    ) -> None:
        stream_info = StreamInfo(
            stream_id=4,
            session_id="s1",
            direction=StreamDirection.BIDIRECTIONAL,
            state=initial_state,
            created_at=0.0,
        )
        tracker._streams[4] = stream_info
        mock_cleanup = mocker.patch.object(tracker, "_cleanup_stream")

        tracker.update_stream_state_on_send_end(stream_id=4)
        assert stream_info.state == expected_state
        if cleanup_called:
            mock_cleanup.assert_called_once_with(stream_id=4)
        else:
            mock_cleanup.assert_not_called()

    def test_update_stream_state_on_send_end_unknown_stream(self, tracker: _ProtocolStreamTracker) -> None:
        tracker.update_stream_state_on_send_end(stream_id=99)
