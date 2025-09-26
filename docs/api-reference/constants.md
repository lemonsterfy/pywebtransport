# API Reference: constants

This module provides module-level constants, error codes, and default configuration utilities.

---

## Module-Level Constants

### General Web Standard Identifiers

- `ALPN_H3` (`str`): The ALPN identifier for HTTP/3. `Default: "h3"`.
- `ALPN_H3_29` (`str`): The ALPN identifier for HTTP/3 draft 29. `Default: "h3-29"`.
- `ALPN_H3_32` (`str`): The ALPN identifier for HTTP/3 draft 32. `Default: "h3-32"`.
- `ORIGIN_HEADER` (`str`): The HTTP "Origin" header field name. `Default: "origin"`.
- `SECURE_SCHEMES` (`tuple[str, str]`): URL schemes considered secure. `Default: ("https", "wss")`.
- `USER_AGENT_HEADER` (`str`): The HTTP "User-Agent" header field name. `Default: "user-agent"`.
- `WEBTRANSPORT_MIME_TYPE` (`str`): The MIME type for WebTransport session requests. `Default: "application/webtransport"`.
- `WEBTRANSPORT_SCHEMES` (`tuple[str, str]`): URL schemes used for WebTransport. `Default: ("https", "wss")`.

### Protocol-Defined Constants

- `BIDIRECTIONAL_STREAM` (`int`): The QUIC stream type identifier for bidirectional streams. `Default: 0x0`.
- `CLOSE_WEBTRANSPORT_SESSION_TYPE` (`int`): The Capsule type for closing a WebTransport session. `Default: 0x2843`.
- `DRAIN_WEBTRANSPORT_SESSION_TYPE` (`int`): The Capsule type for draining a WebTransport session. `Default: 0x78AE`.
- `DRAFT_VERSION` (`int`): The supported WebTransport draft version. `Default: 13`.
- `H3_FRAME_TYPE_DATA` (`int`): The H3 frame type for data frames. `Default: 0x0`.
- `H3_FRAME_TYPE_HEADERS` (`int`): The H3 frame type for headers. `Default: 0x1`.
- `H3_FRAME_TYPE_SETTINGS` (`int`): The H3 frame type for settings. `Default: 0x4`.
- `H3_FRAME_TYPE_WEBTRANSPORT_STREAM` (`int`): The H3 frame type used for WebTransport stream data. `Default: 0x41`.
- `H3_STREAM_TYPE_CONTROL` (`int`): The H3 stream type for the control stream. `Default: 0x00`.
- `H3_STREAM_TYPE_QPACK_DECODER` (`int`): The H3 stream type for the QPACK decoder. `Default: 0x03`.
- `H3_STREAM_TYPE_QPACK_ENCODER` (`int`): The H3 stream type for the QPACK encoder. `Default: 0x02`.
- `H3_STREAM_TYPE_WEBTRANSPORT` (`int`): The H3 stream type for a WebTransport stream. `Default: 0x54`.
- `MAX_DATAGRAM_SIZE` (`int`): The maximum theoretical size of a UDP datagram. `Default: 65535`.
- `MAX_STREAM_ID` (`int`): The maximum possible stream ID in QUIC. `Default: 2**62 - 1`.
- `SEC_WEBTRANSPORT_HTTP3_DRAFT13` (`str`): The Sec-WebTransport-Http3-Draft header value. `Default: "webtransport"`.
- `SETTINGS_ENABLE_CONNECT_PROTOCOL` (`int`): The H3 setting to enable the CONNECT method. `Default: 0x8`.
- `SETTINGS_H3_DATAGRAM` (`int`): The H3 setting to enable datagrams. `Default: 0x33`.
- `SETTINGS_QPACK_BLOCKED_STREAMS` (`int`): The H3 setting for QPACK blocked streams. `Default: 0x7`.
- `SETTINGS_QPACK_MAX_TABLE_CAPACITY` (`int`): The H3 setting for QPACK max table capacity. `Default: 0x1`.
- `SETTINGS_WT_INITIAL_MAX_DATA` (`int`): The H3 setting for WebTransport initial max data. `Default: 0x2B61`.
- `SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI` (`int`): The H3 setting for WebTransport initial max bidirectional streams. `Default: 0x2B65`.
- `SETTINGS_WT_INITIAL_MAX_STREAMS_UNI` (`int`): The H3 setting for WebTransport initial max unidirectional streams. `Default: 0x2B64`.
- `SETTINGS_WT_MAX_SESSIONS` (`int`): The H3 setting to enable WebTransport and indicate max sessions. `Default: 0x14E9CD29`.
- `UNIDIRECTIONAL_STREAM` (`int`): The QUIC stream type identifier for unidirectional streams. `Default: 0x2`.
- `WEBTRANSPORT_HEADER` (`str`): The "WebTransport" header field name. `Default: "webtransport"`.
- `WT_DATA_BLOCKED_TYPE` (`int`): The Capsule type for `DATA_BLOCKED`. `Default: 0x190B4D41`.
- `WT_MAX_DATA_TYPE` (`int`): The Capsule type for `MAX_DATA`. `Default: 0x190B4D3D`.
- `WT_MAX_STREAMS_BIDI_TYPE` (`int`): The Capsule type for `MAX_STREAMS` (bidirectional). `Default: 0x190B4D3F`.
- `WT_MAX_STREAMS_UNI_TYPE` (`int`): The Capsule type for `MAX_STREAMS` (unidirectional). `Default: 0x190B4D40`.
- `WT_STREAMS_BLOCKED_BIDI_TYPE` (`int`): The Capsule type for `STREAMS_BLOCKED` (bidirectional). `Default: 0x190B4D43`.
- `WT_STREAMS_BLOCKED_UNI_TYPE` (`int`): The Capsule type for `STREAMS_BLOCKED` (unidirectional). `Default: 0x190B4D44`.

