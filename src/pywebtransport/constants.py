"""Protocol-level constants and default configuration values."""

from __future__ import annotations

import ssl
from enum import IntEnum
from typing import Any, TypedDict

from pywebtransport.types import Headers
from pywebtransport.version import __version__

__all__: list[str] = [
    "ALPN_H3",
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
    "DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE",
    "DEFAULT_FLOW_CONTROL_WINDOW_SIZE",
    "DEFAULT_INITIAL_MAX_DATA",
    "DEFAULT_INITIAL_MAX_STREAMS_BIDI",
    "DEFAULT_INITIAL_MAX_STREAMS_UNI",
    "DEFAULT_KEEP_ALIVE",
    "DEFAULT_KEYFILE",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_MAX_DATAGRAM_SIZE",
    "DEFAULT_MAX_INCOMING_STREAMS",
    "DEFAULT_MAX_MESSAGE_SIZE",
    "DEFAULT_MAX_PENDING_EVENTS_PER_SESSION",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_RETRY_DELAY",
    "DEFAULT_MAX_SESSIONS",
    "DEFAULT_MAX_STREAMS",
    "DEFAULT_MAX_STREAMS_PER_CONNECTION",
    "DEFAULT_MAX_TOTAL_PENDING_EVENTS",
    "DEFAULT_PENDING_EVENT_TTL",
    "DEFAULT_PROXY_CONNECT_TIMEOUT",
    "DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE",
    "DEFAULT_READ_TIMEOUT",
    "DEFAULT_RETRY_BACKOFF",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_RPC_CONCURRENCY_LIMIT",
    "DEFAULT_SECURE_PORT",
    "DEFAULT_SERVER_MAX_CONNECTIONS",
    "DEFAULT_SERVER_VERIFY_MODE",
    "DEFAULT_SESSION_CLEANUP_INTERVAL",
    "DEFAULT_STREAM_CLEANUP_INTERVAL",
    "DEFAULT_STREAM_CREATION_TIMEOUT",
    "DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI",
    "DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI",
    "DEFAULT_STREAM_LINE_LIMIT",
    "DEFAULT_WEBTRANSPORT_PATH",
    "DEFAULT_WRITE_TIMEOUT",
    "DRAIN_WEBTRANSPORT_SESSION_TYPE",
    "ErrorCodes",
    "H3_FRAME_TYPE_CANCEL_PUSH",
    "H3_FRAME_TYPE_DATA",
    "H3_FRAME_TYPE_GOAWAY",
    "H3_FRAME_TYPE_HEADERS",
    "H3_FRAME_TYPE_MAX_PUSH_ID",
    "H3_FRAME_TYPE_PUSH_PROMISE",
    "H3_FRAME_TYPE_SETTINGS",
    "H3_FRAME_TYPE_WEBTRANSPORT_STREAM",
    "H3_STREAM_TYPE_CONTROL",
    "H3_STREAM_TYPE_PUSH",
    "H3_STREAM_TYPE_QPACK_DECODER",
    "H3_STREAM_TYPE_QPACK_ENCODER",
    "H3_STREAM_TYPE_WEBTRANSPORT",
    "MAX_BUFFER_SIZE",
    "MAX_DATAGRAM_SIZE",
    "MAX_STREAM_ID",
    "SETTINGS_ENABLE_CONNECT_PROTOCOL",
    "SETTINGS_H3_DATAGRAM",
    "SETTINGS_QPACK_BLOCKED_STREAMS",
    "SETTINGS_QPACK_MAX_TABLE_CAPACITY",
    "SETTINGS_WT_INITIAL_MAX_DATA",
    "SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI",
    "SETTINGS_WT_INITIAL_MAX_STREAMS_UNI",
    "SETTINGS_WT_MAX_SESSIONS",
    "SUPPORTED_CONGESTION_CONTROL_ALGORITHMS",
    "ServerConfigDefaults",
    "UNIDIRECTIONAL_STREAM",
    "USER_AGENT_HEADER",
    "WEBTRANSPORT_SCHEME",
    "WT_DATA_BLOCKED_TYPE",
    "WT_MAX_DATA_TYPE",
    "WT_MAX_STREAMS_BIDI_TYPE",
    "WT_MAX_STREAMS_UNI_TYPE",
    "WT_STREAMS_BLOCKED_BIDI_TYPE",
    "WT_STREAMS_BLOCKED_UNI_TYPE",
    "get_default_client_config",
    "get_default_server_config",
]


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
    flow_control_window_auto_scale: bool
    flow_control_window_size: int
    headers: Headers
    initial_max_data: int
    initial_max_streams_bidi: int
    initial_max_streams_uni: int
    keep_alive: bool
    keyfile: str | None
    log_level: str
    max_connections: int
    max_datagram_size: int
    max_incoming_streams: int
    max_pending_events_per_session: int
    max_retries: int
    max_retry_delay: float
    max_stream_buffer_size: int
    max_streams: int
    max_total_pending_events: int
    pending_event_ttl: float
    proxy: Any
    read_timeout: float | None
    retry_backoff: float
    retry_delay: float
    rpc_concurrency_limit: int
    stream_buffer_size: int
    stream_cleanup_interval: float
    stream_creation_timeout: float
    stream_flow_control_increment_bidi: int
    stream_flow_control_increment_uni: int
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
    flow_control_window_auto_scale: bool
    flow_control_window_size: int
    initial_max_data: int
    initial_max_streams_bidi: int
    initial_max_streams_uni: int
    keep_alive: bool
    keyfile: str
    log_level: str
    max_connections: int
    max_datagram_size: int
    max_incoming_streams: int
    max_pending_events_per_session: int
    max_sessions: int
    max_stream_buffer_size: int
    max_streams_per_connection: int
    max_total_pending_events: int
    middleware: list[Any]
    pending_event_ttl: float
    read_timeout: float | None
    rpc_concurrency_limit: int
    session_cleanup_interval: float
    stream_buffer_size: int
    stream_cleanup_interval: float
    stream_flow_control_increment_bidi: int
    stream_flow_control_increment_uni: int
    verify_mode: ssl.VerifyMode
    write_timeout: float | None


