# API Reference: Utils

This document provides a comprehensive reference for the `pywebtransport.utils` module, which contains helper functions for logging, networking, security, data processing, and asynchronous operations.

---

## Logging Utilities

- **`setup_logging(*, level: str = "INFO", format_string: str | None = None, logger_name: str = "pywebtransport") -> logging.Logger`**: Sets up the root logger for the library. It is idempotent.
- **`get_logger(name: str) -> logging.Logger`**: Retrieves a logger instance with a name prefixed by `pywebtransport.`.

---

## ID Generation Utilities

- **`generate_connection_id() -> str`**: Generates a unique, URL-safe, cryptographically secure identifier for a connection.
- **`generate_request_id() -> str`**: Generates a unique identifier for a request.
- **`generate_session_id() -> str`**: Generates a unique identifier for a session.

---

## Timing & Performance Utilities

### Timer Class

A context manager for measuring execution time.

#### Constructor

- **`__init__(self, name: str = "timer")`**: Initializes the timer.

#### Methods

- **`start(self) -> None`**: Starts the timer.
- **`stop(self) -> float`**: Stops the timer and returns the elapsed time in seconds.

#### Properties

- `elapsed` (`float`): Returns the currently elapsed time without stopping the timer.

### Time Formatting Functions

- **`get_timestamp() -> float`**: Returns the current Unix timestamp.
- **`format_timestamp(timestamp: float) -> str`**: Formats a Unix timestamp into an ISO 8601 string.
- **`format_duration(seconds: float) -> str`**: Formats a duration in seconds into a human-readable string (e.g., `500.1ms`, `1m2.3s`).

---

## Network Utilities

- **`parse_webtransport_url(url: URL) -> URLParts`**: Parses a WebTransport URL string into a `(hostname, port, path)` tuple. The result is cached for performance.
- **`build_webtransport_url(host: str, port: int, *, path: str = "/", secure: bool = True, query_params: dict[str, str] | None = None) -> URL`**: Constructs a WebTransport URL from its components.
- **`async def resolve_address(host: str, port: int, *, family: int = socket.AF_UNSPEC) -> Address`**: Asynchronously resolves a hostname to an `(ip_address, port)` tuple.
- **`is_ipv4_address(host: str) -> bool`**: Checks if a string is a valid IPv4 address. The result is cached for performance.
- **`is_ipv6_address(host: str) -> bool`**: Checks if a string is a valid IPv6 address. The result is cached for performance.

---

## Security & Certificate Utilities

- **`generate_self_signed_cert(hostname: str, *, output_dir: str = ".", key_size: int = 2048, days_valid: int = 365) -> tuple[str, str]`**: Generates a self-signed certificate and private key, returning paths to the created files.
- **`load_certificate(certfile: str, keyfile: str) -> ssl.SSLContext`**: Loads a certificate and key into a server-side `SSLContext`.
- **`calculate_checksum(data: bytes, *, algorithm: str = "sha256") -> str`**: Calculates the hex digest of data using a specified hash algorithm.

---

## Data Processing & Formatting Utilities

- **`ensure_bytes(data: Buffer | str, *, encoding: str = "utf-8") -> bytes`**: Ensures the given data is returned as `bytes`.
- **`ensure_str(data: Buffer | str, *, encoding: str = "utf-8") -> str`**: Ensures the given data is returned as `str`.
- **`normalize_headers(headers: dict[str, Any]) -> dict[str, str]`**: Normalizes HTTP headers by lowercasing keys and converting values to strings.
- **`chunked_read(data: bytes, *, chunk_size: int = 8192) -> list[bytes]`**: Splits a bytes object into a list of smaller chunks.
- **`format_bytes(data: bytes, *, max_length: int = 100) -> str`**: Formats a bytes object for readable debug output, truncating if necessary.

---

## Asynchronous Task Utilities

- **`async def create_task_with_timeout(coro: Coroutine, *, timeout: Timeout | None = None, name: str | None = None) -> asyncio.Task`**: Creates an `asyncio.Task` that will be cancelled if it does not complete within the specified timeout.
- **`async def run_with_timeout(coro: Coroutine, *, timeout: float, default_value: T | None = None) -> T | None`**: Runs a coroutine with a timeout, returning a default value if it times out.
- **`async def wait_for_condition(condition: Callable[[], bool], *, timeout: Timeout | None = None, interval: float = 0.1) -> None`**: Asynchronously waits until a condition returns `True`.

---

## Validation Utilities

These functions validate inputs and raise `TypeError` or `ValueError` upon failure.

- **`validate_address(address: Any) -> None`**: Validates that an object is a `(host, port)` tuple.
- **`validate_error_code(error_code: Any) -> None`**: Validates that an error code is an integer within the valid protocol range.
- **`validate_port(port: Any) -> None`**: Validates that a port is an integer between 1 and 65535.
- **`validate_session_id(session_id: Any) -> None`**: Validates that a session ID is a non-empty string.
- **`validate_stream_id(stream_id: Any) -> None`**: Validates that a stream ID is an integer within the valid protocol range.
- **`validate_url(url: URL) -> bool`**: A simple boolean check for URL validity.

---

## Configuration Utilities

- **`merge_configs(base_config: dict[str, Any], override_config: dict[str, Any]) -> dict[str, Any]`**: Recursively merges two dictionaries, with values from the override config taking precedence.

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
