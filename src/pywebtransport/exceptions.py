"""
WebTransport Exceptions.
"""

from typing import Any, Dict, Optional, Tuple, Type

from pywebtransport.constants import ErrorCodes
from pywebtransport.types import SessionState, StreamState

__all__ = [
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
    "certificate_not_found",
    "connection_timeout",
    "datagram_too_large",
    "get_error_category",
    "invalid_config",
    "is_fatal_error",
    "is_retriable_error",
    "protocol_violation",
    "session_not_ready",
    "stream_closed",
]


class WebTransportError(Exception):
    """The base exception for all WebTransport errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the WebTransport error."""
        super().__init__(message)
        self.message = message
        self.error_code = error_code or ErrorCodes.INTERNAL_ERROR
        self.details = details or {}

    def __repr__(self) -> str:
        """Return a detailed string representation of the error."""
        return f"{self.__class__.__name__}(message='{self.message}', error_code={self.error_code})"

    def __str__(self) -> str:
        """Return a simple string representation of the error."""
        return f"[{self.error_code}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary for serialization."""
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


class AuthenticationError(WebTransportError):
    """An exception for authentication-related errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        auth_method: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the authentication error."""
        super().__init__(message, error_code=error_code or ErrorCodes.APP_AUTHENTICATION_FAILED, details=details)
        self.auth_method = auth_method

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["auth_method"] = self.auth_method
        return data


class CertificateError(WebTransportError):
    """An exception for certificate-related errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        certificate_path: Optional[str] = None,
        certificate_error: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the certificate error."""
        super().__init__(message, error_code=error_code or ErrorCodes.APP_AUTHENTICATION_FAILED, details=details)
        self.certificate_path = certificate_path
        self.certificate_error = certificate_error

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["certificate_path"] = self.certificate_path
        data["certificate_error"] = self.certificate_error
        return data


class ClientError(WebTransportError):
    """An exception for client-specific errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        target_url: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the client error."""
        super().__init__(message, error_code=error_code or ErrorCodes.APP_INVALID_REQUEST, details=details)
        self.target_url = target_url

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["target_url"] = self.target_url
        return data


class ConfigurationError(WebTransportError):
    """An exception for configuration-related errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        config_key: Optional[str] = None,
        config_value: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the configuration error."""
        super().__init__(message, error_code=error_code or ErrorCodes.APP_INVALID_REQUEST, details=details)
        self.config_key = config_key
        self.config_value = config_value

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["config_key"] = self.config_key
        data["config_value"] = self.config_value
        return data


class ConnectionError(WebTransportError):
    """An exception for connection-related errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        remote_address: Optional[Tuple[str, int]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the connection error."""
        super().__init__(message, error_code=error_code or ErrorCodes.CONNECTION_REFUSED, details=details)
        self.remote_address = remote_address

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["remote_address"] = self.remote_address
        return data


class DatagramError(WebTransportError):
    """An exception for datagram-related errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        datagram_size: Optional[int] = None,
        max_size: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the datagram error."""
        super().__init__(message, error_code=error_code or ErrorCodes.INTERNAL_ERROR, details=details)
        self.datagram_size = datagram_size
        self.max_size = max_size

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["datagram_size"] = self.datagram_size
        data["max_size"] = self.max_size
        return data


class FlowControlError(WebTransportError):
    """An exception for flow control errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        stream_id: Optional[int] = None,
        limit_exceeded: Optional[int] = None,
        current_value: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the flow control error."""
        super().__init__(message, error_code=error_code or ErrorCodes.FLOW_CONTROL_ERROR, details=details)
        self.stream_id = stream_id
        self.limit_exceeded = limit_exceeded
        self.current_value = current_value

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["stream_id"] = self.stream_id
        data["limit_exceeded"] = self.limit_exceeded
        data["current_value"] = self.current_value
        return data


class HandshakeError(WebTransportError):
    """An exception for handshake-related errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        handshake_stage: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the handshake error."""
        super().__init__(message, error_code=error_code or ErrorCodes.INTERNAL_ERROR, details=details)
        self.handshake_stage = handshake_stage

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["handshake_stage"] = self.handshake_stage
        return data


class ProtocolError(WebTransportError):
    """An exception for protocol violation errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        frame_type: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the protocol error."""
        super().__init__(message, error_code=error_code or ErrorCodes.PROTOCOL_VIOLATION, details=details)
        self.frame_type = frame_type

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["frame_type"] = self.frame_type
        return data


class ServerError(WebTransportError):
    """An exception for server-specific errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        bind_address: Optional[Tuple[str, int]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the server error."""
        super().__init__(message, error_code=error_code or ErrorCodes.APP_SERVICE_UNAVAILABLE, details=details)
        self.bind_address = bind_address

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["bind_address"] = self.bind_address
        return data


