"""
PyWebTransport: A high-performance, async-native WebTransport implementation for Python.
"""

from .version import __version__
from .client import WebTransportClient
from .config import ClientConfig, ServerConfig
from .datagram import DatagramReliabilityLayer, WebTransportDatagramDuplexStream
from .events import Event, EventEmitter
from .exceptions import (
    AuthenticationError,
    CertificateError,
    ClientError,
    ConfigurationError,
    ConnectionError,
    DatagramError,
    FlowControlError,
    HandshakeError,
    ProtocolError,
    ServerError,
    SessionError,
    StreamError,
    TimeoutError,
    WebTransportError,
)
from .server import ServerApp, create_development_server
from .session import WebTransportSession
from .stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from .types import (
    Address,
    ConnectionState,
    EventType,
    Headers,
    SessionState,
    StreamDirection,
    StreamState,
    URL,
)

__all__ = [
    "__version__",
    # High-Level API (Client & Server)
    "ServerApp",
    "WebTransportClient",
    "create_development_server",
    # Core Primitives
    "DatagramReliabilityLayer",
    "WebTransportDatagramDuplexStream",
    "WebTransportReceiveStream",
    "WebTransportSendStream",
    "WebTransportSession",
    "WebTransportStream",
    # Configuration
    "ClientConfig",
    "ServerConfig",
    # Events
    "Event",
    "EventEmitter",
    # Core Enums & Types
    "Address",
    "ConnectionState",
    "EventType",
    "Headers",
    "SessionState",
    "StreamDirection",
    "StreamState",
    "URL",
    # Exceptions
    "AuthenticationError",
    "CertificateError",
    "ClientError",
    "ConfigurationError",
    "ConnectionError",
    "DatagramError",
    "FlowControlError",
    "HandshakeError",
    "ProtocolError",
    "ServerError",
    "SessionError",
    "StreamError",
    "TimeoutError",
    "WebTransportError",
]