### Library Defaults & Utils

- `DEFAULT_ACCESS_LOG` (`bool`): Default server access log state. `Default: True`.
- `DEFAULT_AUTO_RECONNECT` (`bool`): Default client auto-reconnect state. `Default: False`.
- `DEFAULT_BIND_HOST` (`str`): Default host for the server to bind to. `Default: "localhost"`.
- `DEFAULT_BUFFER_SIZE` (`int`): Default stream buffer size. `Default: 65536`.
- `DEFAULT_CERTFILE` (`str`): Default path for a certificate file. `Default: ""`.
- `DEFAULT_CLIENT_MAX_CONNECTIONS` (`int`): Default maximum concurrent connections for a client. `Default: 100`.
- `DEFAULT_CLIENT_VERIFY_MODE` (`ssl.VerifyMode`): Default SSL verification mode for the client. `Default: ssl.CERT_REQUIRED`.
- `DEFAULT_CLOSE_TIMEOUT` (`float`): Default timeout for a graceful connection close. `Default: 5.0`.
- `DEFAULT_CONNECT_TIMEOUT` (`float`): Default timeout for connection establishment. `Default: 30.0`.
- `DEFAULT_CONGESTION_CONTROL_ALGORITHM` (`str`): Default congestion control algorithm. `Default: "cubic"`.
- `DEFAULT_CONNECTION_CLEANUP_INTERVAL` (`float`): Default interval for cleaning up closed connections. `Default: 30.0`.
- `DEFAULT_CONNECTION_IDLE_CHECK_INTERVAL` (`float`): Default interval for checking connection idle status. `Default: 5.0`.
- `DEFAULT_CONNECTION_IDLE_TIMEOUT` (`float`): Default timeout for idle connections. `Default: 60.0`.
- `DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT` (`float`): Default timeout for sending keep-alive packets. `Default: 30.0`.
- `DEFAULT_DEBUG` (`bool`): Default debug mode state. `Default: False`.
- `DEFAULT_DEV_PORT` (`int`): Default port for the development server. `Default: 4433`.
- `DEFAULT_FLOW_CONTROL_WINDOW_AUTO_SCALE` (`bool`): Default for flow control window auto-scaling. `Default: True`.
- `DEFAULT_FLOW_CONTROL_WINDOW_SIZE` (`int`): Default size of the flow control window. `Default: 1048576`.
- `DEFAULT_INITIAL_MAX_DATA` (`int`): Default initial max data for flow control. `Default: 0`.
- `DEFAULT_INITIAL_MAX_STREAMS_BIDI` (`int`): Default initial max bidirectional streams. `Default: 0`.
- `DEFAULT_INITIAL_MAX_STREAMS_UNI` (`int`): Default initial max unidirectional streams. `Default: 0`.
- `DEFAULT_KEEP_ALIVE` (`bool`): Default TCP keep-alive state. `Default: True`.
- `DEFAULT_KEYFILE` (`str`): Default path for a private key file. `Default: ""`.
- `DEFAULT_LOG_FORMAT` (`str`): Default format string for logging.
- `DEFAULT_LOG_LEVEL` (`str`): Default logging level. `Default: "INFO"`.
- `DEFAULT_MAX_DATAGRAM_SIZE` (`int`): Default maximum datagram size. `Default: 65535`.
- `DEFAULT_MAX_INCOMING_STREAMS` (`int`): Default maximum concurrent incoming streams. `Default: 100`.
- `DEFAULT_MAX_PENDING_EVENTS_PER_SESSION` (`int`): Default maximum buffered events per pending session. `Default: 16`.
- `DEFAULT_MAX_RETRIES` (`int`): Default maximum number of connection retries. `Default: 3`.
- `DEFAULT_MAX_RETRY_DELAY` (`float`): Default maximum delay between connection retries. `Default: 30.0`.
- `DEFAULT_MAX_SESSIONS` (`int`): Default maximum concurrent sessions on the server. `Default: 10000`.
- `DEFAULT_MAX_STREAMS` (`int`): Default maximum concurrent streams per connection. `Default: 100`.
- `DEFAULT_MAX_STREAMS_PER_CONNECTION` (`int`): Alias for `DEFAULT_MAX_STREAMS`. `Default: 100`.
- `DEFAULT_MAX_TOTAL_PENDING_EVENTS` (`int`): Default global maximum for buffered events. `Default: 1000`.
- `DEFAULT_PENDING_EVENT_TTL` (`float`): Default TTL for buffered events in seconds. `Default: 5.0`.
- `DEFAULT_PORT` (`int`): Default port for insecure connections. `Default: 80`.
- `DEFAULT_PROXY_CONNECT_TIMEOUT` (`float`): Default timeout for establishing a connection through a proxy. `Default: 10.0`.
- `DEFAULT_PUBSUB_SUBSCRIPTION_QUEUE_SIZE` (`int`): Default subscription queue size for the Pub/Sub manager. `Default: 16`.
- `DEFAULT_READ_TIMEOUT` (`float`): Default timeout for stream read operations. `Default: 60.0`.
- `DEFAULT_RETRY_BACKOFF` (`float`): Default backoff factor for connection retries. `Default: 2.0`.
- `DEFAULT_RETRY_DELAY` (`float`): Default initial delay for connection retries. `Default: 1.0`.
- `DEFAULT_SECURE_PORT` (`int`): Default port for secure connections. `Default: 443`.
- `DEFAULT_SERVER_MAX_CONNECTIONS` (`int`): Default maximum concurrent connections for a server. `Default: 3000`.
- `DEFAULT_SERVER_VERIFY_MODE` (`ssl.VerifyMode`): Default SSL verification mode for the server. `Default: ssl.CERT_NONE`.
- `DEFAULT_SESSION_CLEANUP_INTERVAL` (`float`): Default interval for cleaning up closed sessions. `Default: 60.0`.
- `DEFAULT_STREAM_CLEANUP_INTERVAL` (`float`): Default interval for cleaning up closed streams. `Default: 15.0`.
- `DEFAULT_STREAM_CREATION_TIMEOUT` (`float`): Default timeout for creating a new stream. `Default: 10.0`.
- `DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_BIDI` (`int`): Default stream increment for bidirectional flow control. `Default: 10`.
- `DEFAULT_STREAM_FLOW_CONTROL_INCREMENT_UNI` (`int`): Default stream increment for unidirectional flow control. `Default: 10`.
- `DEFAULT_VERSION` (`str`): Default protocol version. `Default: "h3"`.
- `DEFAULT_WEBTRANSPORT_PATH` (`str`): Default path for WebTransport endpoint. `Default: "/webtransport"`.
- `DEFAULT_WRITE_TIMEOUT` (`float`): Default timeout for stream write operations. `Default: 30.0`.
- `MAX_BUFFER_SIZE` (`int`): The maximum buffer size for streams. `Default: 1048576`.
- `RECOMMENDED_BUFFER_SIZES` (`dict[str, int]`): Pre-defined buffer sizes for different use cases.
- `SUPPORTED_CONGESTION_CONTROL_ALGORITHMS` (`tuple[str, str]`): Supported congestion control algorithms. `Default: ("reno", "cubic")`.
- `SUPPORTED_VERSIONS` (`tuple[str, ...]`): Supported protocol versions.