ALPN_H3: str = "h3"
USER_AGENT_HEADER: str = "user-agent"
WEBTRANSPORT_SCHEME: str = "https"

BIDIRECTIONAL_STREAM: int = 0x0
CLOSE_WEBTRANSPORT_SESSION_TYPE: int = 0x2843
DRAIN_WEBTRANSPORT_SESSION_TYPE: int = 0x78AE
H3_FRAME_TYPE_DATA: int = 0x0
H3_FRAME_TYPE_HEADERS: int = 0x1
H3_FRAME_TYPE_CANCEL_PUSH: int = 0x3
H3_FRAME_TYPE_SETTINGS: int = 0x4
H3_FRAME_TYPE_PUSH_PROMISE: int = 0x5
H3_FRAME_TYPE_GOAWAY: int = 0x7
H3_FRAME_TYPE_MAX_PUSH_ID: int = 0xD
H3_FRAME_TYPE_WEBTRANSPORT_STREAM: int = 0x41
H3_STREAM_TYPE_CONTROL: int = 0x0
H3_STREAM_TYPE_PUSH: int = 0x1
H3_STREAM_TYPE_QPACK_ENCODER: int = 0x2
H3_STREAM_TYPE_QPACK_DECODER: int = 0x3
H3_STREAM_TYPE_WEBTRANSPORT: int = 0x54
MAX_DATAGRAM_SIZE: int = 65535
MAX_STREAM_ID: int = 2**62 - 1
SETTINGS_ENABLE_CONNECT_PROTOCOL: int = 0x8
SETTINGS_H3_DATAGRAM: int = 0x33
SETTINGS_QPACK_BLOCKED_STREAMS: int = 0x7
SETTINGS_QPACK_MAX_TABLE_CAPACITY: int = 0x1
SETTINGS_WT_INITIAL_MAX_DATA: int = 0x2B61
SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI: int = 0x2B65
SETTINGS_WT_INITIAL_MAX_STREAMS_UNI: int = 0x2B64
SETTINGS_WT_MAX_SESSIONS: int = 0x14E9CD29
UNIDIRECTIONAL_STREAM: int = 0x2
WT_DATA_BLOCKED_TYPE: int = 0x190B4D41
WT_MAX_DATA_TYPE: int = 0x190B4D3D
WT_MAX_STREAMS_BIDI_TYPE: int = 0x190B4D3F
WT_MAX_STREAMS_UNI_TYPE: int = 0x190B4D40
WT_STREAMS_BLOCKED_BIDI_TYPE: int = 0x190B4D43
WT_STREAMS_BLOCKED_UNI_TYPE: int = 0x190B4D44

