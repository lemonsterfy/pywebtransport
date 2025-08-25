"""
WebTransport Protocol Utility Functions.
"""

from __future__ import annotations

from typing import Any

from aioquic.quic.configuration import QuicConfiguration

from pywebtransport.constants import WebTransportConstants
from pywebtransport.types import ConnectionState, SessionState, StreamDirection, StreamId
from pywebtransport.utils import get_logger, validate_stream_id

__all__ = [
    "can_receive_data",
    "can_receive_data_on_stream",
    "can_send_data",
    "can_send_data_on_stream",
    "create_quic_configuration",
    "get_stream_direction_from_id",
    "is_bidirectional_stream",
    "is_client_initiated_stream",
    "is_server_initiated_stream",
    "is_unidirectional_stream",
]

logger = get_logger("protocol.utils")


def can_receive_data(connection_state: ConnectionState, session_state: SessionState) -> bool:
    """Check if data can be received based on connection and session states."""
    return connection_state == ConnectionState.CONNECTED and session_state in [
        SessionState.CONNECTED,
        SessionState.DRAINING,
    ]


def can_receive_data_on_stream(stream_id: StreamId, *, is_client: bool) -> bool:
    """Check if the local endpoint can receive data on a given stream."""
    if is_bidirectional_stream(stream_id):
        return True
    return (is_client and is_server_initiated_stream(stream_id)) or (
        not is_client and is_client_initiated_stream(stream_id)
    )


def can_send_data(connection_state: ConnectionState, session_state: SessionState) -> bool:
    """Check if data can be sent based on connection and session states."""
    return connection_state == ConnectionState.CONNECTED and session_state == SessionState.CONNECTED


def can_send_data_on_stream(stream_id: StreamId, *, is_client: bool) -> bool:
    """Check if the local endpoint can send data on a given stream."""
    if is_bidirectional_stream(stream_id):
        return True
    return (is_client and is_client_initiated_stream(stream_id)) or (
        not is_client and is_server_initiated_stream(stream_id)
    )


def create_quic_configuration(*, is_client: bool = True, **kwargs: Any) -> QuicConfiguration:
    """Create a QUIC configuration from keyword arguments."""
    config_params = {
        "alpn_protocols": kwargs.get("alpn_protocols", WebTransportConstants.DEFAULT_ALPN_PROTOCOLS),
        "max_datagram_frame_size": kwargs.get("max_datagram_size", WebTransportConstants.MAX_DATAGRAM_SIZE),
    }
    return QuicConfiguration(is_client=is_client, **config_params)


def get_stream_direction_from_id(stream_id: StreamId, *, is_client: bool) -> StreamDirection:
    """Determine the stream direction from its ID and the endpoint role."""
    validate_stream_id(stream_id)

    match (is_bidirectional_stream(stream_id), can_send_data_on_stream(stream_id, is_client=is_client)):
        case (True, _):
            return StreamDirection.BIDIRECTIONAL
        case (False, True):
            return StreamDirection.SEND_ONLY
        case (False, False):
            return StreamDirection.RECEIVE_ONLY
        case _:
            raise AssertionError("Unreachable code: Invalid stream direction logic")


def is_bidirectional_stream(stream_id: StreamId) -> bool:
    """Check if a stream is bidirectional."""
    return (stream_id & 0x2) == 0


def is_client_initiated_stream(stream_id: StreamId) -> bool:
    """Check if a stream was initiated by the client (stream IDs are even)."""
    return (stream_id & 0x1) == 0


def is_server_initiated_stream(stream_id: StreamId) -> bool:
    """Check if a stream was initiated by the server (stream IDs are odd)."""
    return (stream_id & 0x1) == 1


def is_unidirectional_stream(stream_id: StreamId) -> bool:
    """Check if a stream is unidirectional."""
    return (stream_id & 0x2) != 0
