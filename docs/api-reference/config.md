# API Reference: Configuration

This document provides a comprehensive reference for the `pywebtransport.config` module, which contains the configuration classes for the client and server.

---

## `ClientConfig` Class

A dataclass that holds all configuration options for a WebTransport client.

### Attributes

#### Timeouts

- `connect_timeout` (float): Timeout for establishing a connection. Default: `30.0`.
- `read_timeout` (Optional[float]): Timeout for read operations. Default: `60.0`.
- `write_timeout` (Optional[float]): Timeout for write operations. Default: `30.0`.
- `close_timeout` (float): Timeout for closing the connection. Default: `5.0`.
- `stream_creation_timeout` (float): Timeout for creating a new stream. Default: `10.0`.

#### Limits & Buffers

- `max_streams` (int): Maximum number of concurrent streams. Default: `100`.
- `stream_buffer_size` (int): Default buffer size for streams in bytes. Default: `65536`.
- `max_stream_buffer_size` (int): Maximum buffer size for streams. Default: `1048576`.
- `max_datagram_size` (int): Maximum size for a datagram payload. Default: `65535`.

#### Security (SSL/TLS)

- `verify_mode` (Optional[ssl.VerifyMode]): SSL verification mode. Default: `ssl.CERT_REQUIRED`.
- `ca_certs` (Optional[str]): Path to a file of concatenated CA certificates.
- `certfile` (Optional[str]): Path to the client's certificate file (for mTLS).
- `keyfile` (Optional[str]): Path to the client's private key file (for mTLS).
- `check_hostname` (bool): Whether to check if the server's hostname matches its certificate. Default: `True`.

#### Protocol & Headers

- `alpn_protocols` (List[str]): List of protocols for ALPN negotiation.
- `http_version` (str): The HTTP version to use. Default: `"3"`.
- `user_agent` (str): The User-Agent header string.
- `headers` (Headers): A dictionary of additional headers to send.

#### Retry Logic

- `max_retries` (int): Maximum number of connection retries. Default: `3`.
- `retry_delay` (float): Initial delay between retries in seconds. Default: `1.0`.
- `retry_backoff` (float): Multiplier for increasing retry delay. Default: `2.0`.
- `max_retry_delay` (float): Maximum delay between retries. Default: `30.0`.

#### Flow Control

- `initial_max_data` (int): Initial connection-level flow control window. Default: `1048576`.
- `initial_max_stream_data_bidi_local` (int): Initial flow control window for locally-initiated bidirectional streams. Default: `262144`.
- `initial_max_stream_data_bidi_remote` (int): Initial flow control window for remotely-initiated bidirectional streams. Default: `262144`.
- `initial_max_stream_data_uni` (int): Initial flow control window for unidirectional streams. Default: `262144`.
- `initial_max_streams_bidi` (int): Maximum number of concurrent bidirectional streams. Default: `100`.
- `initial_max_streams_uni` (int): Maximum number of concurrent unidirectional streams. Default: `3`.

#### Debugging

- `debug` (bool): Enable debug mode. Default: `False`.
- `log_level` (str): Logging level. Default: `"INFO"`.

### Class Methods

- `create(**kwargs: Any) -> ClientConfig`: Creates a `ClientConfig` instance, applying keyword arguments over the defaults.
- `create_for_development(*, verify_ssl: bool = False) -> ClientConfig`: Creates a config optimized for development with relaxed security and verbose logging.
- `create_for_production(*, ca_certs: Optional[str] = None, ...) -> ClientConfig`: Creates a config optimized for production with stricter security and performance settings.
- `from_dict(config_dict: Dict[str, Any]) -> ClientConfig`: Creates a `ClientConfig` instance from a dictionary, ignoring unknown keys.

### Instance Methods

- `validate() -> None`: Validates the configuration values, raising `ConfigurationError` on failure.
- `copy() -> ClientConfig`: Returns a deep copy of the configuration instance.
- `update(**kwargs: Any) -> ClientConfig`: Returns a new `ClientConfig` instance with updated values.
- `merge(other: Union[ClientConfig, Dict[str, Any]]) -> ClientConfig`: Merges the current config with another, returning a new instance.
- `to_dict() -> Dict[str, Any]`: Converts the configuration to a dictionary.