DEFAULT_ACCESS_LOG: bool = True
DEFAULT_ALPN_PROTOCOLS: tuple[str] = (ALPN_H3,)
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
DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE: bool = True
DEFAULT_FLOW_CONTROL_WINDOW_SIZE: int = 1024 * 1024
DEFAULT_INITIAL_MAX_DATA: int = 0
DEFAULT_INITIAL_MAX_STREAMS_BIDI: int = 0
DEFAULT_INITIAL_MAX_STREAMS_UNI: int = 0
DEFAULT_KEEP_ALIVE: bool = True
DEFAULT_KEYFILE: str = ""
DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_MAX_DATAGRAM_SIZE: int = 65535
DEFAULT_MAX_MESSAGE_SIZE: int = 1024 * 1024
DEFAULT_MAX_INCOMING_STREAMS: int = 100
DEFAULT_MAX_PENDING_EVENTS_PER_SESSION: int = 16
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_MAX_RETRY_DELAY: float = 30.0
DEFAULT_MAX_SESSIONS: int = 10000
DEFAULT_MAX_STREAMS: int = 100
DEFAULT_MAX_STREAMS_PER_CONNECTION: int = 100
DEFAULT_MAX_TOTAL_PENDING_EVENTS: int = 1000
DEFAULT_PENDING_EVENT_TTL: float = 5.0
DEFAULT_PROXY_CONNECT_TIMEOUT: float = 10.0
DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE: int = 16
DEFAULT_READ_TIMEOUT: float = 60.0
DEFAULT_RETRY_BACKOFF: float = 2.0
DEFAULT_RETRY_DELAY: float = 1.0
DEFAULT_RPC_CONCURRENCY_LIMIT: int = 100
DEFAULT_SECURE_PORT: int = 443
DEFAULT_SERVER_MAX_CONNECTIONS: int = 3000
DEFAULT_SERVER_VERIFY_MODE: ssl.VerifyMode = ssl.CERT_OPTIONAL
DEFAULT_SESSION_CLEANUP_INTERVAL: float = 60.0
DEFAULT_STREAM_CLEANUP_INTERVAL: float = 15.0
DEFAULT_STREAM_CREATION_TIMEOUT: float = 10.0
DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI: int = 10
DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI: int = 10
DEFAULT_STREAM_LINE_LIMIT: int = 65536
DEFAULT_WEBTRANSPORT_PATH: str = "/webtransport"
DEFAULT_WRITE_TIMEOUT: float = 30.0
MAX_BUFFER_SIZE: int = 1024 * 1024
SUPPORTED_CONGESTION_CONTROL_ALGORITHMS: tuple[str, str] = ("reno", "cubic")


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
    "flow_control_window_auto_scale": DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE,
    "flow_control_window_size": DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    "headers": {},
    "initial_max_data": DEFAULT_INITIAL_MAX_DATA,
    "initial_max_streams_bidi": DEFAULT_INITIAL_MAX_STREAMS_BIDI,
    "initial_max_streams_uni": DEFAULT_INITIAL_MAX_STREAMS_UNI,
    "keep_alive": DEFAULT_KEEP_ALIVE,
    "keyfile": None,
    "log_level": DEFAULT_LOG_LEVEL,
    "max_connections": DEFAULT_CLIENT_MAX_CONNECTIONS,
    "max_datagram_size": DEFAULT_MAX_DATAGRAM_SIZE,
    "max_incoming_streams": DEFAULT_MAX_INCOMING_STREAMS,
    "max_pending_events_per_session": DEFAULT_MAX_PENDING_EVENTS_PER_SESSION,
    "max_retries": DEFAULT_MAX_RETRIES,
    "max_retry_delay": DEFAULT_MAX_RETRY_DELAY,
    "max_stream_buffer_size": MAX_BUFFER_SIZE,
    "max_streams": DEFAULT_MAX_STREAMS,
    "max_total_pending_events": DEFAULT_MAX_TOTAL_PENDING_EVENTS,
    "pending_event_ttl": DEFAULT_PENDING_EVENT_TTL,
    "proxy": None,
    "read_timeout": DEFAULT_READ_TIMEOUT,
    "retry_backoff": DEFAULT_RETRY_BACKOFF,
    "retry_delay": DEFAULT_RETRY_DELAY,
    "rpc_concurrency_limit": DEFAULT_RPC_CONCURRENCY_LIMIT,
    "stream_buffer_size": DEFAULT_BUFFER_SIZE,
    "stream_cleanup_interval": DEFAULT_STREAM_CLEANUP_INTERVAL,
    "stream_creation_timeout": DEFAULT_STREAM_CREATION_TIMEOUT,
    "stream_flow_control_increment_bidi": DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI,
    "stream_flow_control_increment_uni": DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI,
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
    "flow_control_window_auto_scale": DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE,
    "flow_control_window_size": DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    "initial_max_data": DEFAULT_INITIAL_MAX_DATA,
    "initial_max_streams_bidi": DEFAULT_INITIAL_MAX_STREAMS_BIDI,
    "initial_max_streams_uni": DEFAULT_INITIAL_MAX_STREAMS_UNI,
    "keep_alive": DEFAULT_KEEP_ALIVE,
    "keyfile": DEFAULT_KEYFILE,
    "log_level": DEFAULT_LOG_LEVEL,
    "max_connections": DEFAULT_SERVER_MAX_CONNECTIONS,
    "max_datagram_size": DEFAULT_MAX_DATAGRAM_SIZE,
    "max_incoming_streams": DEFAULT_MAX_INCOMING_STREAMS,
    "max_pending_events_per_session": DEFAULT_MAX_PENDING_EVENTS_PER_SESSION,
    "max_sessions": DEFAULT_MAX_SESSIONS,
    "max_stream_buffer_size": MAX_BUFFER_SIZE,
    "max_streams_per_connection": DEFAULT_MAX_STREAMS_PER_CONNECTION,
    "max_total_pending_events": DEFAULT_MAX_TOTAL_PENDING_EVENTS,
    "middleware": [],
    "pending_event_ttl": DEFAULT_PENDING_EVENT_TTL,
    "read_timeout": DEFAULT_READ_TIMEOUT,
    "rpc_concurrency_limit": DEFAULT_RPC_CONCURRENCY_LIMIT,
    "session_cleanup_interval": DEFAULT_SESSION_CLEANUP_INTERVAL,
    "stream_buffer_size": DEFAULT_BUFFER_SIZE,
    "stream_cleanup_interval": DEFAULT_STREAM_CLEANUP_INTERVAL,
    "stream_flow_control_increment_bidi": DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI,
    "stream_flow_control_increment_uni": DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI,
    "verify_mode": DEFAULT_SERVER_VERIFY_MODE,
    "write_timeout": DEFAULT_WRITE_TIMEOUT,
}


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
    WT_SESSION_GONE = 0x170D7B68
    WT_BUFFERED_STREAM_REJECTED = 0x3994BD84
    WT_APPLICATION_ERROR_FIRST = 0x52E4A40FA8DB
    QPACK_DECOMPRESSION_FAILED = 0x200
    QPACK_ENCODER_STREAM_ERROR = 0x201
    QPACK_DECODER_STREAM_ERROR = 0x202
    APP_CONNECTION_TIMEOUT = 0x1000
    APP_AUTHENTICATION_FAILED = 0x1001
    APP_PERMISSION_DENIED = 0x1002
    APP_RESOURCE_EXHAUSTED = 0x1003
    APP_INVALID_REQUEST = 0x1004
    APP_SERVICE_UNAVAILABLE = 0x1005


def get_default_client_config() -> ClientConfigDefaults:
    """Return a copy of the default client configuration."""
    return _DEFAULT_CLIENT_CONFIG.copy()


def get_default_server_config() -> ServerConfigDefaults:
    """Return a copy of the default server configuration."""
    return _DEFAULT_SERVER_CONFIG.copy()
