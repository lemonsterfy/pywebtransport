"""Unit tests for the pywebtransport._protocol.utils module."""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport._protocol import utils as protocol_utils
from pywebtransport.constants import MAX_STREAM_ID, ErrorCodes
from pywebtransport.exceptions import ProtocolError
from pywebtransport.types import StreamDirection


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
    mock_validate = mocker.patch("pywebtransport._protocol.utils.validate_stream_id")

    direction = protocol_utils.get_stream_direction_from_id(stream_id=stream_id, is_client=is_client)

    mock_validate.assert_called_once_with(stream_id=stream_id)
    assert direction == expected_direction


def test_get_stream_direction_from_id_unreachable(mocker: MockerFixture) -> None:
    mocker.patch("pywebtransport._protocol.utils.validate_stream_id")
    mocker.patch("pywebtransport._protocol.utils.is_bidirectional_stream", return_value=False)
    mocker.patch("pywebtransport._protocol.utils.can_send_data_on_stream", return_value=None)

    with pytest.raises(AssertionError, match="Unreachable code: Invalid stream direction logic"):
        protocol_utils.get_stream_direction_from_id(stream_id=0, is_client=True)


@pytest.mark.parametrize(
    "http_code, expected_wt_code",
    [
        (ErrorCodes.WT_APPLICATION_ERROR_FIRST + 0, 0),
        (ErrorCodes.WT_APPLICATION_ERROR_FIRST + 29, 29),
        (ErrorCodes.WT_APPLICATION_ERROR_FIRST + 31, 30),
        (ErrorCodes.WT_APPLICATION_ERROR_FIRST + 12345 + (12345 // 30), 12345),
        (
            ErrorCodes.WT_APPLICATION_ERROR_FIRST + 0xFFFFFFFF + (0xFFFFFFFF // 30),
            0xFFFFFFFF,
        ),
    ],
)
def test_http_code_to_webtransport_code(http_code: int, expected_wt_code: int) -> None:
    result = protocol_utils.http_code_to_webtransport_code(http_error_code=http_code)
    assert result == expected_wt_code


@pytest.mark.parametrize(
    "invalid_code, match_msg",
    [
        (ErrorCodes.WT_APPLICATION_ERROR_FIRST - 1, "not in the WebTransport application range"),
        (ErrorCodes.WT_APPLICATION_ERROR_LAST + 1, "not in the WebTransport application range"),
        (ErrorCodes.WT_APPLICATION_ERROR_FIRST + 0x1E, "reserved codepoint"),
    ],
)
def test_http_code_to_webtransport_code_invalid(invalid_code: int, match_msg: str) -> None:
    with pytest.raises(ValueError, match=match_msg):
        protocol_utils.http_code_to_webtransport_code(http_error_code=invalid_code)


def test_internal_stream_checks() -> None:
    assert protocol_utils._is_server_initiated_stream(stream_id=1) is True
    assert protocol_utils._is_server_initiated_stream(stream_id=0) is False

    assert protocol_utils.is_unidirectional_stream(stream_id=2) is True
    assert protocol_utils.is_unidirectional_stream(stream_id=3) is True
    assert protocol_utils.is_unidirectional_stream(stream_id=0) is False

    assert protocol_utils.is_request_response_stream(stream_id=0) is True
    assert protocol_utils.is_request_response_stream(stream_id=4) is True
    assert protocol_utils.is_request_response_stream(stream_id=1) is False
    assert protocol_utils.is_request_response_stream(stream_id=2) is False


@pytest.mark.parametrize(
    "session_id, is_valid",
    [
        (0, True),
        (4, True),
        (100, True),
        (1, False),
        (2, False),
        (3, False),
        (5, False),
    ],
)
def test_validate_h3_session_id(session_id: int, is_valid: bool) -> None:
    if is_valid:
        protocol_utils.validate_h3_session_id(session_id=session_id)
    else:
        with pytest.raises(ProtocolError, match="Invalid Session ID format"):
            protocol_utils.validate_h3_session_id(session_id=session_id)


@pytest.mark.parametrize(
    "value, is_valid, exc_type",
    [
        ("some-valid-id", True, None),
        ("", False, ValueError),
        (None, False, TypeError),
        (123, False, TypeError),
    ],
)
def test_validate_session_id(value: Any, is_valid: bool, exc_type: type[Exception] | None) -> None:
    if is_valid:
        protocol_utils.validate_session_id(session_id=value)
    else:
        assert exc_type is not None
        with pytest.raises(exc_type):
            protocol_utils.validate_session_id(session_id=value)


@pytest.mark.parametrize(
    "value, is_valid, exc_type",
    [
        (0, True, None),
        (MAX_STREAM_ID, True, None),
        (-1, False, ValueError),
        (MAX_STREAM_ID + 1, False, ValueError),
        ("not-an-int", False, TypeError),
        (None, False, TypeError),
    ],
)
def test_validate_stream_id(value: Any, is_valid: bool, exc_type: type[Exception] | None) -> None:
    if is_valid:
        protocol_utils.validate_stream_id(stream_id=value)
    else:
        assert exc_type is not None
        with pytest.raises(exc_type):
            protocol_utils.validate_stream_id(stream_id=value)


@pytest.mark.parametrize(
    "app_error_code, expected_http_code",
    [
        (0, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 0),
        (29, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 29),
        (30, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 30 + 1),
        (12345, ErrorCodes.WT_APPLICATION_ERROR_FIRST + 12345 + (12345 // 30)),
        (
            0xFFFFFFFF,
            ErrorCodes.WT_APPLICATION_ERROR_FIRST + 0xFFFFFFFF + (0xFFFFFFFF // 30),
        ),
    ],
)
def test_webtransport_code_to_http_code(app_error_code: int, expected_http_code: int) -> None:
    result = protocol_utils.webtransport_code_to_http_code(app_error_code=app_error_code)
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
        protocol_utils.webtransport_code_to_http_code(app_error_code=invalid_code)
