"""Internal events, commands, and effects for the protocol engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pywebtransport.types import (
    Data,
    ErrorCode,
    EventType,
    Future,
    Headers,
    SessionId,
    StreamId,
)

__all__: list[str] = []


class ProtocolEvent:
    """Base class for all events processed by the _WebTransportEngine."""


@dataclass(kw_only=True)
class InternalCleanupEarlyEvents(ProtocolEvent):
    """Internal command signaling the engine to clean up the early event buffer."""


@dataclass(kw_only=True)
class InternalCleanupResources(ProtocolEvent):
    """Internal command signaling the engine to garbage collect closed resources."""


@dataclass(kw_only=True)
class TransportConnectionTerminated(ProtocolEvent):
    """Event indicating the underlying QUIC connection was terminated."""

    error_code: ErrorCode
    reason_phrase: str


@dataclass(kw_only=True)
class TransportDatagramFrameReceived(ProtocolEvent):
    """Event for a raw datagram frame received from QUIC."""

    data: bytes


@dataclass(kw_only=True)
class TransportHandshakeCompleted(ProtocolEvent):
    """Event signaling QUIC handshake completion is processed."""


@dataclass(kw_only=True)
class TransportQuicParametersReceived(ProtocolEvent):
    """Event signaling peer's QUIC transport parameters are received."""

    remote_max_datagram_frame_size: int


@dataclass(kw_only=True)
class TransportQuicTimerFired(ProtocolEvent):
    """Event signaling the transport timer has fired."""


@dataclass(kw_only=True)
class TransportStreamDataReceived(ProtocolEvent):
    """Event for raw stream data received from QUIC."""

    data: bytes
    end_stream: bool
    stream_id: StreamId


@dataclass(kw_only=True)
class TransportStreamReset(ProtocolEvent):
    """Event for a stream reset received from QUIC."""

    error_code: ErrorCode
    stream_id: StreamId


class H3Event(ProtocolEvent):
    """Base class for all H3 protocol engine semantic events."""


@dataclass(kw_only=True)
class CapsuleReceived(H3Event):
    """Represent an HTTP Capsule received on a stream."""

    capsule_data: bytes
    capsule_type: int
    stream_id: StreamId


@dataclass(kw_only=True)
class ConnectStreamClosed(H3Event):
    """H3 event signaling the CONNECT stream was cleanly closed (FIN received)."""

    stream_id: StreamId


@dataclass(kw_only=True)
class DatagramReceived(H3Event):
    """Represent a WebTransport datagram received."""

    data: bytes
    stream_id: StreamId


@dataclass(kw_only=True)
class GoawayReceived(H3Event):
    """Represent an H3 GOAWAY frame received on the control stream."""


@dataclass(kw_only=True)
class HeadersReceived(H3Event):
    """Represent a HEADERS frame received on a stream."""

    headers: Headers
    stream_id: StreamId
    stream_ended: bool


@dataclass(kw_only=True)
class SettingsReceived(H3Event):
    """Represent an H3 SETTINGS frame received and parsed."""

    settings: dict[int, int]


@dataclass(kw_only=True)
class WebTransportStreamDataReceived(H3Event):
    """Represent semantic data received on an established WebTransport stream."""

    data: bytes
    control_stream_id: StreamId
    stream_id: StreamId
    stream_ended: bool


@dataclass(kw_only=True)
class UserEvent(ProtocolEvent):
    """Base class for commands originating from the user-facing API."""

    future: Future[Any]


@dataclass(kw_only=True)
class ConnectionClose(UserEvent):
    """User or internal command to close the entire connection."""

    error_code: ErrorCode
    reason: str | None


@dataclass(kw_only=True)
class UserAcceptSession(UserEvent):
    """User command to accept a pending session (server-only)."""

    session_id: SessionId


@dataclass(kw_only=True)
class UserCloseSession(UserEvent):
    """User command to close an active session."""

    session_id: SessionId
    error_code: ErrorCode
    reason: str | None


@dataclass(kw_only=True)
class UserConnectionGracefulClose(UserEvent):
    """User command to gracefully close the connection (sends GOAWAY)."""


@dataclass(kw_only=True)
class UserCreateSession(UserEvent):
    """User command to create a new WebTransport session (client-only)."""

    path: str
    headers: Headers


@dataclass(kw_only=True)
class UserCreateStream(UserEvent):
    """User command to create a new stream."""

    session_id: SessionId
    is_unidirectional: bool


@dataclass(kw_only=True)
class UserGetConnectionDiagnostics(UserEvent):
    """User command to get connection diagnostics."""


@dataclass(kw_only=True)
class UserGetSessionDiagnostics(UserEvent):
    """User command to get session diagnostics."""

    session_id: SessionId


@dataclass(kw_only=True)
class UserGetStreamDiagnostics(UserEvent):
    """User command to get stream diagnostics."""

    stream_id: StreamId


@dataclass(kw_only=True)
class UserGrantDataCredit(UserEvent):
    """User command to manually grant data credit."""

    session_id: SessionId
    max_data: int


