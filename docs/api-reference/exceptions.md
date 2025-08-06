# API Reference: Exceptions

This document provides a comprehensive reference for the exception system in `pywebtransport`. It covers the exception hierarchy, details of each exception class, and the utility functions provided for robust error handling.

---

## Exception Hierarchy

All exceptions in the library inherit from the base `WebTransportError` class. This hierarchical structure allows for precise and flexible error handling.

```python
Exception
└── WebTransportError
    ├── AuthenticationError
    ├── CertificateError
    ├── ClientError
    ├── ConfigurationError
    ├── ConnectionError
    ├── DatagramError
    ├── FlowControlError
    ├── HandshakeError
    ├── ProtocolError
    ├── ServerError
    ├── SessionError
    ├── StreamError
    └── TimeoutError
```

---

## Base Exception

### WebTransportError Exception

The base class for all library-specific exceptions.

#### Constructor

- **`WebTransportError(message: str, *, error_code: int | None = None, details: dict[str, Any] | None = None)`**: Initializes the base error.

#### Attributes

- `message` (`str`): A human-readable description of the error.
- `error_code` (`int`): A numeric error code, defaulting to `ErrorCodes.INTERNAL_ERROR`.
- `details` (`dict[str, Any]`): A dictionary for additional context.

#### Methods

- **`to_dict() -> dict[str, Any]`**: Serializes the exception's data to a dictionary.

---

## Exception Classes

### AuthenticationError Exception

Raised for errors during the authentication process. Inherits from `WebTransportError`.

#### Constructor

- **`AuthenticationError(message: str, *, error_code: int | None = None, auth_method: str | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `auth_method` (`str | None`): The authentication method that failed.

### CertificateError Exception

Raised for errors related to TLS certificate loading or validation. Inherits from `WebTransportError`.

#### Constructor

- **`CertificateError(message: str, *, error_code: int | None = None, certificate_path: str | None = None, certificate_error: str | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `certificate_path` (`str | None`): The file path of the problematic certificate.
- `certificate_error` (`str | None`): A string identifying the specific certificate issue (e.g., "file_not_found").

### ClientError Exception

Raised for errors specific to client-side operations. Inherits from `WebTransportError`.

#### Constructor

- **`ClientError(message: str, *, error_code: int | None = None, target_url: str | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `target_url` (`str | None`): The URL the client was attempting to connect to.

### ConfigurationError Exception

Raised when invalid configuration parameters are provided. Inherits from `WebTransportError`.

#### Constructor

- **`ConfigurationError(message: str, *, error_code: int | None = None, config_key: str | None = None, config_value: Any | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `config_key` (`str | None`): The configuration key that caused the error.
- `config_value` (`Any | None`): The invalid value provided for the key.

### ConnectionError Exception

Raised for errors during connection establishment or management. Inherits from `WebTransportError`.

#### Constructor

- **`ConnectionError(message: str, *, error_code: int | None = None, remote_address: tuple[str, int] | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `remote_address` (`tuple[str, int] | None`): The `(host, port)` tuple of the remote peer.

### DatagramError Exception

Raised for errors related to sending or receiving datagrams. Inherits from `WebTransportError`.

#### Constructor

- **`DatagramError(message: str, *, error_code: int | None = None, datagram_size: int | None = None, max_size: int | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `datagram_size` (`int | None`): The size of the datagram that caused the error.
- `max_size` (`int | None`): The maximum permissible datagram size.

### FlowControlError Exception

Raised when a flow control limit is violated. Inherits from `WebTransportError`.

#### Constructor

- **`FlowControlError(message: str, *, error_code: int | None = None, stream_id: int | None = None, limit_exceeded: int | None = None, current_value: int | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `stream_id` (`int | None`): The ID of the stream where the error occurred.
- `limit_exceeded` (`int | None`): The flow control limit that was surpassed.
- `current_value` (`int | None`): The value that exceeded the limit.

### HandshakeError Exception

Raised for errors during the WebTransport handshake process. Inherits from `WebTransportError`.

#### Constructor

- **`HandshakeError(message: str, *, error_code: int | None = None, handshake_stage: str | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `handshake_stage` (`str | None`): The stage of the handshake where the failure occurred.

### ProtocolError Exception

Raised for violations of the WebTransport or underlying QUIC protocols. Inherits from `WebTransportError`.

#### Constructor

- **`ProtocolError(message: str, *, error_code: int | None = None, frame_type: int | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `frame_type` (`int | None`): The QUIC frame type that caused the error, if applicable.

### ServerError Exception

Raised for errors specific to server-side operations. Inherits from `WebTransportError`.

#### Constructor

- **`ServerError(message: str, *, error_code: int | None = None, bind_address: tuple[str, int] | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `bind_address` (`tuple[str, int] | None`): The address the server failed to bind to.

### SessionError Exception

Raised for errors related to WebTransport session state or management. Inherits from `WebTransportError`.

#### Constructor

- **`SessionError(message: str, *, session_id: str | None = None, error_code: int | None = None, session_state: SessionState | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `session_id` (`str | None`): The ID of the affected session.
- `session_state` (`SessionState | None`): The state of the session when the error occurred.

### StreamError Exception

Raised for errors related to stream operations or state. Inherits from `WebTransportError`.

#### Constructor

- **`StreamError(message: str, *, stream_id: int | None = None, error_code: int | None = None, stream_state: StreamState | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `stream_id` (`int | None`): The ID of the affected stream.
- `stream_state` (`StreamState | None`): The state of the stream when the error occurred.

### TimeoutError Exception

Raised when an operation exceeds its specified timeout. Inherits from `WebTransportError`.

#### Constructor

- **`TimeoutError(message: str, *, error_code: int | None = None, timeout_duration: float | None = None, operation: str | None = None, details: dict[str, Any] | None = None)`**

#### Additional Attributes

- `timeout_duration` (`float | None`): The timeout value in seconds.
- `operation` (`str | None`): A description of the operation that timed out.

---

## Utility Functions

### Exception Factory Functions

These helper functions create specific, pre-configured exception instances.

- **`certificate_not_found(path: str) -> CertificateError`**: Creates a `CertificateError` for a missing certificate file.
- **`connection_timeout(timeout_duration: float, operation: str = "connect") -> TimeoutError`**: Creates a `TimeoutError` for a connection timeout.
- **`datagram_too_large(size: int, max_size: int) -> DatagramError`**: Creates a `DatagramError` for an oversized datagram.
- **`invalid_config(key: str, value: Any, reason: str) -> ConfigurationError`**: Creates a `ConfigurationError` for an invalid configuration parameter.
- **`protocol_violation(message: str, frame_type: int | None = None) -> ProtocolError`**: Creates a `ProtocolError` for a protocol violation.
- **`session_not_ready(session_id: str, current_state: SessionState) -> SessionError`**: Creates a `SessionError` for operations on a session that is not yet in the `CONNECTED` state.
- **`stream_closed(stream_id: int, reason: str = "Stream was closed") -> StreamError`**: Creates a `StreamError` for operations on a closed stream.

### Error Handling Utilities

These functions assist in classifying and handling exceptions.

- **`is_fatal_error(exception: Exception) -> bool`**: Returns `True` if the error is considered fatal and should terminate the connection.
- **`is_retriable_error(exception: Exception) -> bool`**: Returns `True` if the error is transient and the operation may succeed if retried.
- **`get_error_category(exception: Exception) -> str`**: Returns a simple string category for the exception (e.g., `"connection"`, `"stream"`, `"timeout"`).

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Types API](types.md)**: Review type definitions and enumerations.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
