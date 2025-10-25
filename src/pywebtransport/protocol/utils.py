"""Shared utility functions for the protocol implementation."""

from __future__ import annotations

from typing import Any

from pywebtransport.constants import MAX_STREAM_ID, ErrorCodes
from pywebtransport.types import StreamDirection, StreamId

__all__: list[str] = [
    "can_receive_data_on_stream",
    "can_send_data_on_stream",
    "get_stream_direction_from_id",
    "validate_session_id",
    "validate_stream_id",
    "webtransport_code_to_http_code",
]


def can_receive_data_on_stream(*, stream_id: StreamId, is_client: bool) -> bool:
    """Check if the local endpoint can receive data on a given stream."""
    if _is_bidirectional_stream(stream_id=stream_id):
        return True
    return (is_client and _is_server_initiated_stream(stream_id=stream_id)) or (
        not is_client and _is_client_initiated_stream(stream_id=stream_id)
    )


def can_send_data_on_stream(*, stream_id: StreamId, is_client: bool) -> bool:
    """Check if the local endpoint can send data on a given stream."""
    if _is_bidirectional_stream(stream_id=stream_id):
        return True
    return (is_client and _is_client_initiated_stream(stream_id=stream_id)) or (
        not is_client and _is_server_initiated_stream(stream_id=stream_id)
    )


def get_stream_direction_from_id(*, stream_id: StreamId, is_client: bool) -> StreamDirection:
    """Determine the stream direction from its ID and the endpoint role."""
    validate_stream_id(stream_id=stream_id)

    match (
        _is_bidirectional_stream(stream_id=stream_id),
        can_send_data_on_stream(stream_id=stream_id, is_client=is_client),
    ):
        case (True, _):
            return StreamDirection.BIDIRECTIONAL
        case (False, True):
            return StreamDirection.SEND_ONLY
        case (False, False):
            return StreamDirection.RECEIVE_ONLY
        case _:
            raise AssertionError("Unreachable code: Invalid stream direction logic")


def validate_session_id(*, session_id: Any) -> None:
    """Validate a WebTransport session ID."""
    if not isinstance(session_id, str):
        raise TypeError("Session ID must be a string")
    if not session_id:
        raise ValueError("Session ID cannot be empty")


def validate_stream_id(*, stream_id: Any) -> None:
    """Validate a WebTransport stream ID."""
    if not isinstance(stream_id, int):
        raise TypeError("Stream ID must be an integer")
    if not (0 <= stream_id <= MAX_STREAM_ID):
        raise ValueError(f"Stream ID {stream_id} out of valid range")


def webtransport_code_to_http_code(app_error_code: int) -> int:
    """Map a 32-bit WebTransport application error code to an HTTP/3 error code."""
    if not (0x0 <= app_error_code <= 0xFFFFFFFF):
        raise ValueError("Application error code must be a 32-bit unsigned integer.")

    return ErrorCodes.WT_APPLICATION_ERROR_FIRST + app_error_code + (app_error_code // 0x1E)


def _is_bidirectional_stream(*, stream_id: StreamId) -> bool:
    """Check if a stream is bidirectional."""
    return (stream_id & 0x2) == 0


def _is_client_initiated_stream(*, stream_id: StreamId) -> bool:
    """Check if a stream was initiated by the client (stream IDs are even)."""
    return (stream_id & 0x1) == 0


def _is_server_initiated_stream(*, stream_id: StreamId) -> bool:
    """Check if a stream was initiated by the server (stream IDs are odd)."""
    return (stream_id & 0x1) == 1


def _is_unidirectional_stream(*, stream_id: StreamId) -> bool:
    """Check if a stream is unidirectional."""
    return (stream_id & 0x2) != 0