@dataclass(kw_only=True)
class UserGrantStreamsCredit(UserEvent):
    """User command to manually grant stream credit."""

    session_id: SessionId
    max_streams: int
    is_unidirectional: bool


@dataclass(kw_only=True)
class UserRejectSession(UserEvent):
    """User command to reject a pending session (server-only)."""

    session_id: SessionId
    status_code: int


@dataclass(kw_only=True)
class UserResetStream(UserEvent):
    """User command to reset the sending side of a stream."""

    stream_id: StreamId
    error_code: ErrorCode


@dataclass(kw_only=True)
class UserSendDatagram(UserEvent):
    """User command to send a datagram."""

    session_id: SessionId
    data: Data


@dataclass(kw_only=True)
class UserSendStreamData(UserEvent):
    """User command to send data on a stream."""

    stream_id: StreamId
    data: Data
    end_stream: bool


@dataclass(kw_only=True)
class UserStopStream(UserEvent):
    """User command to stop the receiving side of a stream."""

    stream_id: StreamId
    error_code: ErrorCode


@dataclass(kw_only=True)
class UserStreamRead(UserEvent):
    """User command to read data from a stream."""

    stream_id: StreamId
    max_bytes: int


class Effect:
    """Base class for all side effects returned by the state machine."""


@dataclass(kw_only=True)
class CleanupH3Stream(Effect):
    """Effect instructing Engine to cleanup H3-level stream state."""

    stream_id: StreamId


@dataclass(kw_only=True)
class CloseQuicConnection(Effect):
    """Effect to close the entire QUIC connection."""

    error_code: ErrorCode
    reason: str | None


@dataclass(kw_only=True)
class CompleteUserFuture(Effect):
    """Effect to complete a user's future, optionally with a value."""

    future: Future[Any]
    value: Any = None


@dataclass(kw_only=True)
class CreateH3Session(Effect):
    """Effect instructing Engine to initiate H3 session creation."""

    session_id: SessionId
    path: str
    headers: Headers
    create_future: Future[Any]


@dataclass(kw_only=True)
class CreateQuicStream(Effect):
    """Effect instructing Adapter to create a new QUIC stream."""

    session_id: SessionId
    is_unidirectional: bool
    create_future: Future[Any]


@dataclass(kw_only=True)
class EmitConnectionEvent(Effect):
    """Effect to emit an event on the WebTransportConnection."""

    event_type: EventType
    data: dict[str, Any]


@dataclass(kw_only=True)
class EmitSessionEvent(Effect):
    """Effect to emit an event on the WebTransportSession."""

    session_id: SessionId
    event_type: EventType
    data: dict[str, Any]


@dataclass(kw_only=True)
class EmitStreamEvent(Effect):
    """Effect to emit an event on the WebTransportStream."""

    stream_id: StreamId
    event_type: EventType
    data: dict[str, Any]


@dataclass(kw_only=True)
class FailUserFuture(Effect):
    """Effect to fail a user's future with an exception."""

    future: Future[Any]
    exception: Exception


@dataclass(kw_only=True)
class LogH3Frame(Effect):
    """Effect instructing Adapter to log an H3-level frame."""

    category: str
    event: str
    data: dict[str, Any]


@dataclass(kw_only=True)
class RescheduleQuicTimer(Effect):
    """Effect instructing the Adapter to schedule the next QUIC timer."""


@dataclass(kw_only=True)
class ResetQuicStream(Effect):
    """Effect to reset the sending side of a QUIC stream."""

    stream_id: StreamId
    error_code: ErrorCode


@dataclass(kw_only=True)
class SendH3Capsule(Effect):
    """Effect instructing Engine to encode and send an H3 Capsule."""

    stream_id: StreamId
    capsule_type: int
    capsule_data: bytes


@dataclass(kw_only=True)
class SendH3Datagram(Effect):
    """Effect instructing Engine to encode and send an H3 Datagram."""

    stream_id: StreamId
    data: bytes


@dataclass(kw_only=True)
class SendH3Goaway(Effect):
    """Effect instructing Engine to encode and send an H3 GOAWAY frame."""


@dataclass(kw_only=True)
class SendH3Headers(Effect):
    """Effect instructing Engine to send simple H3 status headers."""

    stream_id: StreamId
    status: int
    end_stream: bool = True


@dataclass(kw_only=True)
class SendQuicData(Effect):
    """Effect to send data on a QUIC stream."""

    stream_id: StreamId
    data: bytes
    end_stream: bool = False


@dataclass(kw_only=True)
class SendQuicDatagram(Effect):
    """Effect to send a QUIC datagram frame."""

    data: bytes


@dataclass(kw_only=True)
class StopQuicStream(Effect):
    """Effect to stop the receiving side of a QUIC stream."""

    stream_id: StreamId
    error_code: ErrorCode


@dataclass(kw_only=True)
class TriggerQuicTimer(Effect):
    """Effect instructing the Adapter to handle the QUIC timer."""
