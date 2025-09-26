"""WebTransport Session and Stream Information Data Classes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pywebtransport.types import Headers, SessionId, SessionState, StreamDirection, StreamId, StreamState
from pywebtransport.utils import get_timestamp

__all__ = ["StreamInfo", "WebTransportSessionInfo"]


@dataclass(kw_only=True)
class StreamInfo:
    """Represents stateful information about a single WebTransport stream."""

    stream_id: StreamId
    session_id: SessionId
    direction: StreamDirection
    state: StreamState
    created_at: float
    bytes_sent: int = 0
    bytes_received: int = 0
    closed_at: float | None = None
    close_code: int | None = None
    close_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the stream information to a dictionary."""
        return asdict(obj=self)

    def __str__(self) -> str:
        """Format stream information for protocol debugging."""
        duration = ""
        if self.closed_at:
            duration = f" (duration: {self.closed_at - self.created_at:.2f}s)"
        else:
            duration = f" (active: {get_timestamp() - self.created_at:.2f}s)"

        return (
            f"Stream {self.stream_id} [{self.state}] "
            f"direction={self.direction} session={self.session_id} "
            f"sent={self.bytes_sent}b recv={self.bytes_received}b{duration}"
        )


@dataclass(kw_only=True)
class WebTransportSessionInfo:
    """Represents stateful information about a WebTransport session."""

    session_id: SessionId
    stream_id: StreamId
    state: SessionState
    path: str
    created_at: float
    headers: Headers = field(default_factory=dict)
    ready_at: float | None = None
    closed_at: float | None = None
    close_code: int | None = None
    close_reason: str | None = None
    local_max_data: int = 0
    local_data_sent: int = 0
    peer_max_data: int = 0
    peer_data_sent: int = 0
    local_max_streams_bidi: int = 0
    local_streams_bidi_opened: int = 0
    peer_max_streams_bidi: int = 0
    peer_streams_bidi_opened: int = 0
    local_max_streams_uni: int = 0
    local_streams_uni_opened: int = 0
    peer_max_streams_uni: int = 0
    peer_streams_uni_opened: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert the session information to a dictionary."""
        return asdict(obj=self)

    def __str__(self) -> str:
        """Format session information for protocol debugging."""
        duration = ""
        if self.ready_at and self.closed_at:
            duration = f" (duration: {self.closed_at - self.ready_at:.2f}s)"
        elif self.ready_at:
            duration = f" (active: {get_timestamp() - self.ready_at:.2f}s)"

        return f"Session {self.session_id} [{self.state}] " f"path={self.path} stream={self.stream_id}{duration}"
