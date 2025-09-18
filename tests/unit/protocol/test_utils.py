"""Unit tests for the pywebtransport.protocol.utils module."""

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionState, SessionState, StreamDirection
from pywebtransport.constants import (
    DEFAULT_ALPN_PROTOCOLS,
    DEFAULT_CONGESTION_CONTROL_ALGORITHM,
    DEFAULT_MAX_DATAGRAM_SIZE,
    ErrorCodes,
)
from pywebtransport.protocol import utils as protocol_utils


def test_create_quic_configuration(mocker: MockerFixture) -> None:
    mock_quic_config = mocker.patch("pywebtransport.protocol.utils.QuicConfiguration")

    protocol_utils.create_quic_configuration(
        is_client=True,
        alpn_protocols=DEFAULT_ALPN_PROTOCOLS,
        congestion_control_algorithm=DEFAULT_CONGESTION_CONTROL_ALGORITHM,
        max_datagram_size=DEFAULT_MAX_DATAGRAM_SIZE,
    )

    mock_quic_config.assert_called_once_with(
        is_client=True,
        alpn_protocols=DEFAULT_ALPN_PROTOCOLS,
        congestion_control_algorithm=DEFAULT_CONGESTION_CONTROL_ALGORITHM,
        max_datagram_frame_size=DEFAULT_MAX_DATAGRAM_SIZE,
    )

    mock_quic_config.reset_mock()
    custom_alpn = ["my-protocol"]
    protocol_utils.create_quic_configuration(
        is_client=False,
        alpn_protocols=custom_alpn,
        congestion_control_algorithm="cubic",
        max_datagram_size=1200,
    )

    mock_quic_config.assert_called_once_with(
        is_client=False,
        alpn_protocols=custom_alpn,
        congestion_control_algorithm="cubic",
        max_datagram_frame_size=1200,
    )


@pytest.mark.parametrize(
    "stream_id, is_client_initiated, is_server_initiated, is_bidi, is_uni",
    [
        (0, True, False, True, False),
        (1, False, True, True, False),
        (2, True, False, False, True),
        (3, False, True, False, True),
        (4, True, False, True, False),
        (5, False, True, True, False),
    ],
)
def test_stream_id_properties(
    stream_id: int,
    is_client_initiated: bool,
    is_server_initiated: bool,
    is_bidi: bool,
    is_uni: bool,
) -> None:
    assert protocol_utils.is_client_initiated_stream(stream_id=stream_id) == is_client_initiated
    assert protocol_utils.is_server_initiated_stream(stream_id=stream_id) == is_server_initiated
    assert protocol_utils.is_bidirectional_stream(stream_id=stream_id) == is_bidi
    assert protocol_utils.is_unidirectional_stream(stream_id=stream_id) == is_uni


@pytest.mark.parametrize(
    "connection_state, session_state, expected",
    [
        (ConnectionState.CONNECTED, SessionState.CONNECTED, True),
        (ConnectionState.CONNECTED, SessionState.CONNECTING, False),
        (ConnectionState.CONNECTING, SessionState.CONNECTED, False),
        (ConnectionState.CLOSED, SessionState.CLOSED, False),
    ],
)
def test_can_send_data(connection_state: ConnectionState, session_state: SessionState, expected: bool) -> None:
    assert protocol_utils.can_send_data(connection_state=connection_state, session_state=session_state) == expected


@pytest.mark.parametrize(
    "connection_state, session_state, expected",
    [
        (ConnectionState.CONNECTED, SessionState.CONNECTED, True),
        (ConnectionState.CONNECTED, SessionState.DRAINING, True),
        (ConnectionState.CONNECTED, SessionState.CONNECTING, False),
        (ConnectionState.CONNECTING, SessionState.CONNECTED, False),
        (ConnectionState.CLOSED, SessionState.CLOSED, False),
    ],
)
def test_can_receive_data(connection_state: ConnectionState, session_state: SessionState, expected: bool) -> None:
    assert protocol_utils.can_receive_data(connection_state=connection_state, session_state=session_state) == expected


@pytest.mark.parametrize(
    "stream_id, is_client, expected",
    [
        (0, True, True),
        (0, False, True),
        (1, True, True),
        (1, False, True),
        (2, True, True),
        (2, False, False),
        (3, True, False),
        (3, False, True),
    ],
)
def test_can_send_data_on_stream(stream_id: int, is_client: bool, expected: bool) -> None:
    assert protocol_utils.can_send_data_on_stream(stream_id=stream_id, is_client=is_client) == expected


@pytest.mark.parametrize(
    "stream_id, is_client, expected",
    [
        (0, True, True),
        (0, False, True),
        (1, True, True),
        (1, False, True),
        (2, True, False),
        (2, False, True),
        (3, True, True),
        (3, False, False),
    ],
)
def test_can_receive_data_on_stream(stream_id: int, is_client: bool, expected: bool) -> None:
    assert protocol_utils.can_receive_data_on_stream(stream_id=stream_id, is_client=is_client) == expected


@pytest.mark.parametrize(
    "stream_id, is_client, expected_direction",
    [
        (0, True, StreamDirection.BIDIRECTIONAL),
        (0, False, StreamDirection.BIDIRECTIONAL),
        (1, True, StreamDirection.BIDIRECTIONAL),
        (1, False, StreamDirection.BIDIRECTIONAL),
        (2, True, StreamDirection.SEND_ONLY),
        (2, False, StreamDirection.RECEIVE_ONLY),
        (3, True, StreamDirection.RECEIVE_ONLY),
        (3, False, StreamDirection.SEND_ONLY),
    ],
)
def test_get_stream_direction_from_id(
    mocker: MockerFixture,
    stream_id: int,
    is_client: bool,
    expected_direction: StreamDirection,
) -> None:
    mock_validate = mocker.patch("pywebtransport.protocol.utils.validate_stream_id")

    direction = protocol_utils.get_stream_direction_from_id(stream_id=stream_id, is_client=is_client)

    mock_validate.assert_called_once_with(stream_id=stream_id)
    assert direction == expected_direction


def test_get_stream_direction_from_id_unreachable(mocker: MockerFixture) -> None:
    mocker.patch("pywebtransport.protocol.utils.validate_stream_id")
    mocker.patch("pywebtransport.protocol.utils.is_bidirectional_stream", return_value=None)

    with pytest.raises(AssertionError, match="Unreachable code: Invalid stream direction logic"):
        protocol_utils.get_stream_direction_from_id(stream_id=0, is_client=True)


@pytest.mark.parametrize(
    "app_error_code, expected_http_code",
    [
        (0, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 0),
        (29, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 29),
        (30, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 30 + 1),
        (12345, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 12345 + (12345 // 30)),
        (0xFFFFFFFF, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 0xFFFFFFFF + (0xFFFFFFFF // 30)),
    ],
)
def test_webtransport_code_to_http_code(app_error_code: int, expected_http_code: int) -> None:
    result = protocol_utils.webtransport_code_to_http_code(app_error_code)
    assert result == expected_http_code


@pytest.mark.parametrize(
    "invalid_code",
    [
        -1,
        0xFFFFFFFF + 1,
    ],
)
def test_webtransport_code_to_http_code_invalid_input(invalid_code: int) -> None:
    with pytest.raises(ValueError, match="Application error code must be a 32-bit unsigned integer."):
        protocol_utils.webtransport_code_to_http_code(invalid_code)
