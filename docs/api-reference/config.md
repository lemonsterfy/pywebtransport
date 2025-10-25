# API Reference: config

This module provides the configuration classes for the client and server.

---

## ProxyConfig Class

A dataclass that holds all configuration options for an HTTP proxy.

### Constructor

The constructor accepts the following keyword-only arguments:

- `url` (`str`): The complete URL of the proxy server.
- `headers` (`Headers`): A dictionary of additional headers to send to the proxy. `Default: {}`.
- `connect_timeout` (`float`): Timeout in seconds for establishing a connection with the proxy. `Default: 10.0`.

## ClientConfig Class

A dataclass that holds all configuration options for a WebTransport client.

**Note on Usage**: The constructor requires all parameters to be passed as keyword arguments.

### Constructor

The constructor accepts the following keyword-only arguments:

- `alpn_protocols` (`list[str]`): List of protocols for ALPN negotiation. `Default: ['h3']`.
- `auto_reconnect` (`bool`): Enable or disable automatic reconnection on unexpected disconnections. `Default: False`.
- `ca_certs` (`str | None`): Path to a file of concatenated CA certificates. `Default: None`.
- `certfile` (`str | None`): Path to the client's certificate file (for mTLS). `Default: None`.
- `close_timeout` (`float`): Timeout for closing the connection. `Default: 5.0`.
- `congestion_control_algorithm` (`str`): The congestion control algorithm. `Default: "cubic"`.
- `connect_timeout` (`float`): Timeout for establishing a connection. `Default: 30.0`.
- `connection_cleanup_interval` (`float`): Interval for cleaning up closed connections. `Default: 30.0`.
- `connection_idle_check_interval` (`float`): Interval for checking for idle connections. `Default: 5.0`.
- `connection_idle_timeout` (`float`): Time in seconds after which an idle connection is closed. `Default: 60.0`.
- `connection_keepalive_timeout` (`float`): Interval for sending keep-alive packets. `Default: 30.0`.
- `debug` (`bool`): Enable debug mode. `Default: False`.
- `flow_control_window_auto_scale` (`bool`): Enable automatic scaling of the flow control window. `Default: True`.
- `flow_control_window_size` (`int`): The initial size of the flow control window in bytes. `Default: 1048576`.
- `headers` (`Headers`): A dictionary of additional headers to send. `Default: {}`.
- `initial_max_data` (`int`): Initial session-level data limit advertised to the peer. `Default: 0`.
- `initial_max_streams_bidi` (`int`): Initial number of bidirectional streams the peer can open. `Default: 0`.
- `initial_max_streams_uni` (`int`): Initial number of unidirectional streams the peer can open. `Default: 0`.
- `keep_alive` (`bool`): Enable the connection keep-alive mechanism. `Default: True`.
- `keyfile` (`str | None`): Path to the client's private key file (for mTLS). `Default: None`.
- `log_level` (`str`): Logging level. `Default: "INFO"`.
- `max_connections` (`int`): Maximum number of concurrent connections for the client. `Default: 100`.
- `max_datagram_size` (`int`): Maximum size for a datagram payload. `Default: 65535`.
- `max_incoming_streams` (`int`): Maximum number of concurrent server-initiated streams. `Default: 100`.
- `max_pending_events_per_session` (`int`): Max events to buffer for a session before it's established. `Default: 16`.
- `max_retries` (`int`): Maximum number of connection retries. `Default: 3`.
- `max_retry_delay` (`float`): Maximum delay between retries. `Default: 30.0`.
- `max_stream_buffer_size` (`int`): Maximum buffer size for streams. `Default: 1048576`.
- `max_streams` (`int`): Maximum number of concurrent client-initiated streams. `Default: 100`.
- `max_total_pending_events` (`int`): Global limit for buffered events across all pending sessions. `Default: 1000`.
- `pending_event_ttl` (`float`): Time-to-live in seconds for a buffered event. `Default: 5.0`.
- `proxy` (`ProxyConfig | None`): Configuration for connecting through an HTTP proxy. `Default: None`.
- `read_timeout` (`float | None`): Timeout for read operations. `Default: 60.0`.
- `retry_backoff` (`float`): Multiplier for increasing retry delay. `Default: 2.0`.
- `retry_delay` (`float`): Initial delay between retries in seconds. `Default: 1.0`.
- `rpc_concurrency_limit` (`int`): Maximum number of concurrent RPC calls. `Default: 100`.
- `stream_buffer_size` (`int`): Default buffer size for streams in bytes. `Default: 65536`.
- `stream_cleanup_interval` (`float`): Interval for cleaning up closed streams. `Default: 15.0`.
- `stream_creation_timeout` (`float`): Timeout for creating a new stream. `Default: 10.0`.
- `stream_flow_control_increment_bidi` (`int`): Number of bidirectional streams to grant when the limit is reached. `Default: 10`.
- `stream_flow_control_increment_uni` (`int`): Number of unidirectional streams to grant when the limit is reached. `Default: 10`.
- `user_agent` (`str`): The User-Agent header string. `Default: "pywebtransport/<version>"`.
- `verify_mode` (`ssl.VerifyMode | None`): SSL verification mode. `Default: ssl.CERT_REQUIRED`.
- `write_timeout` (`float | None`): Timeout for write operations. `Default: 30.0`.

### Class Methods

- **`def create_for_development(cls, *, verify_ssl: bool = False) -> Self`**: Creates a config optimized for development with relaxed security.
- **`def create_for_production(cls, *, ca_certs: str | None = None, certfile: str | None = None, keyfile: str | None = None) -> Self`**: Creates a config optimized for production with stricter security.
- **`def from_dict(cls, *, config_dict: dict[str, Any]) -> Self`**: Creates a `ClientConfig` instance from a dictionary.

