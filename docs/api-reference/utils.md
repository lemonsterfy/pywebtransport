# API Reference: utils

This document provides a reference for helper functions for logging, networking, security, data processing, and asynchronous operations.

---

## Timer Class

A context manager for measuring execution time.

### Constructor

- **`def __init__(self, *, name: str = "timer") -> None`**: Initializes the timer.

### Properties

- `elapsed` (`float`): Returns the currently elapsed time without stopping the timer.

### Instance Methods

- **`def start(self) -> None`**: Starts the timer.
- **`def stop(self) -> float`**: Stops the timer and returns the elapsed time in seconds.

## Module-Level Functions

### Logging Utilities

- **`def get_logger(*, name: str) -> logging.Logger`**: Retrieves a logger instance with a name prefixed by `pywebtransport.`.
- **`def setup_logging(*, level: str = "INFO", format_string: str | None = None, logger_name: str = "pywebtransport") -> logging.Logger`**: Sets up the root logger for the library.

### ID Generation Utilities

- **`def generate_connection_id() -> str`**: Generates a unique, URL-safe, cryptographically secure identifier for a connection.
- **`def generate_request_id() -> str`**: Generates a unique identifier for a request.
- **`def generate_session_id() -> str`**: Generates a unique identifier for a session.

### Time Formatting Functions

- **`def format_duration(*, seconds: float) -> str`**: Formats a duration in seconds into a human-readable string.
- **`def format_timestamp(*, timestamp: float) -> str`**: Formats a Unix timestamp into an ISO 8601 string.
- **`def get_timestamp() -> float`**: Returns the current Unix timestamp.

### Network Utilities

- **`def build_webtransport_url(*, host: str, port: int, path: str = "/", secure: bool = True, query_params: dict[str, str] | None = None) -> URL`**: Constructs a WebTransport URL from its components.
- **`def is_ipv4_address(*, host: str) -> bool`**: Checks if a string is a valid IPv4 address.
- **`def is_ipv6_address(*, host: str) -> bool`**: Checks if a string is a valid IPv6 address.
- **`def parse_webtransport_url(*, url: URL) -> URLParts`**: Parses a WebTransport URL string into a `(hostname, port, path)` tuple.
- **`async def resolve_address(*, host: str, port: int, family: int = socket.AF_UNSPEC) -> Address`**: Asynchronously resolves a hostname to an `(ip_address, port)` tuple.

### Security & Certificate Utilities

- **`def calculate_checksum(*, data: bytes, algorithm: str = "sha256") -> str`**: Calculates the hex digest of data using a specified hash algorithm.
- **`def generate_self_signed_cert(*, hostname: str, output_dir: str = ".", key_size: int = 2048, days_valid: int = 365) -> tuple[str, str]`**: Generates a self-signed certificate and private key.
- **`def load_certificate(*, certfile: str, keyfile: str) -> ssl.SSLContext`**: Loads a certificate and key into a server-side `SSLContext`.

### Data Processing & Formatting Utilities

- **`def chunked_read(*, data: bytes, chunk_size: int = 8192) -> list[bytes]`**: Splits a bytes object into a list of smaller chunks.
- **`def ensure_bytes(*, data: Buffer | str, encoding: str = "utf-8") -> bytes`**: Ensures the given data is returned as `bytes`.
- **`def ensure_str(*, data: Buffer | str, encoding: str = "utf-8") -> str`**: Ensures the given data is returned as `str`.
- **`def format_bytes(*, data: bytes, max_length: int = 100) -> str`**: Formats a bytes object for readable debug output, truncating if necessary.
- **`def normalize_headers(*, headers: dict[str, Any]) -> dict[str, str]`**: Normalizes HTTP headers by lowercasing keys and converting values to strings.

### Asynchronous Task Utilities

- **`async def create_task_with_timeout(*, coro: Coroutine[Any, Any, T], timeout: Timeout | None = None, name: str | None = None) -> asyncio.Task[T]`**: Creates an `asyncio.Task` that will be cancelled if it exceeds the timeout.
- **`async def run_with_timeout(*, coro: Coroutine[Any, Any, T], timeout: float, default_value: T | None = None) -> T | None`**: Runs a coroutine with a timeout, returning a default value if it times out.
- **`async def wait_for_condition(*, condition: Callable[[], bool], timeout: Timeout | None = None, interval: float = 0.1) -> None`**: Asynchronously waits until a condition returns `True`.

### Validation Utilities

- **`def validate_address(*, address: Any) -> None`**: Validates that an object is a `(host, port)` tuple.
- **`def validate_error_code(*, error_code: Any) -> None`**: Validates that an error code is an integer within the valid protocol range.
- **`def validate_port(*, port: Any) -> None`**: Validates that a port is an integer between 1 and 65535.
- **`def validate_session_id(*, session_id: Any) -> None`**: Validates that a session ID is a non-empty string.
- **`def validate_stream_id(*, stream_id: Any) -> None`**: Validates that a stream ID is an integer within the valid protocol range.
- **`def validate_url(*, url: URL) -> bool`**: A simple boolean check for URL validity.

### Configuration Utilities

- **`def merge_configs(*, base_config: dict[str, Any], override_config: dict[str, Any]) -> dict[str, Any]`**: Recursively merges two dictionaries.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
