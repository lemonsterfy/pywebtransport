"""Unit tests for the pywebtransport.protocol.session_info module."""

import pytest
from pytest_mock import MockerFixture

from pywebtransport.protocol import StreamInfo, WebTransportSessionInfo
from pywebtransport.types import SessionState, StreamDirection, StreamState


class TestStreamInfo:
    def test_initialization_with_required_fields(self) -> None:
        stream_info = StreamInfo(
            stream_id=4,
            session_id="test-session",
            direction=StreamDirection.BIDIRECTIONAL,
            state=StreamState.OPEN,
            created_at=1000.0,
        )

        assert stream_info.stream_id == 4
        assert stream_info.session_id == "test-session"
        assert stream_info.direction == StreamDirection.BIDIRECTIONAL
        assert stream_info.state == StreamState.OPEN
        assert stream_info.created_at == 1000.0
        assert stream_info.bytes_sent == 0
        assert stream_info.bytes_received == 0
        assert stream_info.closed_at is None
        assert stream_info.close_code is None
        assert stream_info.close_reason is None

    def test_str_representation_active(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.protocol.session_info.get_timestamp", return_value=1010.5)
        stream_info = StreamInfo(
            stream_id=8,
            session_id="s1",
            direction=StreamDirection.SEND_ONLY,
            state=StreamState.OPEN,
            created_at=1000.0,
            bytes_sent=100,
            bytes_received=50,
        )

        expected_str = "Stream 8 [open] direction=send_only session=s1 sent=100b recv=50b" " (active: 10.50s)"
        assert str(stream_info) == expected_str

    def test_str_representation_closed(self) -> None:
        stream_info = StreamInfo(
            stream_id=8,
            session_id="s1",
            direction=StreamDirection.SEND_ONLY,
            state=StreamState.CLOSED,
            created_at=1000.0,
            closed_at=1005.25,
        )

        expected_str = "Stream 8 [closed] direction=send_only session=s1 sent=0b recv=0b" " (duration: 5.25s)"
        assert str(stream_info) == expected_str

    def test_to_dict_conversion(self) -> None:
        stream_info = StreamInfo(
            stream_id=4,
            session_id="test-session",
            direction=StreamDirection.BIDIRECTIONAL,
            state=StreamState.OPEN,
            created_at=1000.0,
            bytes_sent=1024,
            bytes_received=512,
        )

        stream_dict = stream_info.to_dict()

        assert isinstance(stream_dict, dict)
        assert stream_dict["stream_id"] == 4
        assert stream_dict["session_id"] == "test-session"
        assert stream_dict["direction"] == StreamDirection.BIDIRECTIONAL
        assert stream_dict["bytes_sent"] == 1024
        assert stream_dict["closed_at"] is None


class TestWebTransportSessionInfo:
    def test_initialization_defaults(self) -> None:
        session_info = WebTransportSessionInfo(
            session_id="test-session",
            control_stream_id=0,
            state=SessionState.CONNECTING,
            path="/",
            created_at=2000.0,
        )

        assert session_info.session_id == "test-session"
        assert session_info.path == "/"
        assert session_info.headers == {}
        assert session_info.ready_at is None
        assert session_info.closed_at is None
        assert session_info.local_max_data == 0
        assert session_info.peer_max_streams_bidi == 0
        assert session_info.local_streams_uni_opened == 0

    @pytest.mark.parametrize(
        "ready_at, closed_at, timestamp, expected_duration_str",
        [
            (None, None, 0, ""),
            (2010.0, None, 2025.5, " (active: 15.50s)"),
            (2010.0, 2030.75, 0, " (duration: 20.75s)"),
        ],
    )
    def test_str_representation_scenarios(
        self,
        mocker: MockerFixture,
        ready_at: float | None,
        closed_at: float | None,
        timestamp: float,
        expected_duration_str: str,
    ) -> None:
        if timestamp > 0:
            mocker.patch(
                "pywebtransport.protocol.session_info.get_timestamp",
                return_value=timestamp,
            )
        session_info = WebTransportSessionInfo(
            session_id="s1",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/live",
            created_at=2000.0,
            ready_at=ready_at,
            closed_at=closed_at,
        )

        expected_str = f"Session s1 [connected] path=/live control_stream=0{expected_duration_str}"
        assert str(session_info) == expected_str

    def test_to_dict_conversion(self) -> None:
        headers = {"user-agent": "test-client"}
        session_info = WebTransportSessionInfo(
            session_id="test-session",
            control_stream_id=0,
            state=SessionState.CONNECTED,
            path="/",
            created_at=2000.0,
            headers=headers,
            ready_at=2001.0,
            local_max_data=1024,
            peer_streams_bidi_opened=5,
        )

        session_dict = session_info.to_dict()

        assert isinstance(session_dict, dict)
        assert session_dict["session_id"] == "test-session"
        assert session_dict["state"] == SessionState.CONNECTED
        assert session_dict["headers"] == headers
        assert session_dict["ready_at"] == 2001.0
        assert session_dict["local_max_data"] == 1024
        assert session_dict["peer_streams_bidi_opened"] == 5
        assert session_dict["peer_data_sent"] == 0