## ErrorCodes Class

An `IntEnum` class containing standardized WebTransport and QUIC error codes.

### Attributes

- `NO_ERROR` (`int`): `0x0`
- `INTERNAL_ERROR` (`int`): `0x1`
- `CONNECTION_REFUSED` (`int`): `0x2`
- `FLOW_CONTROL_ERROR` (`int`): `0x3`
- `STREAM_LIMIT_ERROR` (`int`): `0x4`
- `STREAM_STATE_ERROR` (`int`): `0x5`
- `FINAL_SIZE_ERROR` (`int`): `0x6`
- `FRAME_ENCODING_ERROR` (`int`): `0x7`
- `TRANSPORT_PARAMETER_ERROR` (`int`): `0x8`
- `CONNECTION_ID_LIMIT_ERROR` (`int`): `0x9`
- `PROTOCOL_VIOLATION` (`int`): `0xA`
- `INVALID_TOKEN` (`int`): `0xB`
- `APPLICATION_ERROR` (`int`): `0xC`
- `CRYPTO_BUFFER_EXCEEDED` (`int`): `0xD`
- `KEY_UPDATE_ERROR` (`int`): `0xE`
- `AEAD_LIMIT_REACHED` (`int`): `0xF`
- `NO_VIABLE_PATH` (`int`): `0x10`
- `H3_DATAGRAM_ERROR` (`int`): `0x33`
- `H3_NO_ERROR` (`int`): `0x100`
- `H3_GENERAL_PROTOCOL_ERROR` (`int`): `0x101`
- `H3_INTERNAL_ERROR` (`int`): `0x102`
- `H3_STREAM_CREATION_ERROR` (`int`): `0x103`
- `H3_CLOSED_CRITICAL_STREAM` (`int`): `0x104`
- `H3_FRAME_UNEXPECTED` (`int`): `0x105`
- `H3_FRAME_ERROR` (`int`): `0x106`
- `H3_EXCESSIVE_LOAD` (`int`): `0x107`
- `H3_ID_ERROR` (`int`): `0x108`
- `H3_SETTINGS_ERROR` (`int`): `0x109`
- `H3_MISSING_SETTINGS` (`int`): `0x10A`
- `H3_REQUEST_REJECTED` (`int`): `0x10B`
- `H3_REQUEST_CANCELLED` (`int`): `0x10C`
- `H3_REQUEST_INCOMPLETE` (`int`): `0x10D`
- `H3_MESSAGE_ERROR` (`int`): `0x10E`
- `H3_CONNECT_ERROR` (`int`): `0x10F`
- `H3_VERSION_FALLBACK` (`int`): `0x110`
- `WT_SESSION_GONE` (`int`): `0x170D7B68`
- `WT_BUFFERED_STREAM_REJECTED` (`int`): `0x3994BD84`
- `WT_APPLICATION_ERROR_FIRST` (`int`): `0x52E4A40FA8DB`
- `QPACK_DECOMPRESSION_FAILED` (`int`): `0x200`
- `QPACK_ENCODER_STREAM_ERROR` (`int`): `0x201`
- `QPACK_DECODER_STREAM_ERROR` (`int`): `0x202`
- `APP_CONNECTION_TIMEOUT` (`int`): `0x1000`
- `APP_AUTHENTICATION_FAILED` (`int`): `0x1001`
- `APP_PERMISSION_DENIED` (`int`): `0x1002`
- `APP_RESOURCE_EXHAUSTED` (`int`): `0x1003`
- `APP_INVALID_REQUEST` (`int`): `0x1004`
- `APP_SERVICE_UNAVAILABLE` (`int`): `0x1005`

