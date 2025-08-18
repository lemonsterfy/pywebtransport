"""
WebTransport Configuration.
"""

from __future__ import annotations

import copy
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from pywebtransport.constants import Defaults, WebTransportConstants
from pywebtransport.exceptions import ConfigurationError, certificate_not_found, invalid_config
from pywebtransport.types import Address, Headers
from pywebtransport.utils import normalize_headers
from pywebtransport.version import __version__

__all__ = [
    "ClientConfig",
    "ConfigBuilder",
    "ServerConfig",
]


def _validate_timeout(timeout: float | None) -> None:
    """Validate a timeout value."""
    if timeout is not None:
        if not isinstance(timeout, (int, float)):
            raise TypeError("Timeout must be a number or None")
        if timeout <= 0:
            raise ValueError("Timeout must be positive")


def _validate_port(port: Any) -> None:
    """Validate that a value is a valid network port."""
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"Port must be an integer between 1 and 65535, got {port}")


@dataclass
class ClientConfig:
    """A comprehensive configuration for the WebTransport client."""

    connect_timeout: float = WebTransportConstants.DEFAULT_CONNECT_TIMEOUT
    read_timeout: float | None = WebTransportConstants.DEFAULT_READ_TIMEOUT
    write_timeout: float | None = WebTransportConstants.DEFAULT_WRITE_TIMEOUT
    close_timeout: float = WebTransportConstants.DEFAULT_CLOSE_TIMEOUT
    stream_creation_timeout: float = WebTransportConstants.DEFAULT_STREAM_CREATION_TIMEOUT
    connection_keepalive_timeout: float = WebTransportConstants.DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT
    connection_cleanup_interval: float = WebTransportConstants.DEFAULT_CONNECTION_CLEANUP_INTERVAL
    connection_idle_timeout: float = WebTransportConstants.DEFAULT_CONNECTION_IDLE_TIMEOUT
    connection_idle_check_interval: float = WebTransportConstants.DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL
    stream_cleanup_interval: float = WebTransportConstants.DEFAULT_STREAM_CLEANUP_INTERVAL
    max_connections: int = WebTransportConstants.DEFAULT_CLIENT_MAX_CONNECTIONS
    max_streams: int = WebTransportConstants.DEFAULT_MAX_STREAMS
    max_incoming_streams: int = WebTransportConstants.DEFAULT_MAX_INCOMING_STREAMS
    stream_buffer_size: int = WebTransportConstants.DEFAULT_BUFFER_SIZE
    max_stream_buffer_size: int = WebTransportConstants.MAX_BUFFER_SIZE
    verify_mode: ssl.VerifyMode | None = ssl.CERT_REQUIRED
    ca_certs: str | None = None
    certfile: str | None = None
    keyfile: str | None = None
    check_hostname: bool = True
    keep_alive: bool = True
    alpn_protocols: list[str] = field(default_factory=lambda: list(WebTransportConstants.DEFAULT_ALPN_PROTOCOLS))
    http_version: str = "3"
    user_agent: str = f"pywebtransport/{__version__}"
    headers: Headers = field(default_factory=dict)
    max_datagram_size: int = WebTransportConstants.MAX_DATAGRAM_SIZE
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    max_retry_delay: float = 30.0
    debug: bool = False
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Normalize headers and validate the configuration after initialization."""
        self.headers = normalize_headers(self.headers)
        if "user-agent" not in self.headers:
            self.headers["user-agent"] = self.user_agent
        self.validate()

    @classmethod
    def create(cls, **kwargs: Any) -> Self:
        """Factory method to create a client configuration with specified overrides."""
        config_dict = {**Defaults.get_client_config(), **kwargs}
        return cls.from_dict(config_dict)

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
        cls, *, ca_certs: str | None = None, certfile: str | None = None, keyfile: str | None = None
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
    def from_dict(cls, config_dict: dict[str, Any]) -> Self:
        """Create a ClientConfig instance from a dictionary."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_keys}
        return cls(**filtered_dict)

    def validate(self) -> None:
        """Validate the integrity and correctness of the configuration values."""
        try:
            _validate_timeout(self.connect_timeout)
            _validate_timeout(self.read_timeout)
            _validate_timeout(self.write_timeout)
            _validate_timeout(self.stream_creation_timeout)
            _validate_timeout(self.close_timeout)
            _validate_timeout(self.connection_keepalive_timeout)
            _validate_timeout(self.connection_cleanup_interval)
            _validate_timeout(self.connection_idle_timeout)
            _validate_timeout(self.connection_idle_check_interval)
            _validate_timeout(self.stream_cleanup_interval)
        except ValueError as e:
            raise invalid_config("timeout", str(e), "invalid timeout value") from e
        if self.max_connections <= 0:
            raise invalid_config("max_connections", self.max_connections, "must be positive")
        if self.max_streams <= 0:
            raise invalid_config("max_streams", self.max_streams, "must be positive")
        if self.max_incoming_streams <= 0:
            raise invalid_config("max_incoming_streams", self.max_incoming_streams, "must be positive")
        if self.stream_buffer_size <= 0:
            raise invalid_config("stream_buffer_size", self.stream_buffer_size, "must be positive")
        if self.max_stream_buffer_size < self.stream_buffer_size:
            raise invalid_config("max_stream_buffer_size", self.max_stream_buffer_size, "must be >= stream_buffer_size")
        if self.verify_mode not in [ssl.CERT_NONE, ssl.CERT_OPTIONAL, ssl.CERT_REQUIRED, None]:
            raise invalid_config("verify_mode", self.verify_mode, "invalid SSL verify mode")
        if self.certfile and not Path(self.certfile).exists():
            raise certificate_not_found(self.certfile)
        if self.keyfile and not Path(self.keyfile).exists():
            raise certificate_not_found(self.keyfile)
        if self.ca_certs and not Path(self.ca_certs).exists():
            raise certificate_not_found(self.ca_certs)
        if bool(self.certfile) != bool(self.keyfile):
            raise invalid_config(
                "certfile/keyfile",
                f"certfile={self.certfile}, keyfile={self.keyfile}",
                "both must be provided together",
            )
        if self.http_version not in ["2", "3"]:
            raise invalid_config("http_version", self.http_version, "must be '2' or '3'")
        if not self.alpn_protocols:
            raise invalid_config("alpn_protocols", self.alpn_protocols, "cannot be empty")
        if self.max_datagram_size <= 0 or self.max_datagram_size > 65535:
            raise invalid_config("max_datagram_size", self.max_datagram_size, "must be 1-65535")
        if self.max_retries < 0:
            raise invalid_config("max_retries", self.max_retries, "must be non-negative")
        if self.retry_delay <= 0:
            raise invalid_config("retry_delay", self.retry_delay, "must be positive")
        if self.retry_backoff < 1.0:
            raise invalid_config("retry_backoff", self.retry_backoff, "must be >= 1.0")
        if self.max_retry_delay <= 0:
            raise invalid_config("max_retry_delay", self.max_retry_delay, "must be positive")

    def copy(self) -> Self:
        """Create a deep copy of the configuration."""
        return copy.deepcopy(self)

    def update(self, **kwargs: Any) -> Self:
        """Create a new config with updated values."""
        new_config = self.copy()
        for key, value in kwargs.items():
            if hasattr(new_config, key):
                setattr(new_config, key, value)
            else:
                raise invalid_config(key, value, "unknown configuration key")
        new_config.validate()
        return new_config

    def merge(self, other: ClientConfig | dict[str, Any]) -> Self:
        """Merge this configuration with another config or dictionary."""
        if isinstance(other, dict):
            return self.update(**other)
        if isinstance(other, ClientConfig):
            update_dict = {
                f.name: getattr(other, f.name)
                for f in other.__dataclass_fields__.values()
                if getattr(other, f.name) is not None
            }
            return self.update(**update_dict)
        raise TypeError("Can only merge with ClientConfig or dict")

    def to_dict(self) -> dict[str, Any]:
        """Convert the configuration to a dictionary."""
        result = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, ssl.VerifyMode):
                result[field_name] = value.name
            elif isinstance(value, Path):
                result[field_name] = str(value)
            else:
                result[field_name] = value
        return result


