"""Structured configuration objects for clients and servers."""

from __future__ import annotations

import copy
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from pywebtransport.constants import (
    DEFAULT_ACCESS_LOG,
    DEFAULT_ALPN_PROTOCOLS,
    DEFAULT_AUTO_RECONNECT,
    DEFAULT_BIND_HOST,
    DEFAULT_BUFFER_SIZE,
    DEFAULT_CERTFILE,
    DEFAULT_CLIENT_MAX_CONNECTIONS,
    DEFAULT_CLIENT_VERIFY_MODE,
    DEFAULT_CLOSE_TIMEOUT,
    DEFAULT_CONGESTION_CONTROL_ALGORITHM,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_CONNECTION_CLEANUP_INTERVAL,
    DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL,
    DEFAULT_CONNECTION_IDLE_TIMEOUT,
    DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT,
    DEFAULT_DEBUG,
    DEFAULT_DEV_PORT,
    DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE,
    DEFAULT_FLOW_CONTROL_WINDOW_SIZE,
    DEFAULT_INITIAL_MAX_DATA,
    DEFAULT_INITIAL_MAX_STREAMS_BIDI,
    DEFAULT_INITIAL_MAX_STREAMS_UNI,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_KEYFILE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_DATAGRAM_SIZE,
    DEFAULT_MAX_INCOMING_STREAMS,
    DEFAULT_MAX_PENDING_EVENTS_PER_SESSION,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_RETRY_DELAY,
    DEFAULT_MAX_SESSIONS,
    DEFAULT_MAX_STREAMS,
    DEFAULT_MAX_STREAMS_PER_CONNECTION,
    DEFAULT_MAX_TOTAL_PENDING_EVENTS,
    DEFAULT_PENDING_EVENT_TTL,
    DEFAULT_PROXY_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_DELAY,
    DEFAULT_RPC_CONCURRENCY_LIMIT,
    DEFAULT_SERVER_MAX_CONNECTIONS,
    DEFAULT_SERVER_VERIFY_MODE,
    DEFAULT_SESSION_CLEANUP_INTERVAL,
    DEFAULT_STREAM_CLEANUP_INTERVAL,
    DEFAULT_STREAM_CREATION_TIMEOUT,
    DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI,
    DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI,
    DEFAULT_WRITE_TIMEOUT,
    MAX_BUFFER_SIZE,
    SUPPORTED_CONGESTION_CONTROL_ALGORITHMS,
    get_default_client_config,
    get_default_server_config,
)
from pywebtransport.exceptions import certificate_not_found, invalid_config
from pywebtransport.types import Headers, MiddlewareProtocol
from pywebtransport.version import __version__

__all__: list[str] = ["ClientConfig", "ProxyConfig", "ServerConfig"]


