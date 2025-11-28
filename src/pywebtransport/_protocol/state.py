"""Internal state dataclasses for the protocol engine."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from pywebtransport.types import (
    ConnectionState,
    Future,
    Headers,
    SessionId,
    SessionState,
    StreamDirection,
    StreamId,
    StreamState,
)

__all__: list[str] = []


@dataclass(kw_only=True)
class StreamStateData:
    """Represent the complete state of a single WebTransport stream."""

    stream_id: StreamId
    session_id: SessionId
    direction: StreamDirection
    state: StreamState
    created_at: float

    bytes_sent: int = 0
    bytes_received: int = 0

    read_buffer: deque[bytes] = field(default_factory=deque)
    read_buffer_size: int = 0

    pending_read_requests: deque[Future[Any]] = field(default_factory=deque)
    write_buffer: deque[tuple[bytes, Future[Any], bool]] = field(default_factory=deque)

    close_code: int | None = None
    close_reason: str | None = None
    closed_at: float | None = None


@dataclass(kw_only=True)
class SessionStateData:
    """Represent the complete state of a single WebTransport session."""

    session_id: SessionId
    control_stream_id: StreamId
    state: SessionState
    path: str
    headers: Headers
    created_at: float

    local_max_data: int
    local_data_sent: int = 0
    peer_max_data: int
    peer_data_sent: int = 0

    local_max_streams_bidi: int
    local_streams_bidi_opened: int = 0
    peer_max_streams_bidi: int
    peer_streams_bidi_opened: int = 0

    local_max_streams_uni: int
    local_streams_uni_opened: int = 0
    peer_max_streams_uni: int
    peer_streams_uni_opened: int = 0

    pending_bidi_stream_futures: deque[Future[Any]] = field(default_factory=deque)
    pending_uni_stream_futures: deque[Future[Any]] = field(default_factory=deque)

    datagrams_sent: int = 0
    datagram_bytes_sent: int = 0
    datagrams_received: int = 0
    datagram_bytes_received: int = 0

    close_code: int | None = None
    close_reason: str | None = None
    closed_at: float | None = None
    ready_at: float | None = None


@dataclass(kw_only=True)
class ProtocolState:
    """Represent the single source of truth for an entire connection."""

    is_client: bool
    connection_state: ConnectionState
    max_datagram_size: int
    remote_max_datagram_frame_size: int = 0

    handshake_complete: bool = False
    peer_settings_received: bool = False

    sessions: dict[SessionId, SessionStateData] = field(default_factory=dict)
    streams: dict[StreamId, StreamStateData] = field(default_factory=dict)

    stream_to_session_map: dict[StreamId, SessionId] = field(default_factory=dict)
    pending_create_session_futures: dict[StreamId, Future[Any]] = field(default_factory=dict)

    early_event_buffer: dict[StreamId, list[tuple[float, Any]]] = field(default_factory=dict)
    early_event_count: int = 0

    peer_initial_max_data: int = 0
    peer_initial_max_streams_bidi: int = 0
    peer_initial_max_streams_uni: int = 0

    connected_at: float | None = None
    closed_at: float | None = None
