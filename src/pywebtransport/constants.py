"""
WebTransport Constants and Defaults.
"""

from __future__ import annotations

import ssl
from enum import IntEnum
from typing import Any, TypedDict

from pywebtransport.types import Headers
from pywebtransport.version import __version__

__all__ = [
    "ALPN_H3",
    "ALPN_H3_29",
    "ALPN_H3_32",
    "BIDIRECTIONAL_STREAM",
    "CLOSE_WEBTRANSPORT_SESSION_TYPE",
    "ClientConfigDefaults",
    "DEFAULT_ACCESS_LOG",
    "DEFAULT_ALPN_PROTOCOLS",
    "DEFAULT_AUTO_RECONNECT",
    "DEFAULT_BIND_HOST",
    "DEFAULT_BUFFER_SIZE",
    "DEFAULT_CERTFILE",
    "DEFAULT_CLIENT_MAX_CONNECTIONS",
    "DEFAULT_CLIENT_VERIFY_MODE",
    "DEFAULT_CLOSE_TIMEOUT",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_CONGESTION_CONTROL_ALGORITHM",
    "DEFAULT_CONNECTION_CLEANUP_INTERVAL",
    "DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL",
    "DEFAULT_CONNECTION_IDLE_TIMEOUT",
    "DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT",
    "DEFAULT_DEBUG",
    "DEFAULT_DEV_PORT",
    "DEFAULT_KEEP_ALIVE",
    "DEFAULT_KEYFILE",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_MAX_DATAGRAM_SIZE",
    "DEFAULT_MAX_INCOMING_STREAMS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_RETRY_DELAY",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_MAX_STREAMS",
    "DEFAULT_MAX_STREAMS_PER_CONNECTION",
    "DEFAULT_PORT",
    "DEFAULT_READ_TIMEOUT",
    "DEFAULT_RETRY_BACKOFF",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_SECURE_PORT",
    "DEFAULT_SERVER_MAX_CONNECTIONS",
    "DEFAULT_SERVER_VERIFY_MODE",
    "DEFAULT_SESSION_CLEANUP_INTERVAL",
    "DEFAULT_STREAM_CLEANUP_INTERVAL",
    "DEFAULT_STREAM_CREATION_TIMEOUT",
    "DEFAULT_VERSION",
    "DEFAULT_WEBTRANSPORT_PATH",
    "DEFAULT_WRITE_TIMEOUT",
    "DRAIN_WEBTRANSPORT_SESSION_TYPE",
    "DRAFT_VERSION",
    "Defaults",
    "ErrorCodes",
    "H3_DATA_FRAME_TYPE",
    "H3_FRAME_TYPE_HEADERS",
    "H3_FRAME_TYPE_SETTINGS",
    "H3_STREAM_TYPE_CONTROL",
    "H3_STREAM_TYPE_QPACK_DECODER",
    "H3_STREAM_TYPE_QPACK_ENCODER",
    "MAX_BUFFER_SIZE",
    "MAX_DATAGRAM_SIZE",
    "MAX_STREAM_ID",
    "ORIGIN_HEADER",
    "RECOMMENDED_BUFFER_SIZES",
    "SECURE_SCHEMES",
    "SEC_WEBTRANSPORT_HTTP3_DRAFT13",
    "SETTINGS_ENABLE_CONNECT_PROTOCOL",
    "SETTINGS_ENABLE_WEBTRANSPORT",
    "SETTINGS_H3_DATAGRAM",
    "SETTINGS_QPACK_BLOCKED_STREAMS",
    "SETTINGS_QPACK_MAX_TABLE_CAPACITY",
    "ServerConfigDefaults",
    "SUPPORTED_CONGESTION_CONTROL_ALGORITHMS",
    "SUPPORTED_VERSIONS",
    "UNIDIRECTIONAL_STREAM",
    "USER_AGENT_HEADER",
    "WEBTRANSPORT_H3_BIDI_STREAM_TYPE",
    "WEBTRANSPORT_H3_UNI_STREAM_TYPE",
    "WEBTRANSPORT_HEADER",
    "WEBTRANSPORT_MIME_TYPE",
    "WEBTRANSPORT_SCHEMES",
]


# General Web Standard Identifiers
ALPN_H3: str = "h3"
ALPN_H3_29: str = "h3-29"
ALPN_H3_32: str = "h3-32"
ORIGIN_HEADER: str = "origin"
SECURE_SCHEMES: tuple[str, str] = ("https", "wss")
USER_AGENT_HEADER: str = "user-agent"
WEBTRANSPORT_MIME_TYPE: str = "application/webtransport"
WEBTRANSPORT_SCHEMES: tuple[str, str] = ("https", "wss")


