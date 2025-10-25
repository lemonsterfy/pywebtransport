# API Reference: exceptions

This module provides the custom exception hierarchy and error-handling utilities.

---

## WebTransportError Class

The base exception for all WebTransport errors.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the base WebTransport error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.INTERNAL_ERROR`.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

### Instance Methods

- **`def to_dict(self) -> dict[str, Any]`**: Converts the exception to a dictionary for serialization.

## AuthenticationError Class

An exception for authentication-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, auth_method: str | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the authentication error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.APP_AUTHENTICATION_FAILED`.
  - `auth_method` (`str | None`): The authentication method that failed.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## CertificateError Class

An exception for certificate-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, certificate_path: str | None = None, certificate_error: str | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the certificate error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.APP_AUTHENTICATION_FAILED`.
  - `certificate_path` (`str | None`): The file path of the problematic certificate.
  - `certificate_error` (`str | None`): A string identifying the specific certificate issue.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## ClientError Class

An exception for client-specific errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, target_url: str | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the client error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.APP_INVALID_REQUEST`.
  - `target_url` (`str | None`): The URL the client was attempting to connect to.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## ConfigurationError Class

An exception for configuration-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, config_key: str | None = None, config_value: Any | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the configuration error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.APP_INVALID_REQUEST`.
  - `config_key` (`str | None`): The configuration key that caused the error.
  - `config_value` (`Any | None`): The invalid value provided for the key.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## ConnectionError Class

An exception for connection-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, remote_address: tuple[str, int] | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the connection error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.CONNECTION_REFUSED`.
  - `remote_address` (`tuple[str, int] | None`): The `(host, port)` tuple of the remote peer.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## DatagramError Class

An exception for datagram-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, datagram_size: int | None = None, max_size: int | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the datagram error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.INTERNAL_ERROR`.
  - `datagram_size` (`int | None`): The size of the datagram that caused the error.
  - `max_size` (`int | None`): The maximum permissible datagram size.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## FlowControlError Class

An exception for flow control errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, stream_id: int | None = None, limit_exceeded: int | None = None, current_value: int | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the flow control error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.FLOW_CONTROL_ERROR`.
  - `stream_id` (`int | None`): The ID of the stream where the error occurred.
  - `limit_exceeded` (`int | None`): The flow control limit that was surpassed.
  - `current_value` (`int | None`): The value that exceeded the limit.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## HandshakeError Class

An exception for handshake-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, handshake_stage: str | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the handshake error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.INTERNAL_ERROR`.
  - `handshake_stage` (`str | None`): The stage of the handshake where the failure occurred.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## ProtocolError Class

An exception for protocol violation errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, frame_type: int | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the protocol error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.PROTOCOL_VIOLATION`.
  - `frame_type` (`int | None`): The QUIC frame type that caused the error, if applicable.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## SerializationError Class

An exception for serialization or deserialization errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, details: dict[str, Any] | None = None, original_exception: Exception | None = None) -> None`**: Initializes the serialization error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.INTERNAL_ERROR`.
  - `original_exception` (`Exception | None`): The original exception that was caught during the process.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## ServerError Class

An exception for server-specific errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, bind_address: tuple[str, int] | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the server error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.APP_SERVICE_UNAVAILABLE`.
  - `bind_address` (`tuple[str, int] | None`): The address the server failed to bind to.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## SessionError Class

An exception for WebTransport session errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, session_id: str | None = None, error_code: int | None = None, session_state: SessionState | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the session error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.INTERNAL_ERROR`.
  - `session_id` (`str | None`): The ID of the affected session.
  - `session_state` (`SessionState | None`): The state of the session when the error occurred.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## StreamError Class

An exception for stream-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, stream_id: int | None = None, error_code: int | None = None, stream_state: StreamState | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the stream error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.STREAM_STATE_ERROR`.
  - `stream_id` (`int | None`): The ID of the affected stream.
  - `stream_state` (`StreamState | None`): The state of the stream when the error occurred.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## TimeoutError Class

An exception for timeout-related errors. Inherits from `WebTransportError`.

### Constructor

- **`def __init__(self, message: str, *, error_code: int | None = None, timeout_duration: float | None = None, operation: str | None = None, details: dict[str, Any] | None = None) -> None`**: Initializes the timeout error.
  - `message` (`str`): A human-readable description of the error.
  - `error_code` (`int | None`): A numeric error code. `Default: ErrorCodes.APP_CONNECTION_TIMEOUT`.
  - `timeout_duration` (`float | None`): The timeout value in seconds.
  - `operation` (`str | None`): A description of the operation that timed out.
  - `details` (`dict[str, Any] | None`): A dictionary for additional context. `Default: None`.

## Utility Functions

Helper functions for creating and classifying exceptions.

- **`def certificate_not_found(*, path: str) -> CertificateError`**: Creates a `CertificateError` for a missing certificate file.
- **`def datagram_too_large(*, size: int, max_size: int) -> DatagramError`**: Creates a `DatagramError` for an oversized datagram.
- **`def get_error_category(*, exception: Exception) -> str`**: Returns a simple string category for the exception (e.g., "connection", "stream").
- **`def invalid_config(*, key: str, value: Any, reason: str) -> ConfigurationError`**: Creates a `ConfigurationError` for an invalid configuration parameter.
- **`def is_fatal_error(*, exception: Exception) -> bool`**: Returns `True` if the error is considered fatal and should terminate the connection.
- **`def is_retriable_error(*, exception: Exception) -> bool`**: Returns `True` if the error is transient and the operation may succeed if retried.
- **`def session_not_ready(*, session_id: str, current_state: SessionState) -> SessionError`**: Creates a `SessionError` for operations on a session that is not yet connected.
- **`def stream_closed(*, stream_id: int, reason: str = "Stream was closed") -> StreamError`**: Creates a `StreamError` for operations on a closed stream.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Types API](types.md)**: Review type definitions and enumerations.
