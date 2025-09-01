"""
Core Library Utilities.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import secrets
import socket
import ssl
import time
import urllib.parse
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Self, Type, TypeVar

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from pywebtransport.constants import (
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_LEVEL,
    SECURE_SCHEMES,
    WEBTRANSPORT_SCHEMES,
    WebTransportConstants,
)
from pywebtransport.exceptions import CertificateError, ConfigurationError, TimeoutError, certificate_not_found
from pywebtransport.types import URL, Address, Buffer, Timeout, URLParts

__all__ = [
    "Timer",
    "build_webtransport_url",
    "calculate_checksum",
    "chunked_read",
    "create_task_with_timeout",
    "ensure_bytes",
    "ensure_str",
    "format_bytes",
    "format_duration",
    "format_timestamp",
    "generate_connection_id",
    "generate_request_id",
    "generate_self_signed_cert",
    "generate_session_id",
    "get_logger",
    "get_timestamp",
    "is_ipv4_address",
    "is_ipv6_address",
    "load_certificate",
    "merge_configs",
    "normalize_headers",
    "parse_webtransport_url",
    "resolve_address",
    "run_with_timeout",
    "setup_logging",
    "validate_address",
    "validate_error_code",
    "validate_port",
    "validate_session_id",
    "validate_stream_id",
    "validate_url",
    "wait_for_condition",
]

T = TypeVar("T")


class Timer:
    """A simple context manager for performance measurement."""

    def __init__(self, name: str = "timer"):
        """Initialize the timer."""
        self.name = name
        self.start_time: float | None = None
        self.end_time: float | None = None

    @property
    def elapsed(self) -> float:
        """Get the elapsed time in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time

    def __enter__(self) -> Self:
        """Start the timer upon entering the context."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Stop the timer and log the duration upon exiting the context."""
        elapsed = self.stop()
        logger = get_logger("timer")
        logger.debug(f"{self.name} took {format_duration(elapsed)}")

    def start(self) -> None:
        """Start the timer."""
        self.start_time = time.time()
        self.end_time = None

    def stop(self) -> float:
        """Stop the timer and return the elapsed time."""
        if self.start_time is None:
            raise RuntimeError("Timer not started")
        self.end_time = time.time()
        return self.elapsed


def build_webtransport_url(
    host: str, port: int, *, path: str = "/", secure: bool = True, query_params: dict[str, str] | None = None
) -> URL:
    """Build a WebTransport URL from its components."""
    scheme = "https" if secure else "http"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    query = ""
    if query_params:
        query = "?" + urllib.parse.urlencode(query_params)
    if (secure and port == WebTransportConstants.DEFAULT_SECURE_PORT) or (
        not secure and port == WebTransportConstants.DEFAULT_PORT
    ):
        return f"{scheme}://{host}{path}{query}"
    return f"{scheme}://{host}:{port}{path}{query}"


def calculate_checksum(data: bytes, *, algorithm: str = "sha256") -> str:
    """Calculate the checksum of data using a specified secure hash algorithm."""
    if algorithm not in hashlib.algorithms_guaranteed:
        raise ValueError(f"Unsupported or insecure hash algorithm: {algorithm}")
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(data)
    return hash_obj.hexdigest()


def chunked_read(data: bytes, *, chunk_size: int = 8192) -> list[bytes]:
    """Split data into a list of chunks of a specified size."""
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive")
    return [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]


async def create_task_with_timeout(
    coro: Coroutine[Any, Any, T], *, timeout: Timeout | None = None, name: str | None = None
) -> asyncio.Task[T]:
    """Create an asyncio task with an optional timeout wrapper."""
    if timeout is None:
        return asyncio.create_task(coro, name=name)

    async def _wrapper() -> T:
        return await asyncio.wait_for(coro, timeout=timeout)

    return asyncio.create_task(_wrapper(), name=name)


