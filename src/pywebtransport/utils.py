"""Shared, general-purpose utilities."""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Self

from aioquic.quic.configuration import QuicConfiguration
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from pywebtransport.types import Buffer

__all__: list[str] = [
    "Timer",
    "create_quic_configuration",
    "ensure_bytes",
    "format_duration",
    "generate_self_signed_cert",
    "generate_session_id",
    "get_logger",
    "get_timestamp",
]


class Timer:
    """A simple context manager for performance measurement."""

    def __init__(self, *, name: str = "timer") -> None:
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
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Stop the timer and log the duration upon exiting the context."""
        elapsed = self.stop()
        logger = get_logger(name="timer")
        logger.debug("%s took %s", self.name, format_duration(seconds=elapsed))

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


def create_quic_configuration(
    *,
    alpn_protocols: list[str],
    congestion_control_algorithm: str,
    idle_timeout: float,
    is_client: bool,
    max_datagram_size: int,
) -> QuicConfiguration:
    """Create a QUIC configuration from specific, required parameters."""
    return QuicConfiguration(
        alpn_protocols=alpn_protocols,
        congestion_control_algorithm=congestion_control_algorithm,
        idle_timeout=idle_timeout,
        is_client=is_client,
        max_datagram_frame_size=max_datagram_size,
    )


def ensure_bytes(*, data: Buffer | str, encoding: str = "utf-8") -> bytes:
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


def format_duration(*, seconds: float) -> str:
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


def generate_self_signed_cert(
    *, hostname: str, output_dir: str = ".", days_valid: int = 365, key_size: int = 2048
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


def get_logger(*, name: str) -> logging.Logger:
    """Get a logger instance with a specific name."""
    return logging.getLogger(name)


def get_timestamp() -> float:
    """Get the current Unix timestamp."""
    return time.time()