@dataclass(kw_only=True)
class ClientConfig:
    """A comprehensive configuration for the WebTransport client."""

    alpn_protocols: list[str] = field(default_factory=lambda: list(DEFAULT_ALPN_PROTOCOLS))
    auto_reconnect: bool = DEFAULT_AUTO_RECONNECT
    ca_certs: str | None = None
    certfile: str | None = None
    close_timeout: float = DEFAULT_CLOSE_TIMEOUT
    congestion_control_algorithm: str = DEFAULT_CONGESTION_CONTROL_ALGORITHM
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    connection_cleanup_interval: float = DEFAULT_CONNECTION_CLEANUP_INTERVAL
    connection_idle_check_interval: float = DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL
    connection_idle_timeout: float = DEFAULT_CONNECTION_IDLE_TIMEOUT
    connection_keepalive_timeout: float = DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT
    debug: bool = DEFAULT_DEBUG
    flow_control_window_auto_scale: bool = DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
    flow_control_window_size: int = DEFAULT_FLOW_CONTROL_WINDOW_SIZE
    headers: Headers = field(default_factory=dict)
    initial_max_data: int = DEFAULT_INITIAL_MAX_DATA
    initial_max_streams_bidi: int = DEFAULT_INITIAL_MAX_STREAMS_BIDI
    initial_max_streams_uni: int = DEFAULT_INITIAL_MAX_STREAMS_UNI
    keep_alive: bool = DEFAULT_KEEP_ALIVE
    keyfile: str | None = None
    log_level: str = DEFAULT_LOG_LEVEL
    max_connections: int = DEFAULT_CLIENT_MAX_CONNECTIONS
    max_datagram_size: int = DEFAULT_MAX_DATAGRAM_SIZE
    max_incoming_streams: int = DEFAULT_MAX_INCOMING_STREAMS
    max_pending_events_per_session: int = DEFAULT_MAX_PENDING_EVENTS_PER_SESSION
    max_retries: int = DEFAULT_MAX_RETRIES
    max_retry_delay: float = DEFAULT_MAX_RETRY_DELAY
    max_stream_buffer_size: int = MAX_BUFFER_SIZE
    max_streams: int = DEFAULT_MAX_STREAMS
    max_total_pending_events: int = DEFAULT_MAX_TOTAL_PENDING_EVENTS
    pending_event_ttl: float = DEFAULT_PENDING_EVENT_TTL
    proxy: ProxyConfig | None = None
    read_timeout: float | None = DEFAULT_READ_TIMEOUT
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    retry_delay: float = DEFAULT_RETRY_DELAY
    rpc_concurrency_limit: int = DEFAULT_RPC_CONCURRENCY_LIMIT
    stream_buffer_size: int = DEFAULT_BUFFER_SIZE
    stream_cleanup_interval: float = DEFAULT_STREAM_CLEANUP_INTERVAL
    stream_creation_timeout: float = DEFAULT_STREAM_CREATION_TIMEOUT
    stream_flow_control_increment_bidi: int = DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI
    stream_flow_control_increment_uni: int = DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI
    user_agent: str = f"pywebtransport/{__version__}"
    verify_mode: ssl.VerifyMode | None = DEFAULT_CLIENT_VERIFY_MODE
    write_timeout: float | None = DEFAULT_WRITE_TIMEOUT

    def __post_init__(self) -> None:
        """Normalize headers and validate the configuration after initialization."""
        self.headers = _normalize_headers(headers=self.headers)
        if "user-agent" not in self.headers:
            self.headers["user-agent"] = self.user_agent

        self.validate()

    @classmethod
    def create_for_development(cls, *, verify_ssl: bool = False) -> Self:
        """Factory method to create a client configuration suitable for development."""
        config_dict = {
            **get_default_client_config(),
            "verify_mode": ssl.CERT_NONE if not verify_ssl else ssl.CERT_REQUIRED,
            "debug": True,
            "log_level": "DEBUG",
        }
        return cls.from_dict(config_dict=config_dict)

    @classmethod
    def create_for_production(
        cls,
        *,
        ca_certs: str | None = None,
        certfile: str | None = None,
        keyfile: str | None = None,
    ) -> Self:
        """Factory method to create a client configuration suitable for production."""
        config_dict = {
            **get_default_client_config(),
            "ca_certs": ca_certs,
            "certfile": certfile,
            "keyfile": keyfile,
            "verify_mode": ssl.CERT_REQUIRED,
        }
        return cls.from_dict(config_dict=config_dict)

    @classmethod
    def from_dict(cls, *, config_dict: dict[str, Any]) -> Self:
        """Create a ClientConfig instance from a dictionary."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_keys}
        return cls(**filtered_dict)

    def copy(self) -> Self:
        """Create a deep copy of the configuration."""
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        """Convert the configuration to a dictionary."""
        result = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            match value:
                case ssl.VerifyMode():
                    result[field_name] = value.name
                case _:
                    result[field_name] = value
        return result

    def update(self, **kwargs: Any) -> Self:
        """Create a new config with updated values."""
        new_config = self.copy()

        for key, value in kwargs.items():
            if hasattr(new_config, key):
                setattr(new_config, key, value)
            else:
                raise invalid_config(key=key, value=value, reason="unknown configuration key")

        new_config.validate()
        return new_config

    def validate(self) -> None:
        """Validate the integrity and correctness of the configuration values."""
        _validate_common_config(self)

        if self.proxy:
            try:
                _validate_timeout(timeout=self.proxy.connect_timeout)
            except ValueError as e:
                raise invalid_config(
                    key="proxy.connect_timeout", value=getattr(self.proxy, "connect_timeout", None), reason=str(e)
                ) from e

        if self.max_retries < 0:
            raise invalid_config(key="max_retries", value=self.max_retries, reason="must be non-negative")

        if self.max_retry_delay <= 0:
            raise invalid_config(key="max_retry_delay", value=self.max_retry_delay, reason="must be positive")

        if self.retry_backoff < 1.0:
            raise invalid_config(key="retry_backoff", value=self.retry_backoff, reason="must be >= 1.0")

        if self.retry_delay <= 0:
            raise invalid_config(key="retry_delay", value=self.retry_delay, reason="must be positive")

        if self.max_streams <= 0:
            raise invalid_config(key="max_streams", value=self.max_streams, reason="must be positive")


@dataclass(kw_only=True)
class ProxyConfig:
    """Configuration for connecting through an HTTP proxy."""

    url: str
    headers: Headers = field(default_factory=dict)
    connect_timeout: float = DEFAULT_PROXY_CONNECT_TIMEOUT


@dataclass(kw_only=True)
class ServerConfig:
    """A comprehensive configuration for the WebTransport server."""

    access_log: bool = DEFAULT_ACCESS_LOG
    alpn_protocols: list[str] = field(default_factory=lambda: list(DEFAULT_ALPN_PROTOCOLS))
    bind_host: str = DEFAULT_BIND_HOST
    bind_port: int = DEFAULT_DEV_PORT
    ca_certs: str | None = None
    certfile: str = DEFAULT_CERTFILE
    congestion_control_algorithm: str = DEFAULT_CONGESTION_CONTROL_ALGORITHM
    connection_cleanup_interval: float = DEFAULT_CONNECTION_CLEANUP_INTERVAL
    connection_idle_check_interval: float = DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL
    connection_idle_timeout: float = DEFAULT_CONNECTION_IDLE_TIMEOUT
    connection_keepalive_timeout: float = DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT
    debug: bool = DEFAULT_DEBUG
    flow_control_window_auto_scale: bool = DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE
    flow_control_window_size: int = DEFAULT_FLOW_CONTROL_WINDOW_SIZE
    initial_max_data: int = DEFAULT_INITIAL_MAX_DATA
    initial_max_streams_bidi: int = DEFAULT_INITIAL_MAX_STREAMS_BIDI
    initial_max_streams_uni: int = DEFAULT_INITIAL_MAX_STREAMS_UNI
    keep_alive: bool = DEFAULT_KEEP_ALIVE
    keyfile: str = DEFAULT_KEYFILE
    log_level: str = DEFAULT_LOG_LEVEL
    max_connections: int = DEFAULT_SERVER_MAX_CONNECTIONS
    max_datagram_size: int = DEFAULT_MAX_DATAGRAM_SIZE
    max_incoming_streams: int = DEFAULT_MAX_INCOMING_STREAMS
    max_pending_events_per_session: int = DEFAULT_MAX_PENDING_EVENTS_PER_SESSION
    max_sessions: int = DEFAULT_MAX_SESSIONS
    max_stream_buffer_size: int = MAX_BUFFER_SIZE
    max_streams_per_connection: int = DEFAULT_MAX_STREAMS_PER_CONNECTION
    max_total_pending_events: int = DEFAULT_MAX_TOTAL_PENDING_EVENTS
    middleware: list[MiddlewareProtocol] = field(default_factory=list)
    pending_event_ttl: float = DEFAULT_PENDING_EVENT_TTL
    read_timeout: float | None = DEFAULT_READ_TIMEOUT
    rpc_concurrency_limit: int = DEFAULT_RPC_CONCURRENCY_LIMIT
    session_cleanup_interval: float = DEFAULT_SESSION_CLEANUP_INTERVAL
    stream_buffer_size: int = DEFAULT_BUFFER_SIZE
    stream_cleanup_interval: float = DEFAULT_STREAM_CLEANUP_INTERVAL
    stream_flow_control_increment_bidi: int = DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI
    stream_flow_control_increment_uni: int = DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI
    verify_mode: ssl.VerifyMode = DEFAULT_SERVER_VERIFY_MODE
    write_timeout: float | None = DEFAULT_WRITE_TIMEOUT

    def __post_init__(self) -> None:
        """Validate the configuration after initialization."""
        self.validate()

    @classmethod
    def create_for_development(
        cls,
        *,
        host: str = "localhost",
        port: int = 4433,
        certfile: str | None = None,
        keyfile: str | None = None,
    ) -> Self:
        """Factory method to create a server configuration suitable for development."""
        config_dict = {
            **get_default_server_config(),
            "bind_host": host,
            "bind_port": port,
            "debug": True,
            "log_level": "DEBUG",
        }
        config = cls.from_dict(config_dict=config_dict)

        if certfile and keyfile:
            config.certfile, config.keyfile = certfile, keyfile
        elif not (config.certfile and config.keyfile):
            config.certfile = ""
            config.keyfile = ""
        return config

    @classmethod
    def create_for_production(
        cls,
        *,
        host: str,
        port: int,
        certfile: str,
        keyfile: str,
        ca_certs: str | None = None,
    ) -> Self:
        """Factory method to create a server configuration suitable for production."""
        config_dict = {
            **get_default_server_config(),
            "bind_host": host,
            "bind_port": port,
            "certfile": certfile,
            "keyfile": keyfile,
            "ca_certs": ca_certs,
            "verify_mode": ssl.CERT_OPTIONAL if ca_certs else ssl.CERT_NONE,
        }
        return cls.from_dict(config_dict=config_dict)

    @classmethod
    def from_dict(cls, *, config_dict: dict[str, Any]) -> Self:
        """Create a ServerConfig instance from a dictionary."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_keys}
        return cls(**filtered_dict)

    def copy(self) -> Self:
        """Create a deep copy of the configuration."""
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        """Convert the configuration to a dictionary."""
        result = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            match value:
                case ssl.VerifyMode():
                    result[field_name] = value.name
                case _:
                    result[field_name] = value
        return result

    def update(self, **kwargs: Any) -> Self:
        """Create a new config with updated values."""
        new_config = self.copy()

        for key, value in kwargs.items():
            if hasattr(new_config, key):
                setattr(new_config, key, value)
            else:
                raise invalid_config(key=key, value=value, reason="unknown configuration key")

        new_config.validate()
        return new_config

    def validate(self) -> None:
        """Validate the integrity and correctness of the configuration values."""
        _validate_common_config(self)

        if not self.bind_host:
            raise invalid_config(key="bind_host", value=self.bind_host, reason="cannot be empty")

        try:
            _validate_port(port=self.bind_port)
        except ValueError as e:
            raise invalid_config(key="bind_port", value=self.bind_port, reason=str(e)) from e

        if self.max_sessions <= 0:
            raise invalid_config(key="max_sessions", value=self.max_sessions, reason="must be positive")

        if self.max_streams_per_connection <= 0:
            raise invalid_config(
                key="max_streams_per_connection", value=self.max_streams_per_connection, reason="must be positive"
            )