---

## `ServerConfig` Class

A dataclass that holds all configuration options for a WebTransport server.

### Attributes

#### Binding

- `bind_host` (str): The host address to bind to. Default: `"localhost"`.
- `bind_port` (int): The port to bind to. Default: `4433`.

#### Limits & Timeouts

- `max_connections` (int): Maximum number of concurrent connections. Default: `1000`.
- `max_streams_per_connection` (int): Maximum streams per connection. Default: `100`.
- `connection_timeout` (float): Keep-alive timeout for connections. Default: `300.0`.
- (Inherits `read_timeout`, `write_timeout`, buffer sizes, and flow control settings from `ClientConfig` defaults).

#### Security (SSL/TLS)

- `certfile` (str): Path to the server's certificate file. **Required for TLS**.
- `keyfile` (str): Path to the server's private key file. **Required for TLS**.
- `ca_certs` (Optional[str]): Path to CA certificates for client certificate validation (mTLS).
- `verify_mode` (ssl.VerifyMode): SSL verification mode for client certificates. Default: `ssl.CERT_NONE`.

#### Performance

- `backlog` (int): Socket listen backlog. Default: `128`.
- `reuse_port` (bool): Whether to enable the `SO_REUSEPORT` socket option. Default: `True`.
- `keep_alive` (bool): Whether to enable TCP keep-alive. Default: `True`.

#### Advanced

- `middleware` (List[Any]): A list of middleware to apply to sessions. Default: `[]`.
- `access_log` (bool): Enable or disable access logging. Default: `True`.
- (Inherits `alpn_protocols`, `http_version`, `debug`, and `log_level` from `ClientConfig` defaults).

### Class Methods

- `create(**kwargs: Any) -> ServerConfig`: Creates a `ServerConfig` instance, applying keyword arguments over the defaults.
- `create_for_development(*, host: str = ..., port: int = ..., ...) -> ServerConfig`: Creates a config for local development.
- `create_for_production(*, host: str, port: int, certfile: str, keyfile: str, ...) -> ServerConfig`: Creates a config for production use, requiring paths for the certificate and key.
- `from_dict(config_dict: Dict[str, Any]) -> ServerConfig`: Creates a `ServerConfig` instance from a dictionary.

### Instance Methods

- `get_bind_address() -> Address`: Returns the bind address as a `(host, port)` tuple.
- (Inherits `validate`, `copy`, `update`, `merge`, and `to_dict` methods from `ClientConfig`).

---

## `ConfigBuilder` Class

A fluent builder for creating `ClientConfig` or `ServerConfig` instances using method chaining.

- **Constructor**: `ConfigBuilder(config_type: str = "client")`
  - `config_type` can be `"client"` or `"server"`.

### Chaining Methods

- `bind(host: str, port: int) -> ConfigBuilder`: Sets bind address (server only).
- `debug(*, enabled: bool = True, ...) -> ConfigBuilder`: Sets debug settings.
- `performance(*, max_streams: int = ..., ...) -> ConfigBuilder`: Sets performance settings.
- `security(*, certfile: str = ..., ...) -> ConfigBuilder`: Sets security settings.
- `timeout(*, connect: float = ..., ...) -> ConfigBuilder`: Sets timeout settings.

### Finalizer Method

- `build() -> Union[ClientConfig, ServerConfig]`: Constructs and returns the final configuration object.

#### Example

```python
from pywebtransport.config import ConfigBuilder

# Build a client config
client_config = (
    ConfigBuilder("client")
    .timeout(connect=10.0)
    .performance(max_streams=50)
    .build()
)

# Build a server config
server_config = (
    ConfigBuilder("server")
    .bind("0.0.0.0", 8443)
    .security(certfile="cert.pem", keyfile="key.pem")
    .build()
)
```

---

## See Also

- [**Protocol API**](protocol.md): Protocol implementation details.
- [**Types API**](types.md): Review type definitions and enumerations.
- [**Exceptions API**](exceptions.md): Understand the library's error and exception hierarchy.
- [**Constants API**](constants.md): Review default values and protocol-level constants.
