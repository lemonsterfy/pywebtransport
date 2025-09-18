"""
WebTransport Configuration.
"""

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
    DEFAULT_READ_TIMEOUT,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_DELAY,
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
    Defaults,
)
from pywebtransport.exceptions import ConfigurationError, certificate_not_found, invalid_config
from pywebtransport.types import Address, Headers, MiddlewareProtocol
from pywebtransport.utils import normalize_headers
from pywebtransport.version import __version__

__all__ = [
    "ClientConfig",
    "ConfigBuilder",
    "ServerConfig",
]


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
    read_timeout: float | None = DEFAULT_READ_TIMEOUT
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    retry_delay: float = DEFAULT_RETRY_DELAY
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
        self.headers = normalize_headers(headers=self.headers)
        if "user-agent" not in self.headers:
            self.headers["user-agent"] = self.user_agent
        self.validate()

    @classmethod
    def create(cls, **kwargs: Any) -> Self:
        """Factory method to create a client configuration with specified overrides."""
        config_dict = {**Defaults.get_client_config(), **kwargs}
        return cls.from_dict(config_dict=config_dict)

    @classmethod
    def create_for_development(cls, *, verify_ssl: bool = False) -> Self:
        """Factory method to create a client configuration suitable for development."""
        return cls.create(
            connect_timeout=10.0,
            read_timeout=30.0,
            verify_mode=ssl.CERT_NONE if not verify_ssl else ssl.CERT_REQUIRED,
            debug=True,
            log_level="DEBUG",
        )

    @classmethod
    def create_for_production(
        cls,
        *,
        ca_certs: str | None = None,
        certfile: str | None = None,
        keyfile: str | None = None,
    ) -> Self:
        """Factory method to create a client configuration suitable for production."""
        return cls.create(
            connect_timeout=30.0,
            read_timeout=60.0,
            write_timeout=30.0,
            ca_certs=ca_certs,
            certfile=certfile,
            keyfile=keyfile,
            verify_mode=ssl.CERT_REQUIRED,
            max_streams=200,
            stream_buffer_size=65536,
            debug=False,
            log_level="INFO",
        )

    @classmethod
    def from_dict(cls, *, config_dict: dict[str, Any]) -> Self:
        """Create a ClientConfig instance from a dictionary."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_keys}
        return cls(**filtered_dict)

    def copy(self) -> Self:
        """Create a deep copy of the configuration."""
        return copy.deepcopy(self)

    def merge(self, *, other: ClientConfig | dict[str, Any]) -> Self:
        """Merge this configuration with another config or dictionary."""
        match other:
            case dict():
                return self.update(**other)
            case ClientConfig():
                update_dict = {
                    f.name: getattr(other, f.name)
                    for f in other.__dataclass_fields__.values()
                    if getattr(other, f.name) is not None
                }
                return self.update(**update_dict)
            case _:
                raise TypeError("Can only merge with ClientConfig or dict")

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
        if not self.alpn_protocols:
            raise invalid_config(key="alpn_protocols", value=self.alpn_protocols, reason="cannot be empty")
        if self.congestion_control_algorithm not in SUPPORTED_CONGESTION_CONTROL_ALGORITHMS:
            raise invalid_config(
                key="congestion_control_algorithm",
                value=self.congestion_control_algorithm,
                reason=f"must be one of {SUPPORTED_CONGESTION_CONTROL_ALGORITHMS}",
            )

        try:
            _validate_timeout(timeout=self.close_timeout)
            _validate_timeout(timeout=self.connect_timeout)
            _validate_timeout(timeout=self.connection_cleanup_interval)
            _validate_timeout(timeout=self.connection_idle_check_interval)
            _validate_timeout(timeout=self.connection_idle_timeout)
            _validate_timeout(timeout=self.connection_keepalive_timeout)
            _validate_timeout(timeout=self.pending_event_ttl)
            _validate_timeout(timeout=self.read_timeout)
            _validate_timeout(timeout=self.stream_cleanup_interval)
            _validate_timeout(timeout=self.stream_creation_timeout)
            _validate_timeout(timeout=self.write_timeout)
        except ValueError as e:
            raise invalid_config(key="timeout", value=str(e), reason="invalid timeout value") from e

        if self.flow_control_window_size <= 0:
            raise invalid_config(
                key="flow_control_window_size",
                value=self.flow_control_window_size,
                reason="must be positive",
            )
        if self.max_connections <= 0:
            raise invalid_config(key="max_connections", value=self.max_connections, reason="must be positive")
        if self.max_datagram_size <= 0 or self.max_datagram_size > 65535:
            raise invalid_config(
                key="max_datagram_size",
                value=self.max_datagram_size,
                reason="must be 1-65535",
            )
        if self.max_incoming_streams <= 0:
            raise invalid_config(
                key="max_incoming_streams",
                value=self.max_incoming_streams,
                reason="must be positive",
            )
        if self.max_pending_events_per_session <= 0:
            raise invalid_config(
                key="max_pending_events_per_session",
                value=self.max_pending_events_per_session,
                reason="must be positive",
            )
        if self.max_streams <= 0:
            raise invalid_config(key="max_streams", value=self.max_streams, reason="must be positive")
        if self.max_total_pending_events <= 0:
            raise invalid_config(
                key="max_total_pending_events",
                value=self.max_total_pending_events,
                reason="must be positive",
            )
        if self.stream_buffer_size <= 0:
            raise invalid_config(
                key="stream_buffer_size",
                value=self.stream_buffer_size,
                reason="must be positive",
            )
        if self.max_stream_buffer_size < self.stream_buffer_size:
            raise invalid_config(
                key="max_stream_buffer_size",
                value=self.max_stream_buffer_size,
                reason="must be >= stream_buffer_size",
            )
        if self.stream_flow_control_increment_bidi <= 0:
            raise invalid_config(
                key="stream_flow_control_increment_bidi",
                value=self.stream_flow_control_increment_bidi,
                reason="must be positive",
            )
        if self.stream_flow_control_increment_uni <= 0:
            raise invalid_config(
                key="stream_flow_control_increment_uni",
                value=self.stream_flow_control_increment_uni,
                reason="must be positive",
            )

        if self.max_retries < 0:
            raise invalid_config(key="max_retries", value=self.max_retries, reason="must be non-negative")
        if self.max_retry_delay <= 0:
            raise invalid_config(
                key="max_retry_delay",
                value=self.max_retry_delay,
                reason="must be positive",
            )
        if self.retry_backoff < 1.0:
            raise invalid_config(key="retry_backoff", value=self.retry_backoff, reason="must be >= 1.0")
        if self.retry_delay <= 0:
            raise invalid_config(key="retry_delay", value=self.retry_delay, reason="must be positive")

        if self.ca_certs and not Path(self.ca_certs).exists():
            raise certificate_not_found(path=self.ca_certs)
        if self.certfile and not Path(self.certfile).exists():
            raise certificate_not_found(path=self.certfile)
        if self.keyfile and not Path(self.keyfile).exists():
            raise certificate_not_found(path=self.keyfile)
        if bool(self.certfile) != bool(self.keyfile):
            raise invalid_config(
                key="certfile/keyfile",
                value=f"certfile={self.certfile}, keyfile={self.keyfile}",
                reason="both must be provided together",
            )
        if self.verify_mode not in [
            ssl.CERT_NONE,
            ssl.CERT_OPTIONAL,
            ssl.CERT_REQUIRED,
            None,
        ]:
            raise invalid_config(key="verify_mode", value=self.verify_mode, reason="invalid SSL verify mode")


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
    def create(cls, **kwargs: Any) -> Self:
        """Factory method to create a server configuration with specified overrides."""
        config_dict = {**Defaults.get_server_config(), **kwargs}
        return cls.from_dict(config_dict=config_dict)

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
        config = cls.create(
            bind_host=host,
            bind_port=port,
            max_connections=100,
            max_streams_per_connection=50,
            debug=True,
            log_level="DEBUG",
        )
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
        return cls.create(
            bind_host=host,
            bind_port=port,
            certfile=certfile,
            keyfile=keyfile,
            ca_certs=ca_certs,
            verify_mode=ssl.CERT_OPTIONAL if ca_certs else ssl.CERT_NONE,
            max_connections=DEFAULT_SERVER_MAX_CONNECTIONS,
            max_streams_per_connection=DEFAULT_MAX_STREAMS_PER_CONNECTION,
            debug=False,
            log_level="INFO",
        )

    @classmethod
    def from_dict(cls, *, config_dict: dict[str, Any]) -> Self:
        """Create a ServerConfig instance from a dictionary."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_keys}
        return cls(**filtered_dict)

    def copy(self) -> Self:
        """Create a deep copy of the configuration."""
        return copy.deepcopy(self)

    def get_bind_address(self) -> Address:
        """Get the bind address as a (host, port) tuple."""
        return (self.bind_host, self.bind_port)

    def merge(self, *, other: ServerConfig | dict[str, Any]) -> Self:
        """Merge this configuration with another config or dictionary."""
        match other:
            case dict():
                return self.update(**other)
            case ServerConfig():
                update_dict = {
                    f.name: getattr(other, f.name)
                    for f in other.__dataclass_fields__.values()
                    if getattr(other, f.name) is not None
                }
                return self.update(**update_dict)
            case _:
                raise TypeError("Can only merge with ServerConfig or dict")

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
        if not self.alpn_protocols:
            raise invalid_config(key="alpn_protocols", value=self.alpn_protocols, reason="cannot be empty")
        if not self.bind_host:
            raise invalid_config(key="bind_host", value=self.bind_host, reason="cannot be empty")
        try:
            _validate_port(port=self.bind_port)
        except ValueError as e:
            raise invalid_config(key="bind_port", value=self.bind_port, reason=str(e)) from e
        if self.congestion_control_algorithm not in SUPPORTED_CONGESTION_CONTROL_ALGORITHMS:
            raise invalid_config(
                key="congestion_control_algorithm",
                value=self.congestion_control_algorithm,
                reason=f"must be one of {SUPPORTED_CONGESTION_CONTROL_ALGORITHMS}",
            )

        try:
            _validate_timeout(timeout=self.connection_cleanup_interval)
            _validate_timeout(timeout=self.connection_idle_check_interval)
            _validate_timeout(timeout=self.connection_idle_timeout)
            _validate_timeout(timeout=self.connection_keepalive_timeout)
            _validate_timeout(timeout=self.pending_event_ttl)
            _validate_timeout(timeout=self.read_timeout)
            _validate_timeout(timeout=self.session_cleanup_interval)
            _validate_timeout(timeout=self.stream_cleanup_interval)
            _validate_timeout(timeout=self.write_timeout)
        except ValueError as e:
            raise invalid_config(key="timeout", value=str(e), reason="invalid timeout value") from e

        if self.flow_control_window_size <= 0:
            raise invalid_config(
                key="flow_control_window_size",
                value=self.flow_control_window_size,
                reason="must be positive",
            )
        if self.max_connections <= 0:
            raise invalid_config(key="max_connections", value=self.max_connections, reason="must be positive")
        if self.max_datagram_size <= 0 or self.max_datagram_size > 65535:
            raise invalid_config(
                key="max_datagram_size",
                value=self.max_datagram_size,
                reason="must be 1-65535",
            )
        if self.max_incoming_streams <= 0:
            raise invalid_config(
                key="max_incoming_streams",
                value=self.max_incoming_streams,
                reason="must be positive",
            )
        if self.max_pending_events_per_session <= 0:
            raise invalid_config(
                key="max_pending_events_per_session",
                value=self.max_pending_events_per_session,
                reason="must be positive",
            )
        if self.max_sessions <= 0:
            raise invalid_config(key="max_sessions", value=self.max_sessions, reason="must be positive")
        if self.max_stream_buffer_size < self.stream_buffer_size:
            raise invalid_config(
                key="max_stream_buffer_size",
                value=self.max_stream_buffer_size,
                reason="must be >= stream_buffer_size",
            )
        if self.max_streams_per_connection <= 0:
            raise invalid_config(
                key="max_streams_per_connection",
                value=self.max_streams_per_connection,
                reason="must be positive",
            )
        if self.max_total_pending_events <= 0:
            raise invalid_config(
                key="max_total_pending_events",
                value=self.max_total_pending_events,
                reason="must be positive",
            )
        if self.stream_buffer_size <= 0:
            raise invalid_config(
                key="stream_buffer_size",
                value=self.stream_buffer_size,
                reason="must be positive",
            )
        if self.stream_flow_control_increment_bidi <= 0:
            raise invalid_config(
                key="stream_flow_control_increment_bidi",
                value=self.stream_flow_control_increment_bidi,
                reason="must be positive",
            )
        if self.stream_flow_control_increment_uni <= 0:
            raise invalid_config(
                key="stream_flow_control_increment_uni",
                value=self.stream_flow_control_increment_uni,
                reason="must be positive",
            )

        if self.ca_certs and not Path(self.ca_certs).exists():
            raise certificate_not_found(path=self.ca_certs)
        if self.certfile and not Path(self.certfile).exists():
            raise certificate_not_found(path=self.certfile)
        if self.keyfile and not Path(self.keyfile).exists():
            raise certificate_not_found(path=self.keyfile)
        if bool(self.certfile) != bool(self.keyfile):
            raise invalid_config(
                key="certfile/keyfile",
                value=f"certfile={self.certfile}, keyfile={self.keyfile}",
                reason="certfile and keyfile must be provided together",
            )
        if self.verify_mode not in [
            ssl.CERT_NONE,
            ssl.CERT_OPTIONAL,
            ssl.CERT_REQUIRED,
        ]:
            raise invalid_config(key="verify_mode", value=self.verify_mode, reason="invalid SSL verify mode")