# Protocol-Defined Constants
BIDIRECTIONAL_STREAM: int = 0x0
CLOSE_WEBTRANSPORT_SESSION_TYPE: int = 0x2843
DRAIN_WEBTRANSPORT_SESSION_TYPE: int = 0x78AE
DRAFT_VERSION: int = 13
H3_DATA_FRAME_TYPE: int = 0x0
H3_FRAME_TYPE_HEADERS = 0x01
H3_FRAME_TYPE_SETTINGS = 0x04
H3_STREAM_TYPE_CONTROL = 0x00
H3_STREAM_TYPE_QPACK_DECODER = 0x03
H3_STREAM_TYPE_QPACK_ENCODER = 0x02
MAX_DATAGRAM_SIZE: int = 65535
MAX_STREAM_ID: int = 2**62 - 1
SEC_WEBTRANSPORT_HTTP3_DRAFT13: str = "webtransport"
SETTINGS_ENABLE_CONNECT_PROTOCOL = 0x8
SETTINGS_ENABLE_WEBTRANSPORT = 0x2B603742
SETTINGS_H3_DATAGRAM = 0x33
SETTINGS_QPACK_BLOCKED_STREAMS = 0x7
SETTINGS_QPACK_MAX_TABLE_CAPACITY = 0x1
UNIDIRECTIONAL_STREAM: int = 0x2
WEBTRANSPORT_H3_BIDI_STREAM_TYPE: int = 0x41
WEBTRANSPORT_H3_UNI_STREAM_TYPE: int = 0x54
WEBTRANSPORT_HEADER: str = "webtransport"


# Library Defaults & Utils
DEFAULT_ACCESS_LOG: bool = True
DEFAULT_ALPN_PROTOCOLS: tuple[str, str] = (ALPN_H3, ALPN_H3_29)
DEFAULT_AUTO_RECONNECT: bool = False
DEFAULT_BIND_HOST: str = "localhost"
DEFAULT_BUFFER_SIZE: int = 65536
DEFAULT_CERTFILE: str = ""
DEFAULT_CLIENT_MAX_CONNECTIONS: int = 100
DEFAULT_CLIENT_VERIFY_MODE: ssl.VerifyMode = ssl.CERT_REQUIRED
DEFAULT_CLOSE_TIMEOUT: float = 5.0
DEFAULT_CONNECT_TIMEOUT: float = 30.0
DEFAULT_CONGESTION_CONTROL_ALGORITHM: str = "cubic"
DEFAULT_CONNECTION_CLEANUP_INTERVAL: float = 30.0
DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL: float = 5.0
DEFAULT_CONNECTION_IDLE_TIMEOUT: float = 60.0
DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT: float = 30.0
DEFAULT_DEBUG: bool = False
DEFAULT_DEV_PORT: int = 4433
DEFAULT_KEEP_ALIVE: bool = True
DEFAULT_KEYFILE: str = ""
DEFAULT_LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_MAX_DATAGRAM_SIZE: int = 65535
DEFAULT_MAX_INCOMING_STREAMS: int = 100
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_MAX_RETRY_DELAY: float = 30.0
DEFAULT_MAX_SESSIONS: int = 10000
DEFAULT_MAX_STREAMS: int = 100
DEFAULT_MAX_STREAMS_PER_CONNECTION: int = 100
DEFAULT_PORT: int = 80
DEFAULT_READ_TIMEOUT: float = 60.0
DEFAULT_RETRY_BACKOFF: float = 2.0
DEFAULT_RETRY_DELAY: float = 1.0
DEFAULT_SECURE_PORT: int = 443
DEFAULT_SERVER_MAX_CONNECTIONS: int = 3000
DEFAULT_SERVER_VERIFY_MODE: ssl.VerifyMode = ssl.CERT_NONE
DEFAULT_SESSION_CLEANUP_INTERVAL: float = 60.0
DEFAULT_STREAM_CLEANUP_INTERVAL: float = 15.0
DEFAULT_STREAM_CREATION_TIMEOUT: float = 10.0
DEFAULT_VERSION: str = "h3"
DEFAULT_WEBTRANSPORT_PATH: str = "/webtransport"
DEFAULT_WRITE_TIMEOUT: float = 30.0
MAX_BUFFER_SIZE: int = 1024 * 1024
RECOMMENDED_BUFFER_SIZES: dict[str, int] = {"small": 8192, "medium": 65536, "large": 262144}
SUPPORTED_CONGESTION_CONTROL_ALGORITHMS: tuple[str, str] = ("reno", "cubic")
SUPPORTED_VERSIONS: tuple[str, ...] = ("draft-ietf-webtrans-http3-13", "h3")


