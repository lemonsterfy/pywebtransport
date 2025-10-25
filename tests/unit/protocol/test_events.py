"""Unit tests for the pywebtransport.protocol.events module."""

import pytest

from pywebtransport import Headers
from pywebtransport.protocol.events import (
    CapsuleReceived,
    DatagramReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.types import StreamId


@pytest.mark.parametrize(
    "capsule_data, capsule_type, stream_id",
    [
        (b"some capsule data", 0, 0),
        (b"", 12345, 4),
        (b"\x00\x01\x02", 99, 8),
    ],
)
def test_capsule_received_event(capsule_data: bytes, capsule_type: int, stream_id: StreamId) -> None:
    event = CapsuleReceived(capsule_data=capsule_data, capsule_type=capsule_type, stream_id=stream_id)

    assert isinstance(event, H3Event)
    assert event.capsule_data == capsule_data
    assert event.capsule_type == capsule_type
    assert event.stream_id == stream_id


@pytest.mark.parametrize(
    "data, stream_id",
    [
        (b"a datagram", 1),
        (b"", 5),
        (b"another datagram with null bytes \x00", 10),
    ],
)
def test_datagram_received_event(data: bytes, stream_id: StreamId) -> None:
    event = DatagramReceived(data=data, stream_id=stream_id)

    assert isinstance(event, H3Event)
    assert event.data == data
    assert event.stream_id == stream_id


def test_h3event_creation() -> None:
    event = H3Event()

    assert isinstance(event, H3Event)


@pytest.mark.parametrize(
    "headers, stream_id, stream_ended",
    [
        ({"method": "GET", "path": "/"}, 0, False),
        ({"content-type": "application/json"}, 4, True),
        ({}, 8, False),
    ],
)
def test_headers_received_event(headers: Headers, stream_id: StreamId, stream_ended: bool) -> None:
    event = HeadersReceived(headers=headers, stream_id=stream_id, stream_ended=stream_ended)

    assert isinstance(event, H3Event)
    assert event.headers == headers
    assert event.stream_id == stream_id
    assert event.stream_ended is stream_ended


@pytest.mark.parametrize(
    "data, control_stream_id, stream_id, stream_ended",
    [
        (b"stream data", 0, 2, True),
        (b"more stream data", 0, 6, False),
        (b"", 4, 10, True),
        (b"\x00", 4, 14, False),
    ],
)
def test_webtransport_stream_data_received_event(
    data: bytes, control_stream_id: StreamId, stream_id: StreamId, stream_ended: bool
) -> None:
    event = WebTransportStreamDataReceived(
        data=data,
        control_stream_id=control_stream_id,
        stream_id=stream_id,
        stream_ended=stream_ended,
    )

    assert isinstance(event, H3Event)
    assert event.data == data
    assert event.control_stream_id == control_stream_id
    assert event.stream_id == stream_id
    assert event.stream_ended is stream_ended
