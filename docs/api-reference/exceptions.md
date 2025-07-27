# API Reference: Exceptions

This document provides a comprehensive reference for the exception system in `pywebtransport`. It covers the exception hierarchy, details of each exception class, and the utility functions provided for robust error handling.

---

## Exception Hierarchy

All exceptions in the library inherit from the base `WebTransportError` class. This hierarchical structure allows for precise and flexible error handling.

```
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

### `WebTransportError`

The base class for all library-specific exceptions.

- **Constructor**: `WebTransportError(message: str, *, error_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None)`
- **Attributes**:
  - `message` (str): A human-readable description of the error.
  - `error_code` (int): A numeric error code, defaulting to `ErrorCodes.INTERNAL_ERROR`.
  - `details` (Dict[str, Any]): A dictionary for additional context.
- **Methods**:
  - `to_dict() -> Dict[str, Any]`: Serializes the exception's data to a dictionary.

---

## Exception Classes

### `AuthenticationError`

Raised for errors during the authentication process.

- **Inherits from**: `WebTransportError`
- **Constructor**: `AuthenticationError(message: str, *, error_code: Optional[int] = None, auth_method: Optional[str] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `auth_method` (Optional[str]): The authentication method that failed.

### `CertificateError`

Raised for errors related to TLS certificate loading or validation.

- **Inherits from**: `WebTransportError`
- **Constructor**: `CertificateError(message: str, *, error_code: Optional[int] = None, certificate_path: Optional[str] = None, certificate_error: Optional[str] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `certificate_path` (Optional[str]): The file path of the problematic certificate.
  - `certificate_error` (Optional[str]): A string identifying the specific certificate issue (e.g., "file_not_found").

### `ClientError`

Raised for errors specific to client-side operations.

- **Inherits from**: `WebTransportError`
- **Constructor**: `ClientError(message: str, *, error_code: Optional[int] = None, target_url: Optional[str] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `target_url` (Optional[str]): The URL the client was attempting to connect to.

### `ConfigurationError`

Raised when invalid configuration parameters are provided.

- **Inherits from**: `WebTransportError`
- **Constructor**: `ConfigurationError(message: str, *, error_code: Optional[int] = None, config_key: Optional[str] = None, config_value: Optional[Any] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `config_key` (Optional[str]): The configuration key that caused the error.
  - `config_value` (Optional[Any]): The invalid value provided for the key.

### `ConnectionError`

Raised for errors during connection establishment or management.

- **Inherits from**: `WebTransportError`
- **Constructor**: `ConnectionError(message: str, *, error_code: Optional[int] = None, remote_address: Optional[Tuple[str, int]] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `remote_address` (Optional[Tuple[str, int]]): The `(host, port)` tuple of the remote peer.

### `DatagramError`

Raised for errors related to sending or receiving datagrams.

- **Inherits from**: `WebTransportError`
- **Constructor**: `DatagramError(message: str, *, error_code: Optional[int] = None, datagram_size: Optional[int] = None, max_size: Optional[int] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `datagram_size` (Optional[int]): The size of the datagram that caused the error.
  - `max_size` (Optional[int]): The maximum permissible datagram size.

### `FlowControlError`

Raised when a flow control limit is violated.

- **Inherits from**: `WebTransportError`
- **Constructor**: `FlowControlError(message: str, *, error_code: Optional[int] = None, stream_id: Optional[int] = None, limit_exceeded: Optional[int] = None, current_value: Optional[int] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `stream_id` (Optional[int]): The ID of the stream where the error occurred.
  - `limit_exceeded` (Optional[int]): The flow control limit that was surpassed.
  - `current_value` (Optional[int]): The value that exceeded the limit.

### `HandshakeError`

Raised for errors during the WebTransport handshake process.

- **Inherits from**: `WebTransportError`
- **Constructor**: `HandshakeError(message: str, *, error_code: Optional[int] = None, handshake_stage: Optional[str] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `handshake_stage` (Optional[str]): The stage of the handshake where the failure occurred.

### `ProtocolError`

Raised for violations of the WebTransport or underlying QUIC protocols.

- **Inherits from**: `WebTransportError`
- **Constructor**: `ProtocolError(message: str, *, error_code: Optional[int] = None, frame_type: Optional[int] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `frame_type` (Optional[int]): The QUIC frame type that caused the error, if applicable.

### `ServerError`

Raised for errors specific to server-side operations.

- **Inherits from**: `WebTransportError`
- **Constructor**: `ServerError(message: str, *, error_code: Optional[int] = None, bind_address: Optional[Tuple[str, int]] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `bind_address` (Optional[Tuple[str, int]]): The address the server failed to bind to.

### `SessionError`

Raised for errors related to WebTransport session state or management.

- **Inherits from**: `WebTransportError`
- **Constructor**: `SessionError(message: str, *, session_id: Optional[str] = None, error_code: Optional[int] = None, session_state: Optional[SessionState] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `session_id` (Optional[str]): The ID of the affected session.
  - `session_state` (Optional[SessionState]): The state of the session when the error occurred.

### `StreamError`

Raised for errors related to stream operations or state.

- **Inherits from**: `WebTransportError`
- **Constructor**: `StreamError(message: str, *, stream_id: Optional[int] = None, error_code: Optional[int] = None, stream_state: Optional[StreamState] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `stream_id` (Optional[int]): The ID of the affected stream.
  - `stream_state` (Optional[StreamState]): The state of the stream when the error occurred.

### `TimeoutError`

Raised when an operation exceeds its specified timeout.

- **Inherits from**: `WebTransportError`
- **Constructor**: `TimeoutError(message: str, *, error_code: Optional[int] = None, timeout_duration: Optional[float] = None, operation: Optional[str] = None, details: Optional[Dict[str, Any]] = None)`
- **Additional Attributes**:
  - `timeout_duration` (Optional[float]): The timeout value in seconds.
  - `operation` (Optional[str]): A description of the operation that timed out.

---

## Exception Factory Functions

These helper functions create specific, pre-configured exception instances.

- **`certificate_not_found(path: str) -> CertificateError`**
  Creates a `CertificateError` for a missing certificate file.

- **`connection_timeout(timeout_duration: float, operation: str = "connect") -> TimeoutError`**
  Creates a `TimeoutError` for a connection timeout.

- **`datagram_too_large(size: int, max_size: int) -> DatagramError`**
  Creates a `DatagramError` for an oversized datagram.

- **`invalid_config(key: str, value: Any, reason: str) -> ConfigurationError`**
  Creates a `ConfigurationError` for an invalid configuration parameter.

- **`protocol_violation(message: str, frame_type: Optional[int] = None) -> ProtocolError`**
  Creates a `ProtocolError` for a protocol violation.

- **`session_not_ready(session_id: str, current_state: SessionState) -> SessionError`**
  Creates a `SessionError` for operations on a session that is not yet in the `CONNECTED` state.

- **`stream_closed(stream_id: int, reason: str = "Stream was closed") -> StreamError`**
  Creates a `StreamError` for operations on a closed stream.

---

## Error Handling Utilities

These functions assist in classifying and handling exceptions.

- **`is_fatal_error(exception: Exception) -> bool`**
  Returns `True` if the error is considered fatal and should terminate the connection. This typically applies to severe protocol violations.

- **`is_retriable_error(exception: Exception) -> bool`**
  Returns `True` if the error is transient (e.g., timeout, flow control) and the operation may succeed if retried.

- **`get_error_category(exception: Exception) -> str`**
  Returns a simple string category for the exception (e.g., `"connection"`, `"stream"`, `"timeout"`), useful for logging and metrics.

---

## See Also

- [**Protocol API**](protocol.md): Protocol implementation details.
- [**Events API**](events.md): Learn about the event system and how to use handlers.
- [**Types API**](types.md): Review type definitions, enumerations, and constants.
- [**Constants API**](constants.md): Review default values and protocol-level constants.