class SessionError(WebTransportError):
    """An exception for WebTransport session errors."""

    def __init__(
        self,
        message: str,
        *,
        session_id: Optional[str] = None,
        error_code: Optional[int] = None,
        session_state: Optional[SessionState] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the session error."""
        super().__init__(message, error_code=error_code or ErrorCodes.INTERNAL_ERROR, details=details)
        self.session_id = session_id
        self.session_state = session_state

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["session_id"] = self.session_id
        data["session_state"] = self.session_state.value if self.session_state else None
        return data


class StreamError(WebTransportError):
    """An exception for stream-related errors."""

    def __init__(
        self,
        message: str,
        *,
        stream_id: Optional[int] = None,
        error_code: Optional[int] = None,
        stream_state: Optional[StreamState] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the stream error."""
        super().__init__(message, error_code=error_code or ErrorCodes.STREAM_STATE_ERROR, details=details)
        self.stream_id = stream_id
        self.stream_state = stream_state

    def __str__(self) -> str:
        """Return a simple string representation of the error."""
        base_msg = super().__str__()
        if self.stream_id is not None:
            return f"{base_msg} (stream_id={self.stream_id})"
        return base_msg

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["stream_id"] = self.stream_id
        data["stream_state"] = self.stream_state.value if self.stream_state else None
        return data


class TimeoutError(WebTransportError):
    """An exception for timeout-related errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[int] = None,
        timeout_duration: Optional[float] = None,
        operation: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the timeout error."""
        super().__init__(message, error_code=error_code or ErrorCodes.APP_CONNECTION_TIMEOUT, details=details)
        self.timeout_duration = timeout_duration
        self.operation = operation

    def to_dict(self) -> Dict[str, Any]:
        """Convert the exception to a dictionary."""
        data = super().to_dict()
        data["timeout_duration"] = self.timeout_duration
        data["operation"] = self.operation
        return data


def certificate_not_found(path: str) -> CertificateError:
    """Create a certificate not found error."""
    return CertificateError(
        f"Certificate file not found: {path}", certificate_path=path, certificate_error="file_not_found"
    )


def connection_timeout(timeout_duration: float, operation: str = "connect") -> TimeoutError:
    """Create a connection timeout error."""
    return TimeoutError(
        f"Connection timeout after {timeout_duration}s during {operation}",
        timeout_duration=timeout_duration,
        operation=operation,
    )


def datagram_too_large(size: int, max_size: int) -> DatagramError:
    """Create a datagram too large error."""
    return DatagramError(f"Datagram size {size} exceeds maximum {max_size}", datagram_size=size, max_size=max_size)


def invalid_config(key: str, value: Any, reason: str) -> ConfigurationError:
    """Create an invalid configuration error."""
    return ConfigurationError(f"Invalid configuration for '{key}': {reason}", config_key=key, config_value=value)


def protocol_violation(message: str, frame_type: Optional[int] = None) -> ProtocolError:
    """Create a protocol violation error."""
    return ProtocolError(message, frame_type=frame_type, error_code=ErrorCodes.PROTOCOL_VIOLATION)


def session_not_ready(session_id: str, current_state: SessionState) -> SessionError:
    """Create a session not ready error."""
    return SessionError(
        f"Session {session_id} not ready, current state: {current_state.value}",
        session_id=session_id,
        session_state=current_state,
    )


def stream_closed(stream_id: int, reason: str = "Stream was closed") -> StreamError:
    """Create a stream closed error."""
    return StreamError(
        f"Stream {stream_id} closed: {reason}", stream_id=stream_id, error_code=ErrorCodes.STREAM_STATE_ERROR
    )


def is_fatal_error(exception: Exception) -> bool:
    """Check if an error is fatal and should terminate the connection."""
    if isinstance(exception, WebTransportError):
        fatal_codes = {
            ErrorCodes.PROTOCOL_VIOLATION,
            ErrorCodes.FRAME_ENCODING_ERROR,
            ErrorCodes.CRYPTO_BUFFER_EXCEEDED,
            ErrorCodes.APP_AUTHENTICATION_FAILED,
            ErrorCodes.APP_PERMISSION_DENIED,
        }
        return exception.error_code in fatal_codes
    return True


def is_retriable_error(exception: Exception) -> bool:
    """Check if an error is transient and the operation can be retried."""
    if isinstance(exception, WebTransportError):
        retriable_codes = {
            ErrorCodes.APP_CONNECTION_TIMEOUT,
            ErrorCodes.APP_SERVICE_UNAVAILABLE,
            ErrorCodes.FLOW_CONTROL_ERROR,
        }
        return exception.error_code in retriable_codes
    return False


_ERROR_CATEGORY_MAP: Dict[Type[Exception], str] = {
    AuthenticationError: "authentication",
    CertificateError: "certificate",
    ClientError: "client",
    ConfigurationError: "configuration",
    ConnectionError: "connection",
    DatagramError: "datagram",
    FlowControlError: "flow_control",
    HandshakeError: "handshake",
    ProtocolError: "protocol",
    ServerError: "server",
    SessionError: "session",
    StreamError: "stream",
    TimeoutError: "timeout",
}


def get_error_category(exception: Exception) -> str:
    """Get a simple string category for an exception for logging or monitoring."""
    for exc_type, category in _ERROR_CATEGORY_MAP.items():
        if isinstance(exception, exc_type):
            return category
    return "unknown"
