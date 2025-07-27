# API Reference: Utilities

This document provides a comprehensive reference for the `pywebtransport.utils` module, which contains helper functions for logging, networking, security, data processing, and asynchronous operations.

---

## Logging Utilities

- **`setup_logging(*, level: str = "INFO", format_string: Optional[str] = None, logger_name: str = "pywebtransport") -> logging.Logger`**

  Sets up the root logger for the library. It is idempotent.

- **`get_logger(name: str) -> logging.Logger`**

  Retrieves a logger instance with a name prefixed by `pywebtransport.`.

---

## ID Generation Utilities

- **`generate_connection_id() -> str`**
- **`generate_request_id() -> str`**
- **`generate_session_id() -> str`**

  Generate unique, URL-safe, cryptographically secure identifiers for connections, requests, and sessions.

---

## Timing & Performance Utilities

### `Timer` Class

A context manager for measuring execution time.

- **`__init__(self, name: str = "timer")`**: Initializes the timer.
- **`start(self) -> None`**: Starts the timer.
- **`stop(self) -> float`**: Stops the timer and returns the elapsed time in seconds.
- **`elapsed` (property)**: Returns the currently elapsed time without stopping the timer.
- **Usage (Context Manager)**: `with Timer("My Operation") as t:`

### Time Formatting

- **`get_timestamp() -> float`**: Returns the current Unix timestamp.
- **`format_timestamp(timestamp: float) -> str`**: Formats a Unix timestamp into an ISO 8601 string.
- **`format_duration(seconds: float) -> str`**: Formats a duration in seconds into a human-readable string (e.g., `500.1ms`, `1m2.3s`).

---

## Network Utilities

- **`parse_webtransport_url(url: URL) -> URLParts`**:
  Parses a WebTransport URL string into a `(hostname, port, path)` tuple. Raises `ConfigurationError` for invalid URLs.

- **`build_webtransport_url(host: str, port: int, *, path: str = "/", secure: bool = True, query_params: Optional[Dict[str, str]] = None) -> URL`**:
  Constructs a WebTransport URL from its components.

- **`resolve_address(host: str, port: int, *, family: int = socket.AF_UNSPEC) -> Address`**:
  Asynchronously resolves a hostname to an `(ip_address, port)` tuple. Raises `ConfigurationError` on failure.

- **`is_ipv4_address(host: str) -> bool`**: Checks if a string is a valid IPv4 address.
- **`is_ipv6_address(host: str) -> bool`**: Checks if a string is a valid IPv6 address.

---

## Security & Certificate Utilities

- **`generate_self_signed_cert(hostname: str, *, output_dir: str = ".", key_size: int = 2048, days_valid: int = 365) -> Tuple[str, str]`**:
  Generates a self-signed certificate and private key, returning paths to the created `.crt` and `.key` files. Useful for testing.

- **`load_certificate(certfile: str, keyfile: str) -> ssl.SSLContext`**:
  Loads a certificate and key into a server-side `SSLContext`. Raises `CertificateError` on failure.

- **`calculate_checksum(data: bytes, *, algorithm: str = "sha256") -> str`**:
  Calculates the hex digest of data using a specified hash algorithm (e.g., "sha256", "md5").

---

## Data Processing & Formatting Utilities

- **`ensure_bytes(data: Data, *, encoding: str = "utf-8") -> bytes`**:
  Ensures the given data (str or bytes-like) is returned as `bytes`.

- **`ensure_str(data: Data, *, encoding: str = "utf-8") -> str`**:
  Ensures the given data (str or bytes-like) is returned as `str`.

- **`normalize_headers(headers: Dict[str, Any]) -> Dict[str, str]`**:
  Normalizes a dictionary of HTTP headers by lowercasing keys and converting values to strings.

- **`chunked_read(data: bytes, *, chunk_size: int = 8192) -> List[bytes]`**:
  Splits a bytes object into a list of smaller chunks.

- **`format_bytes(data: bytes, *, max_length: int = 100) -> str`**:
  Formats a bytes object for readable debug output, truncating if it exceeds `max_length`.

---

## Asynchronous Task Utilities

- **`create_task_with_timeout(coro: Coroutine, *, timeout: Optional[Timeout] = None, name: Optional[str] = None) -> asyncio.Task`**:
  Creates an `asyncio.Task` that will be cancelled if it does not complete within the specified `timeout`.

- **`run_with_timeout(coro: Coroutine, *, timeout: float, default_value: Optional[T] = None) -> Optional[T]`**:
  Runs a coroutine with a timeout. Returns the coroutine's result or `default_value` if it times out.

- **`wait_for_condition(condition: Callable[[], bool], *, timeout: Optional[Timeout] = None, interval: float = 0.1) -> None`**:
  Asynchronously waits until `condition()` returns `True`, polling at a specified `interval`. Raises `TimeoutError` if the timeout is exceeded.

---

## Validation Utilities

These functions validate inputs and raise `TypeError` or `ValueError` upon failure.

- **`validate_address(address: Any) -> None`**: Validates that an object is a `(host, port)` tuple.
- **`validate_error_code(error_code: Any) -> None`**: Validates that an error code is an integer within the valid protocol range.
- **`validate_port(port: Any) -> None`**: Validates that a port is an integer between 1 and 65535.
- **`validate_session_id(session_id: Any) -> None`**: Validates that a session ID is a non-empty string.
- **`validate_stream_id(stream_id: Any) -> None`**: Validates that a stream ID is an integer within the valid protocol range.
- **`validate_url(url: URL) -> bool`**: A simple boolean check for URL validity, wrapping `parse_webtransport_url`.

---

## Configuration Utilities

- **`merge_configs(base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]`**:
  Recursively merges two dictionaries, with values from `override_config` taking precedence.

---

## See Also

- [**Protocol API**](protocol.md): Protocol implementation details.
- [**Types API**](types.md): Review type definitions and enumerations.
- [**Exceptions API**](exceptions.md): Understand the library's error and exception hierarchy.
- [**Constants API**](constants.md): Review default values and protocol-level constants.