def ensure_bytes(data: Buffer | str, *, encoding: str = "utf-8") -> bytes:
    """Ensure that the given data is in bytes format."""
    match data:
        case str():
            return data.encode(encoding)
        case bytes():
            return data
        case bytearray() | memoryview():
            return bytes(data)
        case _:
            raise TypeError(f"Expected str, bytes, bytearray, or memoryview, got {type(data).__name__}")


def ensure_str(data: Buffer | str, *, encoding: str = "utf-8") -> str:
    """Ensure that the given data is in string format."""
    match data:
        case str():
            return data
        case bytes() | bytearray() | memoryview():
            return bytes(data).decode(encoding)
        case _:
            raise TypeError(f"Expected str, bytes, bytearray, or memoryview, got {type(data).__name__}")


def format_bytes(data: bytes, *, max_length: int = 100) -> str:
    """Format bytes for readable debugging output."""
    if len(data) <= max_length:
        return repr(data)
    return f"{repr(data[:max_length])}... ({len(data)} bytes total)"


def format_duration(seconds: float) -> str:
    """Format a duration in seconds into a human-readable string."""
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m{secs:.1f}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}h{minutes}m{secs:.1f}s"


def format_timestamp(timestamp: float) -> str:
    """Format a Unix timestamp into an ISO 8601 string."""
    return datetime.fromtimestamp(timestamp).isoformat()


def generate_connection_id() -> str:
    """Generate a unique, URL-safe connection ID."""
    return secrets.token_urlsafe(12)


def generate_request_id() -> str:
    """Generate a unique, URL-safe request ID."""
    return secrets.token_urlsafe(8)


def generate_self_signed_cert(
    hostname: str, *, output_dir: str = ".", key_size: int = 2048, days_valid: int = 365
) -> tuple[str, str]:
    """Generate a self-signed certificate and key for testing purposes."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "pywebtransport"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=days_valid))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    cert_file = output_path / f"{hostname}.crt"
    key_file = output_path / f"{hostname}.key"
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_file, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    return (str(cert_file), str(key_file))


def generate_session_id() -> str:
    """Generate a unique, URL-safe session ID."""
    return secrets.token_urlsafe(16)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with a specific name."""
    return logging.getLogger(f"pywebtransport.{name}")


def get_timestamp() -> float:
    """Get the current Unix timestamp."""
    return time.time()


@functools.cache
def is_ipv4_address(host: str) -> bool:
    """Check if a host string is a valid IPv4 address."""
    try:
        socket.inet_aton(host)
        return True
    except socket.error:
        return False


@functools.cache
def is_ipv6_address(host: str) -> bool:
    """Check if a host string is a valid IPv6 address."""
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except socket.error:
        return False


def load_certificate(certfile: str, keyfile: str) -> ssl.SSLContext:
    """Load an SSL certificate and private key into an SSL context."""
    if not Path(certfile).exists():
        raise certificate_not_found(certfile)
    if not Path(keyfile).exists():
        raise certificate_not_found(keyfile)

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(certfile, keyfile)
        return context
    except Exception as e:
        raise CertificateError(f"Failed to load certificate: {e}")