### Instance Methods

- **`def copy(self) -> Self`**: Returns a deep copy of the configuration instance.
- **`def to_dict(self) -> dict[str, Any]`**: Converts the configuration to a dictionary.
- **`def update(self, **kwargs: Any) -> Self`**: Returns a new `ClientConfig` instance with updated values.
- **`def validate(self) -> None`**: Validates configuration values, raising `ConfigurationError` on failure.

## ServerConfig Class

A dataclass that holds all configuration options for a WebTransport server.

**Note on Usage**: The constructor requires all parameters to be passed as keyword arguments.

### Constructor

The constructor accepts the following keyword-only arguments:

- `access_log` (`bool`): Enable or disable access logging. `Default: True`.
- `alpn_protocols` (`list[str]`): List of protocols for ALPN negotiation. `Default: ['h3']`.
- `bind_host` (`str`): The host address to bind to. `Default: "localhost"`.
- `bind_port` (`int`): The port to bind to. `Default: 4433`.
- `ca_certs` (`str | None`): Path to CA certificates for client validation (mTLS). `Default: None`.
- `certfile` (`str`): Path to the server's certificate file. `Default: ""`.
- `congestion_control_algorithm` (`str`): The congestion control algorithm. `Default: "cubic"`.
- `connection_cleanup_interval` (`float`): Interval for cleaning up closed connections. `Default: 30.0`.
- `connection_idle_check_interval` (`float`): Interval for checking for idle connections. `Default: 5.0`.
- `connection_idle_timeout` (`float`): Time in seconds after which an idle connection is closed. `Default: 60.0`.
- `connection_keepalive_timeout` (`float`): Interval for sending keep-alive packets. `Default: 30.0`.
- `debug` (`bool`): Enable debug mode. `Default: False`.
- `flow_control_window_auto_scale` (`bool`): Enable automatic scaling of the flow control window. `Default: True`.
- `flow_control_window_size` (`int`): The initial size of the flow control window in bytes. `Default: 1048576`.
- `initial_max_data` (`int`): Initial session-level data limit advertised to clients. `Default: 0`.
- `initial_max_streams_bidi` (`int`): Initial number of bidirectional streams a client can open. `Default: 0`.
- `initial_max_streams_uni` (`int`): Initial number of unidirectional streams a client can open. `Default: 0`.
- `keep_alive` (`bool`): Whether to enable TCP keep-alive. `Default: True`.
- `keyfile` (`str`): Path to the server's private key file. `Default: ""`.
- `log_level` (`str`): Logging level. `Default: "INFO"`.
- `max_connections` (`int`): Maximum number of concurrent connections. `Default: 3000`.
- `max_datagram_size` (`int`): Maximum size for a datagram payload. `Default: 65535`.
- `max_incoming_streams` (`int`): Maximum number of concurrent client-initiated streams. `Default: 100`.
- `max_pending_events_per_session` (`int`): Max events to buffer for a session before it's established. `Default: 16`.
- `max_sessions` (`int`): Maximum number of concurrent WebTransport sessions. `Default: 10000`.
- `max_stream_buffer_size` (`int`): Maximum buffer size for streams. `Default: 1048576`.
- `max_streams_per_connection` (`int`): Maximum streams per connection. `Default: 100`.
- `max_total_pending_events` (`int`): Global limit for buffered events across all pending sessions. `Default: 1000`.
- `middleware` (`list[MiddlewareProtocol]`): A list of middleware to apply to sessions. `Default: []`.
- `pending_event_ttl` (`float`): Time-to-live in seconds for a buffered event. `Default: 5.0`.
- `read_timeout` (`float | None`): Timeout for read operations. `Default: 60.0`.
- `rpc_concurrency_limit` (`int`): Maximum number of concurrent RPC calls per session. `Default: 100`.
- `session_cleanup_interval` (`float`): Interval for cleaning up closed sessions. `Default: 60.0`.
- `stream_buffer_size` (`int`): Default buffer size for streams in bytes. `Default: 65536`.
- `stream_cleanup_interval` (`float`): Interval for cleaning up closed streams. `Default: 15.0`.
- `stream_flow_control_increment_bidi` (`int`): Number of bidirectional streams to grant when the limit is reached. `Default: 10`.
- `stream_flow_control_increment_uni` (`int`): Number of unidirectional streams to grant when the limit is reached. `Default: 10`.
- `verify_mode` (`ssl.VerifyMode`): SSL verification mode for client certificates. `Default: ssl.CERT_OPTIONAL`.
- `write_timeout` (`float | None`): Timeout for write operations. `Default: 30.0`.

### Class Methods

- **`def create_for_development(cls, *, host: str = "localhost", port: int = 4433, certfile: str | None = None, keyfile: str | None = None) -> Self`**: Creates a config for local development.
- **`def create_for_production(cls, *, host: str, port: int, certfile: str, keyfile: str, ca_certs: str | None = None) -> Self`**: Creates a config for production use.
- **`def from_dict(cls, *, config_dict: dict[str, Any]) -> Self`**: Creates a `ServerConfig` instance from a dictionary.

### Instance Methods

- **`def copy(self) -> Self`**: Returns a deep copy of the configuration instance.
- **`def to_dict(self) -> dict[str, Any]`**: Converts the configuration to a dictionary.
- **`def update(self, **kwargs: Any) -> Self`**: Returns a new `ServerConfig` instance with updated values.
- **`def validate(self) -> None`**: Validates configuration values, raising `ConfigurationError` on failure.

## See Also

- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Client API](client.md)**: Learn how to use the WebTransport client.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Types API](types.md)**: Review type definitions and enumerations.
