"""
A high-performance, async-native WebTransport implementation for Python.
"""

import sys
import warnings

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
from .version import __version__

__all__ = [
    "Address",
    "AuthenticationError",
    "CertificateError",
    "ClientConfig",
    "ClientError",
    "ConfigurationError",
    "ConnectionError",
    "ConnectionState",
    "DatagramError",
    "DatagramReliabilityLayer",
    "Event",
    "EventEmitter",
    "EventType",
    "FlowControlError",
    "HandshakeError",
    "Headers",
    "ProtocolError",
    "ServerApp",
    "ServerConfig",
    "ServerError",
    "SessionError",
    "SessionState",
    "StreamDirection",
    "StreamError",
    "StreamState",
    "TimeoutError",
    "URL",
    "WebTransportClient",
    "WebTransportDatagramDuplexStream",
    "WebTransportError",
    "WebTransportReceiveStream",
    "WebTransportSendStream",
    "WebTransportSession",
    "WebTransportStream",
    "__version__",
    "create_development_server",
]

if sys.version_info < (3, 11):
    warnings.warn(
        "pywebtransport support for Python 3.10 and older is deprecated and will be removed in v0.2.0. "
        "Please upgrade to Python 3.11+.",
        DeprecationWarning,
        stacklevel=2,
    )
