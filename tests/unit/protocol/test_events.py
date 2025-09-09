"""Unit tests for the pywebtransport.events module."""

import pytest

from pywebtransport.types import Headers, StreamId
from pywebtransport.protocol.events import (
    DatagramReceived,
    DataReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)


def test_h3event_creation() -> None:
    event = H3Event()

    assert isinstance(event, H3Event)


@pytest.mark.parametrize(
    "data, stream_id, stream_ended",
    [
        (b"some data", 0, True),
        (b"more data", 4, False),
        (b"", 1, True),
        (b"\x00\x01\x02", 99, False),
    ],
)
def test_data_received_event(data: bytes, stream_id: StreamId, stream_ended: bool) -> None:
    event = DataReceived(data=data, stream_id=stream_id, stream_ended=stream_ended)

    assert isinstance(event, H3Event)
    assert event.data == data
    assert event.stream_id == stream_id
    assert event.stream_ended is stream_ended


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
    "data, session_id, stream_id, stream_ended",
    [
        (b"stream data", 12345, 2, True),
        (b"more stream data", 54321, 6, False),
        (b"", 0, 10, True),
        (b"\x00", 999, 14, False),
    ],
)
def test_webtransport_stream_data_received_event(
    data: bytes, session_id: int, stream_id: StreamId, stream_ended: bool
) -> None:
    event = WebTransportStreamDataReceived(
        data=data,
        session_id=session_id,
        stream_id=stream_id,
        stream_ended=stream_ended,
    )

    assert isinstance(event, H3Event)
    assert event.data == data
    assert event.session_id == session_id
    assert event.stream_id == stream_id
    assert event.stream_ended is stream_ended
