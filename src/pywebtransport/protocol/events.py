"""Internal event definitions for the WebTransport protocol layer."""

from __future__ import annotations

from dataclasses import dataclass

from pywebtransport.types import Headers, StreamId

__all__ = [
    "CapsuleReceived",
    "DatagramReceived",
    "H3Event",
    "HeadersReceived",
    "WebTransportStreamDataReceived",
]


class H3Event:
    """Base class for all H3 protocol engine events."""


@dataclass(kw_only=True)
class CapsuleReceived(H3Event):
    """Fired when an HTTP Capsule is received on a stream."""

    capsule_data: bytes
    capsule_type: int
    stream_id: StreamId


@dataclass(kw_only=True)
class DatagramReceived(H3Event):
    """Fired when a WebTransport datagram is received."""

    data: bytes
    stream_id: StreamId


@dataclass(kw_only=True)
class HeadersReceived(H3Event):
    """Fired when a HEADERS frame is received on a stream."""

    headers: Headers
    stream_id: StreamId
    stream_ended: bool


@dataclass(kw_only=True)
class WebTransportStreamDataReceived(H3Event):
    """Fired when raw data is received on an established WebTransport stream."""

    data: bytes
    session_id: int
    stream_id: StreamId
    stream_ended: bool