## ClientConfigDefaults Class

A `TypedDict` that defines the structure of a client configuration dictionary.

### Attributes

- `alpn_protocols` (`list[str]`): A list of ALPN protocols to negotiate.
- `auto_reconnect` (`bool`): Flag to enable or disable client auto-reconnection.
- `ca_certs` (`str | None`): Path to a CA certificate file for server verification.
- `certfile` (`str | None`): Path to a certificate file for client authentication.
- `close_timeout` (`float`): Time in seconds to wait for a graceful connection closure.
- `congestion_control_algorithm` (`str`): The congestion control algorithm to use.
- `connect_timeout` (`float`): Time in seconds to wait for connection establishment.
- `connection_cleanup_interval` (`float`): Interval in seconds for cleaning up closed connections.
- `connection_idle_check_interval` (`float`): Interval in seconds for checking connection idle status.
- `connection_idle_timeout` (`float`): Time in seconds after which an idle connection is closed.
- `connection_keepalive_timeout` (`float`): Time in seconds for sending keep-alive packets.
- `debug` (`bool`): Flag to enable or disable debug mode.
- `flow_control_window_auto_scale` (`bool`): Flag for flow control window auto-scaling.
- `flow_control_window_size` (`int`): The size of the flow control window.
- `headers` (`Headers`): Custom headers for the initial connection request.
- `initial_max_data` (`int`): Initial max data for flow control.
- `initial_max_streams_bidi` (`int`): Initial max bidirectional streams.
- `initial_max_streams_uni` (`int`): Initial max unidirectional streams.
- `keep_alive` (`bool`): Flag to enable or disable TCP keep-alive.
- `keyfile` (`str | None`): Path to a private key file for client authentication.
- `log_level` (`str`): The logging level for the client.
- `max_connections` (`int`): Maximum number of concurrent connections.
- `max_datagram_size` (`int`): Maximum size in bytes for an outgoing datagram.
- `max_incoming_streams` (`int`): Maximum number of concurrent incoming streams.
- `max_pending_events_per_session` (`int`): Maximum buffered events per pending session.
- `max_retries` (`int`): Maximum number of retries for a failed connection.
- `max_retry_delay` (`float`): Maximum delay in seconds between connection retries.
- `max_stream_buffer_size` (`int`): Maximum size in bytes for a stream buffer.
- `max_streams` (`int`): Maximum number of concurrent streams per connection.
- `max_total_pending_events` (`int`): Global maximum for buffered events.
- `pending_event_ttl` (`float`): TTL for buffered events in seconds.
- `proxy` (`ProxyConfig | None`): Configuration object for using an HTTP proxy.
- `read_timeout` (`float | None`): Timeout in seconds for stream read operations.
- `retry_backoff` (`float`): The backoff factor for connection retries.
- `retry_delay` (`float`): Initial delay in seconds between connection retries.
- `stream_buffer_size` (`int`): Default buffer size in bytes for streams.
- `stream_cleanup_interval` (`float`): Interval in seconds for cleaning up closed streams.
- `stream_creation_timeout` (`float`): Timeout in seconds for creating a new stream.
- `stream_flow_control_increment_bidi` (`int`): Stream increment for bidirectional flow control.
- `stream_flow_control_increment_uni` (`int`): Stream increment for unidirectional flow control.
- `user_agent` (`str`): The User-Agent string for the connection request.
- `verify_mode` (`ssl.VerifyMode | None`): The SSL verification mode.
- `write_timeout` (`float | None`): Timeout in seconds for stream write operations.

