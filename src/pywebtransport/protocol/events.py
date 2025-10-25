"""Internal event types used within the protocol layer."""

from __future__ import annotations

from dataclasses import dataclass

from pywebtransport.types import Headers, StreamId

__all__: list[str] = [
    "CapsuleReceived",
    "DatagramReceived",
    "H3Event",
    "HeadersReceived",
    "WebTransportStreamDataReceived",
]


class H3Event:
    """Represent the base class for all H3 protocol engine events."""


@dataclass(kw_only=True)
class CapsuleReceived(H3Event):
    """Represent an HTTP Capsule received on a stream."""

    capsule_data: bytes
    capsule_type: int
    stream_id: StreamId


@dataclass(kw_only=True)
class DatagramReceived(H3Event):
    """Represent a WebTransport datagram received."""

    data: bytes
    stream_id: StreamId


@dataclass(kw_only=True)
class HeadersReceived(H3Event):
    """Represent a HEADERS frame received on a stream."""

    headers: Headers
    stream_id: StreamId
    stream_ended: bool


@dataclass(kw_only=True)
class WebTransportStreamDataReceived(H3Event):
    """Represent raw data received on an established WebTransport stream."""

    data: bytes
    control_stream_id: StreamId
    stream_id: StreamId
    stream_ended: bool
