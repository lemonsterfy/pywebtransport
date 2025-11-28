"""Unit tests for the pywebtransport._protocol.state module."""

import time
from collections import deque
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport._protocol.state import ProtocolState, SessionStateData, StreamStateData
from pywebtransport.types import ConnectionState, SessionState, StreamDirection, StreamState


@pytest.fixture
def mock_connection_state(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(ConnectionState, instance=True)


@pytest.fixture
def mock_session_state(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(SessionState, instance=True)


@pytest.fixture
def mock_stream_direction(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(StreamDirection, instance=True)


@pytest.fixture
def mock_stream_state(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(StreamState, instance=True)


def test_protocol_state_instantiation(mock_connection_state: MagicMock) -> None:
    start_time = time.monotonic()

    state = ProtocolState(
        is_client=True, connection_state=mock_connection_state, max_datagram_size=1200, connected_at=start_time
    )

    assert state.is_client is True
    assert state.connection_state is mock_connection_state
    assert state.max_datagram_size == 1200
    assert state.connected_at == start_time

    assert state.remote_max_datagram_frame_size == 0
    assert state.handshake_complete is False
    assert state.peer_settings_received is False
    assert state.early_event_count == 0
    assert state.peer_initial_max_data == 0
    assert state.closed_at is None

    assert state.sessions == {}
    assert state.streams == {}
    assert state.stream_to_session_map == {}
    assert state.pending_create_session_futures == {}
    assert state.early_event_buffer == {}


def test_session_state_data_instantiation(mock_session_state: MagicMock) -> None:
    start_time = time.monotonic()
    headers = {":path": "/test"}

    session = SessionStateData(
        session_id="session-1",
        control_stream_id=0,
        state=mock_session_state,
        path="/test",
        headers=headers,
        created_at=start_time,
        local_max_data=1024,
        peer_max_data=2048,
        local_max_streams_bidi=10,
        peer_max_streams_bidi=5,
        local_max_streams_uni=10,
        peer_max_streams_uni=5,
        ready_at=start_time,
    )

    assert session.session_id == "session-1"
    assert session.state is mock_session_state
    assert session.path == "/test"
    assert session.headers is headers
    assert session.created_at == start_time
    assert session.local_max_data == 1024
    assert session.peer_max_data == 2048
    assert session.ready_at == start_time

    assert session.local_data_sent == 0
    assert session.peer_data_sent == 0
    assert session.local_streams_bidi_opened == 0
    assert session.datagrams_sent == 0
    assert session.closed_at is None

    assert session.pending_bidi_stream_futures == deque()
    assert session.pending_uni_stream_futures == deque()


def test_state_mutable_defaults_are_unique(
    mock_connection_state: MagicMock,
    mock_session_state: MagicMock,
    mock_stream_state: MagicMock,
    mock_stream_direction: MagicMock,
) -> None:
    p1 = ProtocolState(is_client=True, connection_state=mock_connection_state, max_datagram_size=1200)
    p2 = ProtocolState(is_client=False, connection_state=mock_connection_state, max_datagram_size=1200)

    common_session_args: dict[str, Any] = {
        "state": mock_session_state,
        "path": "/",
        "headers": {},
        "created_at": 0.0,
        "local_max_data": 1,
        "peer_max_data": 1,
        "local_max_streams_bidi": 1,
        "peer_max_streams_bidi": 1,
        "local_max_streams_uni": 1,
        "peer_max_streams_uni": 1,
    }
    s1 = SessionStateData(session_id="s1", control_stream_id=0, **common_session_args)
    s2 = SessionStateData(session_id="s2", control_stream_id=4, **common_session_args)

    common_stream_args: dict[str, Any] = {
        "session_id": "s1",
        "direction": mock_stream_direction,
        "state": mock_stream_state,
        "created_at": 0.0,
    }
    st1 = StreamStateData(stream_id=0, **common_stream_args)
    st2 = StreamStateData(stream_id=4, **common_stream_args)

    assert p1.sessions is not p2.sessions
    assert p1.streams is not p2.streams
    assert p1.stream_to_session_map is not p2.stream_to_session_map
    assert p1.pending_create_session_futures is not p2.pending_create_session_futures
    assert p1.early_event_buffer is not p2.early_event_buffer

    assert s1.pending_bidi_stream_futures is not s2.pending_bidi_stream_futures
    assert s1.pending_uni_stream_futures is not s2.pending_uni_stream_futures

    assert st1.read_buffer is not st2.read_buffer
    assert st1.pending_read_requests is not st2.pending_read_requests
    assert st1.write_buffer is not st2.write_buffer


def test_stream_state_data_instantiation(mock_stream_state: MagicMock, mock_stream_direction: MagicMock) -> None:
    start_time = time.monotonic()

    stream = StreamStateData(
        stream_id=4,
        session_id="session-1",
        direction=mock_stream_direction,
        state=mock_stream_state,
        created_at=start_time,
        close_code=0,
        close_reason="test",
        closed_at=start_time,
    )

    assert stream.stream_id == 4
    assert stream.session_id == "session-1"
    assert stream.direction is mock_stream_direction
    assert stream.state is mock_stream_state
    assert stream.created_at == start_time
    assert stream.close_code == 0
    assert stream.close_reason == "test"
    assert stream.closed_at == start_time

    assert stream.bytes_sent == 0
    assert stream.bytes_received == 0

    assert stream.read_buffer == deque()
    assert stream.read_buffer_size == 0
    assert stream.pending_read_requests == deque()
    assert stream.write_buffer == deque()
