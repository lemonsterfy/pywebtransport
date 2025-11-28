"""Core data types and interface protocols for the library."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncGenerator, AsyncIterator
from enum import StrEnum
from typing import Any, AsyncContextManager, Protocol, TypeAlias, runtime_checkable

__all__: list[str] = [
    "Address",
    "AsyncContextManager",
    "AsyncGenerator",
    "AsyncIterator",
    "AuthHandlerProtocol",
    "Buffer",
    "ConnectionId",
    "ConnectionState",
    "Data",
    "ErrorCode",
    "EventData",
    "EventType",
    "Future",
    "Headers",
    "MiddlewareProtocol",
    "Priority",
    "SSLContext",
    "Serializer",
    "SessionId",
    "SessionState",
    "StreamDirection",
    "StreamId",
    "StreamState",
    "Timeout",
    "Timestamp",
    "URL",
    "URLParts",
    "WebTransportProtocol",
    "Weight",
]


Address: TypeAlias = tuple[str, int]
Buffer: TypeAlias = bytes | bytearray | memoryview
ConnectionId: TypeAlias = str
Data: TypeAlias = bytes | bytearray | memoryview | str
ErrorCode: TypeAlias = int
EventData: TypeAlias = Any
Future: TypeAlias = asyncio.Future
Headers: TypeAlias = dict[str, str]
Priority: TypeAlias = int
SessionId: TypeAlias = str
SSLContext: TypeAlias = ssl.SSLContext
StreamId: TypeAlias = int
Timeout: TypeAlias = float | None
Timestamp: TypeAlias = float
URL: TypeAlias = str
URLParts: TypeAlias = tuple[str, int, str]
Weight: TypeAlias = int


@runtime_checkable
class AuthHandlerProtocol(Protocol):
    """A protocol for auth handlers."""

    async def __call__(self, *, headers: Headers) -> bool: ...


@runtime_checkable
class MiddlewareProtocol(Protocol):
    """A protocol for a middleware object."""

    async def __call__(self, *, session: Any) -> bool: ...


@runtime_checkable
class Serializer(Protocol):
    """A protocol for serializing and deserializing structured data."""

    def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any:
        """Deserialize bytes into an object."""
        ...

    def serialize(self, *, obj: Any) -> bytes:
        """Serialize an object into bytes."""
        ...


@runtime_checkable
class WebTransportProtocol(Protocol):
    """A protocol for the underlying WebTransport transport layer."""

    def connection_lost(self, exc: Exception | None) -> None:
        """Called when a connection is lost."""
        ...

    def connection_made(self, transport: Any) -> None:
        """Called when a connection is established."""
        ...

    def datagram_received(self, data: bytes, addr: Address) -> None:
        """Called when a datagram is received."""
        ...

    def error_received(self, exc: Exception) -> None:
        """Called when an error is received."""
        ...


class ConnectionState(StrEnum):
    """Enumeration of connection states."""

    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"
    DRAINING = "draining"


class EventType(StrEnum):
    """Enumeration of system event types."""

    CAPSULE_RECEIVED = "capsule_received"
    CONNECTION_CLOSED = "connection_closed"
    CONNECTION_ESTABLISHED = "connection_established"
    CONNECTION_FAILED = "connection_failed"
    CONNECTION_LOST = "connection_lost"
    DATAGRAM_ERROR = "datagram_error"
    DATAGRAM_RECEIVED = "datagram_received"
    DATAGRAM_SENT = "datagram_sent"
    PROTOCOL_ERROR = "protocol_error"
    SESSION_CLOSED = "session_closed"
    SESSION_DATA_BLOCKED = "session_data_blocked"
    SESSION_DRAINING = "session_draining"
    SESSION_MAX_DATA_UPDATED = "session_max_data_updated"
    SESSION_MAX_STREAMS_BIDI_UPDATED = "session_max_streams_bidi_updated"
    SESSION_MAX_STREAMS_UNI_UPDATED = "session_max_streams_uni_updated"
    SESSION_READY = "session_ready"
    SESSION_REQUEST = "session_request"
    SESSION_STREAMS_BLOCKED = "session_streams_blocked"
    SETTINGS_RECEIVED = "settings_received"
    STREAM_CLOSED = "stream_closed"
    STREAM_DATA_RECEIVED = "stream_data_received"
    STREAM_ERROR = "stream_error"
    STREAM_OPENED = "stream_opened"
    TIMEOUT_ERROR = "timeout_error"


class SessionState(StrEnum):
    """Enumeration of WebTransport session states."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    DRAINING = "draining"
    CLOSED = "closed"


class StreamDirection(StrEnum):
    """Enumeration of stream directions."""

    BIDIRECTIONAL = "bidirectional"
    SEND_ONLY = "send_only"
    RECEIVE_ONLY = "receive_only"


class StreamState(StrEnum):
    """Enumeration of WebTransport stream states."""

    OPEN = "open"
    HALF_CLOSED_LOCAL = "half_closed_local"
    HALF_CLOSED_REMOTE = "half_closed_remote"
    CLOSED = "closed"
    RESET_SENT = "reset_sent"
    RESET_RECEIVED = "reset_received"
