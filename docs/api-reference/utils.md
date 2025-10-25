# API Reference: utils

This module provides shared, general-purpose utilities.

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

- **`def create_quic_configuration(*, is_client: bool, alpn_protocols: list[str], congestion_control_algorithm: str, max_datagram_size: int) -> QuicConfiguration`**: Creates a QUIC configuration from specific, required parameters.
- **`def ensure_bytes(*, data: Buffer | str, encoding: str = "utf-8") -> bytes`**: Ensures the given data is returned as `bytes`.
- **`def format_duration(*, seconds: float) -> str`**: Formats a duration in seconds into a human-readable string.
- **`def generate_self_signed_cert(*, hostname: str, output_dir: str = ".", key_size: int = 2048, days_valid: int = 365) -> tuple[str, str]`**: Generates a self-signed certificate and private key for testing purposes.
- **`def generate_session_id() -> str`**: Generates a unique, URL-safe session ID.
- **`def get_logger(*, name: str) -> logging.Logger`**: Retrieves a logger instance with a specific name.
- **`def get_timestamp() -> float`**: Returns the current Unix timestamp.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