def merge_configs(base_config: dict[str, Any], override_config: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge two configuration dictionaries."""
    result = base_config.copy()
    for key, value in override_config.items():
        match (result.get(key), value):
            case (dict() as base_dict, dict() as override_dict):
                result[key] = merge_configs(base_dict, override_dict)
            case _:
                result[key] = value
    return result


def normalize_headers(headers: dict[str, Any]) -> dict[str, str]:
    """Normalize header keys to lowercase and values to strings."""
    return {str(key).lower(): str(value) for key, value in headers.items()}


@functools.cache
def parse_webtransport_url(url: URL) -> URLParts:
    """Parse a WebTransport URL into its host, port, and path components."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in WEBTRANSPORT_SCHEMES:
        raise ConfigurationError(
            f"Unsupported scheme '{parsed.scheme}'. Must be one of: {WEBTRANSPORT_SCHEMES}", config_key="url"
        )
    if not parsed.hostname:
        raise ConfigurationError("Missing hostname in URL", config_key="url")

    match parsed:
        case urllib.parse.ParseResult(port=p) if p:
            port = p
        case urllib.parse.ParseResult(scheme=s) if s in SECURE_SCHEMES:
            port = WebTransportConstants.DEFAULT_SECURE_PORT
        case _:
            port = WebTransportConstants.DEFAULT_PORT

    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    if parsed.fragment:
        path += f"#{parsed.fragment}"
    return (parsed.hostname, port, path)


async def resolve_address(host: str, port: int, *, family: int = socket.AF_UNSPEC) -> Address:
    """Resolve a hostname to an IP address asynchronously."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.getaddrinfo(host, port, family=family, type=socket.SOCK_DGRAM)
        if not result:
            raise OSError(f"No address found for {host}:{port}")
        family, type_, proto, canonname, sockaddr = result[0]
        return (sockaddr[0], sockaddr[1])
    except OSError as e:
        raise ConfigurationError(f"Failed to resolve address {host}:{port}: {e}")


async def run_with_timeout(coro: Coroutine[Any, Any, T], *, timeout: float, default_value: T | None = None) -> T | None:
    """Run a coroutine with a timeout, returning a default value on timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return default_value


def setup_logging(
    *, level: str = DEFAULT_LOG_LEVEL, format_string: str | None = None, logger_name: str = "pywebtransport"
) -> logging.Logger:
    """Set up and configure the main logger."""
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {level}")
    logger.setLevel(numeric_level)
    handler = logging.StreamHandler()
    handler.setLevel(numeric_level)
    formatter = logging.Formatter(format_string or DEFAULT_LOG_FORMAT)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def validate_address(address: Any) -> None:
    """Validate a (host, port) address tuple."""
    if not isinstance(address, tuple) or len(address) != 2:
        raise TypeError("Address must be a (host, port) tuple")
    if not isinstance(address[0], str):
        raise TypeError("Host in address tuple must be a string")
    if not isinstance(address[1], int) or not (1 <= address[1] <= 65535):
        raise ValueError(f"Port must be an integer between 1 and 65535, got {address[1]}")


def validate_error_code(error_code: Any) -> None:
    """Validate a protocol error code."""
    if not isinstance(error_code, int):
        raise TypeError("Error code must be an integer")
    if not (0 <= error_code <= 2**32 - 1):
        raise ValueError(f"Error code {error_code} out of valid range")


def validate_port(port: Any) -> None:
    """Validate that a value is a valid network port."""
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(f"Port must be an integer between 1 and 65535, got {port}")


def validate_session_id(session_id: Any) -> None:
    """Validate a WebTransport session ID."""
    if not isinstance(session_id, str):
        raise TypeError("Session ID must be a string")
    if not session_id:
        raise ValueError("Session ID cannot be empty")


def validate_stream_id(stream_id: Any) -> None:
    """Validate a WebTransport stream ID."""
    if not isinstance(stream_id, int):
        raise TypeError("Stream ID must be an integer")
    if not (0 <= stream_id <= WebTransportConstants.MAX_STREAM_ID):
        raise ValueError(f"Stream ID {stream_id} out of valid range")


def validate_url(url: URL) -> bool:
    """Validate the format of a WebTransport URL."""
    try:
        parse_webtransport_url(url)
        return True
    except Exception:
        return False


async def wait_for_condition(
    condition: Callable[[], bool], *, timeout: Timeout | None = None, interval: float = 0.1
) -> None:
    """Wait for a condition to become true, with an optional timeout."""

    async def _waiter() -> None:
        while not condition():
            await asyncio.sleep(interval)

    if timeout is None:
        await _waiter()
    else:
        try:
            await asyncio.wait_for(_waiter(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"Condition not met within {timeout}s timeout") from e