def _normalize_headers(*, headers: dict[str, Any]) -> dict[str, str]:
    """Normalize header keys to lowercase and values to strings."""
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _validate_common_config(config: ClientConfig | ServerConfig) -> None:
    """Validate configuration options common to both client and server."""
    if not config.alpn_protocols:
        raise invalid_config(key="alpn_protocols", value=config.alpn_protocols, reason="cannot be empty")

    if config.congestion_control_algorithm not in SUPPORTED_CONGESTION_CONTROL_ALGORITHMS:
        raise invalid_config(
            key="congestion_control_algorithm",
            value=config.congestion_control_algorithm,
            reason=f"must be one of {SUPPORTED_CONGESTION_CONTROL_ALGORITHMS}",
        )

    timeouts_to_check = [
        "connection_cleanup_interval",
        "connection_idle_check_interval",
        "connection_idle_timeout",
        "connection_keepalive_timeout",
        "pending_event_ttl",
        "read_timeout",
        "stream_cleanup_interval",
        "write_timeout",
    ]
    if isinstance(config, ClientConfig):
        timeouts_to_check.extend(["close_timeout", "connect_timeout", "stream_creation_timeout"])
    if isinstance(config, ServerConfig):
        timeouts_to_check.append("session_cleanup_interval")

    for timeout_name in timeouts_to_check:
        try:
            _validate_timeout(timeout=getattr(config, timeout_name))
        except (ValueError, TypeError) as e:
            raise invalid_config(key=timeout_name, value=getattr(config, timeout_name), reason=str(e)) from e

    if config.flow_control_window_size <= 0:
        raise invalid_config(
            key="flow_control_window_size",
            value=config.flow_control_window_size,
            reason="must be positive",
        )

    if config.max_connections <= 0:
        raise invalid_config(key="max_connections", value=config.max_connections, reason="must be positive")

    if config.max_datagram_size <= 0 or config.max_datagram_size > 65535:
        raise invalid_config(
            key="max_datagram_size",
            value=config.max_datagram_size,
            reason="must be 1-65535",
        )

    if config.max_incoming_streams <= 0:
        raise invalid_config(
            key="max_incoming_streams",
            value=config.max_incoming_streams,
            reason="must be positive",
        )

    if config.max_pending_events_per_session <= 0:
        raise invalid_config(
            key="max_pending_events_per_session",
            value=config.max_pending_events_per_session,
            reason="must be positive",
        )

    if config.max_total_pending_events <= 0:
        raise invalid_config(
            key="max_total_pending_events",
            value=config.max_total_pending_events,
            reason="must be positive",
        )

    if config.stream_buffer_size <= 0:
        raise invalid_config(
            key="stream_buffer_size",
            value=config.stream_buffer_size,
            reason="must be positive",
        )

    if config.max_stream_buffer_size < config.stream_buffer_size:
        raise invalid_config(
            key="max_stream_buffer_size",
            value=config.max_stream_buffer_size,
            reason="must be >= stream_buffer_size",
        )

    if config.stream_flow_control_increment_bidi <= 0:
        raise invalid_config(
            key="stream_flow_control_increment_bidi",
            value=config.stream_flow_control_increment_bidi,
            reason="must be positive",
        )

    if config.stream_flow_control_increment_uni <= 0:
        raise invalid_config(
            key="stream_flow_control_increment_uni",
            value=config.stream_flow_control_increment_uni,
            reason="must be positive",
        )

    if config.rpc_concurrency_limit <= 0:
        raise invalid_config(key="rpc_concurrency_limit", value=config.rpc_concurrency_limit, reason="must be positive")

    if config.ca_certs and not Path(config.ca_certs).exists():
        raise certificate_not_found(path=config.ca_certs)
    if config.certfile and not Path(config.certfile).exists():
        raise certificate_not_found(path=config.certfile)
    if config.keyfile and not Path(config.keyfile).exists():
        raise certificate_not_found(path=config.keyfile)

    certfile_exists = bool(config.certfile)
    keyfile_exists = hasattr(config, "keyfile") and bool(config.keyfile)
    if certfile_exists != keyfile_exists:
        raise invalid_config(
            key="certfile/keyfile",
            value=f"certfile={config.certfile}, keyfile={getattr(config, 'keyfile', None)}",
            reason="both must be provided together",
        )

    allowed_verify_modes: list[ssl.VerifyMode | None] = [ssl.CERT_NONE, ssl.CERT_OPTIONAL, ssl.CERT_REQUIRED]
    if isinstance(config, ClientConfig):
        allowed_verify_modes.append(None)
    if config.verify_mode not in allowed_verify_modes:
        raise invalid_config(key="verify_mode", value=config.verify_mode, reason="invalid SSL verify mode")


def _validate_port(*, port: Any) -> None:
    """Validate that a value is a valid network port."""
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"Port must be an integer between 1 and 65535, got {port}")


def _validate_timeout(*, timeout: float | None) -> None:
    """Validate a timeout value."""
    if timeout is not None:
        if not isinstance(timeout, (int, float)):
            raise TypeError("Timeout must be a number or None")
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