@dataclass
class ServerConfig:
    """A comprehensive configuration for the WebTransport server."""

    bind_host: str = "localhost"
    bind_port: int = WebTransportConstants.DEFAULT_DEV_PORT
    max_connections: int = WebTransportConstants.DEFAULT_SERVER_MAX_CONNECTIONS
    max_sessions: int = WebTransportConstants.DEFAULT_MAX_SESSIONS
    max_streams_per_connection: int = WebTransportConstants.DEFAULT_MAX_STREAMS_PER_CONNECTION
    max_incoming_streams: int = WebTransportConstants.DEFAULT_MAX_INCOMING_STREAMS
    connection_keepalive_timeout: float = WebTransportConstants.DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT
    connection_cleanup_interval: float = WebTransportConstants.DEFAULT_CONNECTION_CLEANUP_INTERVAL
    connection_idle_timeout: float = WebTransportConstants.DEFAULT_CONNECTION_IDLE_TIMEOUT
    connection_idle_check_interval: float = WebTransportConstants.DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL
    session_cleanup_interval: float = WebTransportConstants.DEFAULT_SESSION_CLEANUP_INTERVAL
    stream_cleanup_interval: float = WebTransportConstants.DEFAULT_STREAM_CLEANUP_INTERVAL
    read_timeout: float | None = WebTransportConstants.DEFAULT_READ_TIMEOUT
    write_timeout: float | None = WebTransportConstants.DEFAULT_WRITE_TIMEOUT
    certfile: str = ""
    keyfile: str = ""
    ca_certs: str | None = None
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE
    alpn_protocols: list[str] = field(default_factory=lambda: list(WebTransportConstants.DEFAULT_ALPN_PROTOCOLS))
    http_version: str = "3"
    backlog: int = 128
    reuse_port: bool = True
    keep_alive: bool = True
    stream_buffer_size: int = WebTransportConstants.DEFAULT_BUFFER_SIZE
    max_stream_buffer_size: int = WebTransportConstants.MAX_BUFFER_SIZE
    max_datagram_size: int = WebTransportConstants.MAX_DATAGRAM_SIZE
    middleware: list[Any] = field(default_factory=list)
    debug: bool = False
    log_level: str = "INFO"
    access_log: bool = True

    def __post_init__(self) -> None:
        """Validate the configuration after initialization."""
        self.validate()

    @classmethod
    def create(cls, **kwargs: Any) -> Self:
        """Factory method to create a server configuration with specified overrides."""
        config_dict = {**Defaults.get_server_config(), **kwargs}
        return cls.from_dict(config_dict)

    @classmethod
    def create_for_development(
        cls, *, host: str = "localhost", port: int = 4433, certfile: str | None = None, keyfile: str | None = None
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
        cls, *, host: str, port: int, certfile: str, keyfile: str, ca_certs: str | None = None
    ) -> Self:
        """Factory method to create a server configuration suitable for production."""
        return cls.create(
            bind_host=host,
            bind_port=port,
            certfile=certfile,
            keyfile=keyfile,
            ca_certs=ca_certs,
            verify_mode=ssl.CERT_OPTIONAL if ca_certs else ssl.CERT_NONE,
            max_connections=WebTransportConstants.DEFAULT_SERVER_MAX_CONNECTIONS,
            max_streams_per_connection=WebTransportConstants.DEFAULT_MAX_STREAMS_PER_CONNECTION,
            debug=False,
            log_level="INFO",
        )

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Self:
        """Create a ServerConfig instance from a dictionary."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_dict = {k: v for k, v in config_dict.items() if k in valid_keys}
        return cls(**filtered_dict)

    def validate(self) -> None:
        """Validate the integrity and correctness of the configuration values."""
        if not self.bind_host:
            raise invalid_config("bind_host", self.bind_host, "cannot be empty")
        try:
            _validate_port(self.bind_port)
        except ValueError as e:
            raise invalid_config("bind_port", self.bind_port, str(e)) from e
        if self.max_connections <= 0:
            raise invalid_config("max_connections", self.max_connections, "must be positive")
        if self.max_sessions <= 0:
            raise invalid_config("max_sessions", self.max_sessions, "must be positive")
        if self.max_streams_per_connection <= 0:
            raise invalid_config("max_streams_per_connection", self.max_streams_per_connection, "must be positive")
        if self.max_incoming_streams <= 0:
            raise invalid_config("max_incoming_streams", self.max_incoming_streams, "must be positive")
        try:
            _validate_timeout(self.connection_keepalive_timeout)
            _validate_timeout(self.connection_cleanup_interval)
            _validate_timeout(self.connection_idle_timeout)
            _validate_timeout(self.connection_idle_check_interval)
            _validate_timeout(self.session_cleanup_interval)
            _validate_timeout(self.stream_cleanup_interval)
            _validate_timeout(self.read_timeout)
            _validate_timeout(self.write_timeout)
        except ValueError as e:
            raise invalid_config("timeout", str(e), "invalid timeout value") from e
        if self.certfile and not Path(self.certfile).exists():
            raise certificate_not_found(self.certfile)
        if self.keyfile and not Path(self.keyfile).exists():
            raise certificate_not_found(self.keyfile)
        if bool(self.certfile) != bool(self.keyfile):
            raise invalid_config(
                "certfile/keyfile",
                f"certfile={self.certfile}, keyfile={self.keyfile}",
                "certfile and keyfile must be provided together",
            )
        if self.ca_certs and not Path(self.ca_certs).exists():
            raise certificate_not_found(self.ca_certs)
        if self.verify_mode not in [ssl.CERT_NONE, ssl.CERT_OPTIONAL, ssl.CERT_REQUIRED]:
            raise invalid_config("verify_mode", self.verify_mode, "invalid SSL verify mode")
        if self.http_version not in ["2", "3"]:
            raise invalid_config("http_version", self.http_version, "must be '2' or '3'")
        if not self.alpn_protocols:
            raise invalid_config("alpn_protocols", self.alpn_protocols, "cannot be empty")
        if self.backlog <= 0:
            raise invalid_config("backlog", self.backlog, "must be positive")
        if self.stream_buffer_size <= 0:
            raise invalid_config("stream_buffer_size", self.stream_buffer_size, "must be positive")
        if self.max_stream_buffer_size < self.stream_buffer_size:
            raise invalid_config("max_stream_buffer_size", self.max_stream_buffer_size, "must be >= stream_buffer_size")
        if self.max_datagram_size <= 0 or self.max_datagram_size > 65535:
            raise invalid_config("max_datagram_size", self.max_datagram_size, "must be 1-65535")

    def copy(self) -> Self:
        """Create a deep copy of the configuration."""
        return copy.deepcopy(self)

    def update(self, **kwargs: Any) -> Self:
        """Create a new config with updated values."""
        new_config = self.copy()
        for key, value in kwargs.items():
            if hasattr(new_config, key):
                setattr(new_config, key, value)
            else:
                raise invalid_config(key, value, "unknown configuration key")
        new_config.validate()
        return new_config

    def merge(self, other: ServerConfig | dict[str, Any]) -> Self:
        """Merge this configuration with another config or dictionary."""
        if isinstance(other, dict):
            return self.update(**other)
        if isinstance(other, ServerConfig):
            update_dict = {
                f.name: getattr(other, f.name)
                for f in other.__dataclass_fields__.values()
                if getattr(other, f.name) is not None
            }
            return self.update(**update_dict)
        raise TypeError("Can only merge with ServerConfig or dict")

    def to_dict(self) -> dict[str, Any]:
        """Convert the configuration to a dictionary."""
        result = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, ssl.VerifyMode):
                result[field_name] = value.name
            elif isinstance(value, Path):
                result[field_name] = str(value)
            else:
                result[field_name] = value
        return result

    def get_bind_address(self) -> Address:
        """Get the bind address as a (host, port) tuple."""
        return (self.bind_host, self.bind_port)


class ConfigBuilder:
    """A builder for fluently creating client or server configurations."""

    def __init__(self, config_type: str = "client"):
        """Initialize the configuration builder."""
        self.config_type = config_type
        self._config_dict: dict[str, Any] = {}

    def bind(self, host: str, port: int) -> Self:
        """Set the bind host and port (server only)."""
        if self.config_type != "server":
            raise ConfigurationError("bind() can only be used with server config")
        self._config_dict["bind_host"] = host
        self._config_dict["bind_port"] = port
        return self

    def debug(self, *, enabled: bool = True, log_level: str = "DEBUG") -> Self:
        """Set debug and logging settings."""
        self._config_dict["debug"] = enabled
        self._config_dict["log_level"] = log_level
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

    def timeout(self, *, connect: float | None = None, read: float | None = None, write: float | None = None) -> Self:
        """Set timeout values for the configuration."""
        if connect is not None:
            self._config_dict["connect_timeout"] = connect
        if read is not None:
            self._config_dict["read_timeout"] = read
        if write is not None:
            self._config_dict["write_timeout"] = write
        return self

    def build(self) -> ClientConfig | ServerConfig:
        """Build and return the final configuration object."""
        if self.config_type == "client":
            return ClientConfig.create(**self._config_dict)
        if self.config_type == "server":
            return ServerConfig.create(**self._config_dict)
        raise ConfigurationError(f"Unknown config type: {self.config_type}")