class ErrorCodes(IntEnum):
    """A collection of standard WebTransport and QUIC error codes."""

    NO_ERROR = 0x0
    INTERNAL_ERROR = 0x1
    CONNECTION_REFUSED = 0x2
    FLOW_CONTROL_ERROR = 0x3
    STREAM_LIMIT_ERROR = 0x4
    STREAM_STATE_ERROR = 0x5
    FINAL_SIZE_ERROR = 0x6
    FRAME_ENCODING_ERROR = 0x7
    TRANSPORT_PARAMETER_ERROR = 0x8
    CONNECTION_ID_LIMIT_ERROR = 0x9
    PROTOCOL_VIOLATION = 0xA
    INVALID_TOKEN = 0xB
    APPLICATION_ERROR = 0xC
    CRYPTO_BUFFER_EXCEEDED = 0xD
    KEY_UPDATE_ERROR = 0xE
    AEAD_LIMIT_REACHED = 0xF
    NO_VIABLE_PATH = 0x10
    H3_DATAGRAM_ERROR = 0x33
    H3_NO_ERROR = 0x100
    H3_GENERAL_PROTOCOL_ERROR = 0x101
    H3_INTERNAL_ERROR = 0x102
    H3_STREAM_CREATION_ERROR = 0x103
    H3_CLOSED_CRITICAL_STREAM = 0x104
    H3_FRAME_UNEXPECTED = 0x105
    H3_FRAME_ERROR = 0x106
    H3_EXCESSIVE_LOAD = 0x107
    H3_ID_ERROR = 0x108
    H3_SETTINGS_ERROR = 0x109
    H3_MISSING_SETTINGS = 0x10A
    H3_REQUEST_REJECTED = 0x10B
    H3_REQUEST_CANCELLED = 0x10C
    H3_REQUEST_INCOMPLETE = 0x10D
    H3_MESSAGE_ERROR = 0x10E
    H3_CONNECT_ERROR = 0x10F
    H3_VERSION_FALLBACK = 0x110
    QPACK_DECOMPRESSION_FAILED = 0x200
    QPACK_ENCODER_STREAM_ERROR = 0x201
    QPACK_DECODER_STREAM_ERROR = 0x202
    APP_CONNECTION_TIMEOUT = 0x1000
    APP_AUTHENTICATION_FAILED = 0x1001
    APP_PERMISSION_DENIED = 0x1002
    APP_RESOURCE_EXHAUSTED = 0x1003
    APP_INVALID_REQUEST = 0x1004
    APP_SERVICE_UNAVAILABLE = 0x1005


class ClientConfigDefaults(TypedDict):
    """A type definition for the client configuration dictionary."""

    alpn_protocols: list[str]
    auto_reconnect: bool
    ca_certs: str | None
    certfile: str | None
    close_timeout: float
    congestion_control_algorithm: str
    connect_timeout: float
    connection_cleanup_interval: float
    connection_idle_check_interval: float
    connection_idle_timeout: float
    connection_keepalive_timeout: float
    debug: bool
    headers: Headers
    keep_alive: bool
    keyfile: str | None
    log_level: str
    max_connections: int
    max_datagram_size: int
    max_incoming_streams: int
    max_retries: int
    max_retry_delay: float
    max_stream_buffer_size: int
    max_streams: int
    read_timeout: float | None
    retry_backoff: float
    retry_delay: float
    stream_buffer_size: int
    stream_cleanup_interval: float
    stream_creation_timeout: float
    user_agent: str
    verify_mode: ssl.VerifyMode | None
    write_timeout: float | None


class ServerConfigDefaults(TypedDict):
    """A type definition for the server configuration dictionary."""

    access_log: bool
    alpn_protocols: list[str]
    bind_host: str
    bind_port: int
    ca_certs: str | None
    certfile: str
    congestion_control_algorithm: str
    connection_cleanup_interval: float
    connection_idle_check_interval: float
    connection_idle_timeout: float
    connection_keepalive_timeout: float
    debug: bool
    keep_alive: bool
    keyfile: str
    log_level: str
    max_connections: int
    max_datagram_size: int
    max_incoming_streams: int
    max_sessions: int
    max_stream_buffer_size: int
    max_streams_per_connection: int
    middleware: list[Any]
    read_timeout: float | None
    session_cleanup_interval: float
    stream_buffer_size: int
    stream_cleanup_interval: float
    verify_mode: ssl.VerifyMode
    write_timeout: float | None