## ServerConfigDefaults Class

A `TypedDict` that defines the structure of a server configuration dictionary.

### Attributes

- `access_log` (`bool`): Flag to enable or disable the access log.
- `alpn_protocols` (`list[str]`): A list of ALPN protocols to negotiate.
- `bind_host` (`str`): The host address to bind the server to.
- `bind_port` (`int`): The port number to bind the server to.
- `ca_certs` (`str | None`): Path to a CA certificate file for client verification.
- `certfile` (`str`): Path to the server's certificate file.
- `congestion_control_algorithm` (`str`): The congestion control algorithm to use.
- `connection_cleanup_interval` (`float`): Interval in seconds for cleaning up closed connections.
- `connection_idle_check_interval` (`float`): Interval in seconds for checking connection idle status.
- `connection_idle_timeout` (`float`): Time in seconds after which an idle connection is closed.
- `connection_keepalive_timeout` (`float`): Time in seconds for sending keep-alive packets.
- `debug` (`bool`): Flag to enable or disable debug mode.
- `flow_control_window_auto_scale` (`bool`): Flag for flow control window auto-scaling.
- `flow_control_window_size` (`int`): The size of the flow control window.
- `initial_max_data` (`int`): Initial max data for flow control.
- `initial_max_streams_bidi` (`int`): Initial max bidirectional streams.
- `initial_max_streams_uni` (`int`): Initial max unidirectional streams.
- `keep_alive` (`bool`): Flag to enable or disable TCP keep-alive.
- `keyfile` (`str`): Path to the server's private key file.
- `log_level` (`str`): The logging level for the server.
- `max_connections` (`int`): Maximum number of concurrent client connections.
- `max_datagram_size` (`int`): Maximum size in bytes for an outgoing datagram.
- `max_incoming_streams` (`int`): Maximum number of concurrent incoming streams per session.
- `max_pending_events_per_session` (`int`): Maximum buffered events per pending session.
- `max_sessions` (`int`): Maximum number of concurrent sessions per connection.
- `max_stream_buffer_size` (`int`): Maximum size in bytes for a stream buffer.
- `max_streams_per_connection` (`int`): Maximum number of concurrent streams per connection.
- `max_total_pending_events` (`int`): Global maximum for buffered events.
- `middleware` (`list[Any]`): A list of middleware to apply to incoming sessions.
- `pending_event_ttl` (`float`): TTL for buffered events in seconds.
- `read_timeout` (`float | None`): Timeout in seconds for stream read operations.
- `session_cleanup_interval` (`float`): Interval in seconds for cleaning up closed sessions.
- `stream_buffer_size` (`int`): Default buffer size in bytes for streams.
- `stream_cleanup_interval` (`float`): Interval in seconds for cleaning up closed streams.
- `stream_flow_control_increment_bidi` (`int`): Stream increment for bidirectional flow control.
- `stream_flow_control_increment_uni` (`int`): Stream increment for unidirectional flow control.
- `verify_mode` (`ssl.VerifyMode`): The SSL verification mode for client certificates.
- `write_timeout` (`float | None`): Timeout in seconds for stream write operations.

## Defaults Class

A utility class that provides safe access to default configurations.

### Class Methods

- **`def get_client_config() -> ClientConfigDefaults`**: Returns a copy of the default client configuration dictionary.
- **`def get_server_config() -> ServerConfigDefaults`**: Returns a copy of the default server configuration dictionary.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Types API](types.md)**: Review type definitions and enumerations.
