"""The canonical, async-native WebTransport stack for Python."""

from .client import WebTransportClient
from .config import ClientConfig, ServerConfig
from .datagram import StructuredDatagramTransport, WebTransportDatagramTransport
from .events import Event, EventEmitter
from .exceptions import (
    ClientError,
    ConfigurationError,
    ConnectionError,
    DatagramError,
    ProtocolError,
    ServerError,
    SessionError,
    StreamError,
    TimeoutError,
    WebTransportError,
)
from .server import ServerApp
from .session import WebTransportSession
from .stream import StructuredStream, WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from .types import URL, Address, Headers, Serializer
from .version import __version__

__all__: list[str] = [
    "Address",
    "ClientConfig",
    "ClientError",
    "ConfigurationError",
    "ConnectionError",
    "DatagramError",
    "Event",
    "EventEmitter",
    "Headers",
    "ProtocolError",
    "Serializer",
    "ServerApp",
    "ServerConfig",
    "ServerError",
    "SessionError",
    "StreamError",
    "StructuredDatagramTransport",
    "StructuredStream",
    "TimeoutError",
    "URL",
    "WebTransportClient",
    "WebTransportDatagramTransport",
    "WebTransportError",
    "WebTransportReceiveStream",
    "WebTransportSendStream",
    "WebTransportSession",
    "WebTransportStream",
    "__version__",
]