class ConfigBuilder:
    """A builder for fluently creating client or server configurations."""

    def __init__(self, *, config_type: str = "client"):
        """Initialize the configuration builder."""
        self.config_type = config_type
        self._config_dict: dict[str, Any] = {}

    def bind(self, *, host: str, port: int) -> Self:
        """Set the bind host and port (server only)."""
        if self.config_type != "server":
            raise ConfigurationError("bind() can only be used with server config")

        self._config_dict["bind_host"] = host
        self._config_dict["bind_port"] = port
        return self

    def build(self) -> ClientConfig | ServerConfig:
        """Build and return the final configuration object."""
        match self.config_type:
            case "client":
                return ClientConfig.create(**self._config_dict)
            case "server":
                return ServerConfig.create(**self._config_dict)
            case _:
                raise ConfigurationError(f"Unknown config type: {self.config_type}")

    def debug(self, *, enabled: bool = True, log_level: str = "DEBUG") -> Self:
        """Set debug and logging settings."""
        self._config_dict["debug"] = enabled
        self._config_dict["log_level"] = log_level
        return self

    def flow_control(
        self,
        *,
        window_size: int | None = None,
        window_auto_scale: bool | None = None,
        initial_max_data: int | None = None,
        initial_max_streams_bidi: int | None = None,
        initial_max_streams_uni: int | None = None,
        stream_increment_bidi: int | None = None,
        stream_increment_uni: int | None = None,
    ) -> Self:
        """Set flow control related settings."""
        if window_size is not None:
            self._config_dict["flow_control_window_size"] = window_size
        if window_auto_scale is not None:
            self._config_dict["flow_control_window_auto_scale"] = window_auto_scale
        if initial_max_data is not None:
            self._config_dict["initial_max_data"] = initial_max_data
        if initial_max_streams_bidi is not None:
            self._config_dict["initial_max_streams_bidi"] = initial_max_streams_bidi
        if initial_max_streams_uni is not None:
            self._config_dict["initial_max_streams_uni"] = initial_max_streams_uni
        if stream_increment_bidi is not None:
            self._config_dict["stream_flow_control_increment_bidi"] = stream_increment_bidi
        if stream_increment_uni is not None:
            self._config_dict["stream_flow_control_increment_uni"] = stream_increment_uni
        return self

    def performance(
        self,
        *,
        max_streams: int | None = None,
        buffer_size: int | None = None,
        max_connections: int | None = None,
    ) -> Self:
        """Set performance-related settings."""
        if max_streams is not None:
            if self.config_type == "client":
                self._config_dict["max_streams"] = max_streams
            else:
                self._config_dict["max_streams_per_connection"] = max_streams
        if buffer_size is not None:
            self._config_dict["stream_buffer_size"] = buffer_size
        if max_connections is not None and self.config_type == "server":
            self._config_dict["max_connections"] = max_connections
        return self

    def security(
        self,
        *,
        certfile: str | None = None,
        keyfile: str | None = None,
        ca_certs: str | None = None,
        verify_mode: ssl.VerifyMode | None = None,
    ) -> Self:
        """Set security and SSL/TLS settings."""
        if certfile is not None:
            self._config_dict["certfile"] = certfile
        if keyfile is not None:
            self._config_dict["keyfile"] = keyfile
        if ca_certs is not None:
            self._config_dict["ca_certs"] = ca_certs
        if verify_mode is not None:
            self._config_dict["verify_mode"] = verify_mode
        return self

    def timeout(
        self,
        *,
        connect: float | None = None,
        read: float | None = None,
        write: float | None = None,
    ) -> Self:
        """Set timeout values for the configuration."""
        if connect is not None:
            self._config_dict["connect_timeout"] = connect
        if read is not None:
            self._config_dict["read_timeout"] = read
        if write is not None:
            self._config_dict["write_timeout"] = write
        return self


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