_DEFAULT_CLIENT_CONFIG: ClientConfigDefaults = {
    "alpn_protocols": list(DEFAULT_ALPN_PROTOCOLS),
    "auto_reconnect": DEFAULT_AUTO_RECONNECT,
    "ca_certs": None,
    "certfile": None,
    "close_timeout": DEFAULT_CLOSE_TIMEOUT,
    "congestion_control_algorithm": DEFAULT_CONGESTION_CONTROL_ALGORITHM,
    "connect_timeout": DEFAULT_CONNECT_TIMEOUT,
    "connection_cleanup_interval": DEFAULT_CONNECTION_CLEANUP_INTERVAL,
    "connection_idle_check_interval": DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL,
    "connection_idle_timeout": DEFAULT_CONNECTION_IDLE_TIMEOUT,
    "connection_keepalive_timeout": DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT,
    "debug": DEFAULT_DEBUG,
    "headers": {},
    "keep_alive": DEFAULT_KEEP_ALIVE,
    "keyfile": None,
    "log_level": DEFAULT_LOG_LEVEL,
    "max_connections": DEFAULT_CLIENT_MAX_CONNECTIONS,
    "max_datagram_size": DEFAULT_MAX_DATAGRAM_SIZE,
    "max_incoming_streams": DEFAULT_MAX_INCOMING_STREAMS,
    "max_retries": DEFAULT_MAX_RETRIES,
    "max_retry_delay": DEFAULT_MAX_RETRY_DELAY,
    "max_stream_buffer_size": MAX_BUFFER_SIZE,
    "max_streams": DEFAULT_MAX_STREAMS,
    "read_timeout": DEFAULT_READ_TIMEOUT,
    "retry_backoff": DEFAULT_RETRY_BACKOFF,
    "retry_delay": DEFAULT_RETRY_DELAY,
    "stream_buffer_size": DEFAULT_BUFFER_SIZE,
    "stream_cleanup_interval": DEFAULT_STREAM_CLEANUP_INTERVAL,
    "stream_creation_timeout": DEFAULT_STREAM_CREATION_TIMEOUT,
    "user_agent": f"pywebtransport/{__version__}",
    "verify_mode": DEFAULT_CLIENT_VERIFY_MODE,
    "write_timeout": DEFAULT_WRITE_TIMEOUT,
}

_DEFAULT_SERVER_CONFIG: ServerConfigDefaults = {
    "access_log": DEFAULT_ACCESS_LOG,
    "alpn_protocols": list(DEFAULT_ALPN_PROTOCOLS),
    "bind_host": DEFAULT_BIND_HOST,
    "bind_port": DEFAULT_DEV_PORT,
    "ca_certs": None,
    "certfile": DEFAULT_CERTFILE,
    "congestion_control_algorithm": DEFAULT_CONGESTION_CONTROL_ALGORITHM,
    "connection_cleanup_interval": DEFAULT_CONNECTION_CLEANUP_INTERVAL,
    "connection_idle_check_interval": DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL,
    "connection_idle_timeout": DEFAULT_CONNECTION_IDLE_TIMEOUT,
    "connection_keepalive_timeout": DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT,
    "debug": DEFAULT_DEBUG,
    "keep_alive": DEFAULT_KEEP_ALIVE,
    "keyfile": DEFAULT_KEYFILE,
    "log_level": DEFAULT_LOG_LEVEL,
    "max_connections": DEFAULT_SERVER_MAX_CONNECTIONS,
    "max_datagram_size": DEFAULT_MAX_DATAGRAM_SIZE,
    "max_incoming_streams": DEFAULT_MAX_INCOMING_STREAMS,
    "max_sessions": DEFAULT_MAX_SESSIONS,
    "max_stream_buffer_size": MAX_BUFFER_SIZE,
    "max_streams_per_connection": DEFAULT_MAX_STREAMS_PER_CONNECTION,
    "middleware": [],
    "read_timeout": DEFAULT_READ_TIMEOUT,
    "session_cleanup_interval": DEFAULT_SESSION_CLEANUP_INTERVAL,
    "stream_buffer_size": DEFAULT_BUFFER_SIZE,
    "stream_cleanup_interval": DEFAULT_STREAM_CLEANUP_INTERVAL,
    "verify_mode": DEFAULT_SERVER_VERIFY_MODE,
    "write_timeout": DEFAULT_WRITE_TIMEOUT,
}


class Defaults:
    """Provides access to default configuration values."""

    @staticmethod
    def get_client_config() -> ClientConfigDefaults:
        """Return a copy of the default client configuration."""
        return _DEFAULT_CLIENT_CONFIG.copy()

    @staticmethod
    def get_server_config() -> ServerConfigDefaults:
        """Return a copy of the default server configuration."""
        return _DEFAULT_SERVER_CONFIG.copy()
