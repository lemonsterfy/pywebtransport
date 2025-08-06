# API Reference: Constants

This document provides a comprehensive reference for the `pywebtransport.constants` module, including protocol-level constants, error codes, and default configuration values.

---

## Protocol Constants

### WebTransportConstants Class

A centralized class containing fundamental constants related to the WebTransport and HTTP/3 protocols.

#### Port & Version Constants

- `DEFAULT_PORT` (`int`): 80
- `DEFAULT_SECURE_PORT` (`int`): 443
- `DEFAULT_DEV_PORT` (`int`): 4433 (Default for the development server)
- `DRAFT_VERSION` (`int`): 13
- `SUPPORTED_VERSIONS` (`tuple[str, ...]`): Supported protocol versions.
- `DEFAULT_VERSION` (`str`): "h3"

#### Stream & Frame Type Constants

- `BIDIRECTIONAL_STREAM` (`int`): 0x0
- `UNIDIRECTIONAL_STREAM` (`int`): 0x2
- `WEBTRANSPORT_H3_BIDI_STREAM_TYPE` (`int`): 0x41
- `WEBTRANSPORT_H3_UNI_STREAM_TYPE` (`int`): 0x54
- `CLOSE_WEBTRANSPORT_SESSION_TYPE` (`int`): 0x2843
- `DRAIN_WEBTRANSPORT_SESSION_TYPE` (`int`): 0x78AE

#### H3 & QPACK Settings Constants

- `SETTINGS_QPACK_MAX_TABLE_CAPACITY` (`int`): 0x1
- `SETTINGS_QPACK_BLOCKED_STREAMS` (`int`): 0x7
- `SETTINGS_ENABLE_CONNECT_PROTOCOL` (`int`): 0x8
- `SETTINGS_H3_DATAGRAM` (`int`): 0x33
- `SETTINGS_ENABLE_WEBTRANSPORT` (`int`): 0x2B603742

#### Limits & Timeouts

- `MAX_STREAM_ID` (`int`): 2\*\*62 - 1
- `MAX_DATAGRAM_SIZE` (`int`): 65535
- `DEFAULT_MAX_STREAMS` (`int`): 100
- `DEFAULT_BUFFER_SIZE` (`int`): 65536 (64KB)
- `MAX_BUFFER_SIZE` (`int`): 1048576 (1MB)
- `DEFAULT_CONNECT_TIMEOUT` (`float`): 30.0 seconds
- `DEFAULT_READ_TIMEOUT` (`float`): 60.0 seconds
- `DEFAULT_WRITE_TIMEOUT` (`float`): 30.0 seconds
- `DEFAULT_CLOSE_TIMEOUT` (`float`): 5.0 seconds
- `DEFAULT_KEEPALIVE_TIMEOUT` (`float`): 300.0 seconds
- `DEFAULT_STREAM_CREATION_TIMEOUT` (`float`): 10.0 seconds

#### Flow Control Constants

- `DEFAULT_INITIAL_MAX_DATA` (`int`): 1MB
- `DEFAULT_INITIAL_MAX_STREAM_DATA_BIDI_LOCAL` (`int`): 256KB
- `DEFAULT_INITIAL_MAX_STREAM_DATA_BIDI_REMOTE` (`int`): 256KB
- `DEFAULT_INITIAL_MAX_STREAM_DATA_UNI` (`int`): 256KB
- `DEFAULT_INITIAL_MAX_STREAMS_BIDI` (`int`): 100
- `DEFAULT_INITIAL_MAX_STREAMS_UNI` (`int`): 3

#### ALPN Constants

- `ALPN_H3` (`str`): "h3"
- `ALPN_H3_29` (`str`): "h3-29"
- `ALPN_H3_32` (`str`): "h3-32"
- `DEFAULT_ALPN_PROTOCOLS` (`tuple[str, str]`): ("h3", "h3-29")

---

## Error Codes

### ErrorCodes Enumeration

An `IntEnum` class containing standardized error codes for QUIC, HTTP/3, and application-level failures.

#### Core QUIC Error Codes

- `NO_ERROR` (`int`): 0x0
- `INTERNAL_ERROR` (`int`): 0x1
- `CONNECTION_REFUSED` (`int`): 0x2
- `FLOW_CONTROL_ERROR` (`int`): 0x3

#### HTTP/3 Error Codes

- `H3_NO_ERROR` (`int`): 0x100
- `H3_GENERAL_PROTOCOL_ERROR` (`int`): 0x101

#### Application-Level Error Codes

- `APP_CONNECTION_TIMEOUT` (`int`): 0x1000
- `APP_AUTHENTICATION_FAILED` (`int`): 0x1001
- `APP_PERMISSION_DENIED` (`int`): 0x1002

---

## Module-Level Constants

### Headers & Schemes

- `ORIGIN_HEADER` (`str`): "origin"
- `USER_AGENT_HEADER` (`str`): "user-agent"
- `WEBTRANSPORT_HEADER` (`str`): "webtransport"
- `SECURE_SCHEMES` (`tuple[str, str]`): ("https", "wss")
- `WEBTRANSPORT_SCHEMES` (`tuple[str, str]`): ("https", "wss")

### Paths & MIME Types

- `DEFAULT_WEBTRANSPORT_PATH` (`str`): "/webtransport"
- `WEBTRANSPORT_MIME_TYPE` (`str`): "application/webtransport"

### Logging & Performance

- `DEFAULT_LOG_FORMAT` (`str`): The default format string for logging.
- `DEFAULT_LOG_LEVEL` (`str`): "INFO"
- `RECOMMENDED_BUFFER_SIZES` (`dict[str, int]`): A dictionary with keys `"small"`, `"medium"`, and `"large"` for suggested buffer sizes.

---

## Default Configuration Utilities

### Defaults Class

A utility class that provides safe access to copies of the default configurations for the client and server.

#### Class Methods

- **`get_client_config() -> ClientConfigDefaults`**: Returns a copy of the default client configuration dictionary.
- **`get_server_config() -> ServerConfigDefaults`**: Returns a copy of the default server configuration dictionary.

#### Usage Example

```python
from pywebtransport import ClientConfig
from pywebtransport.constants import Defaults

# Get a copy of the default client configuration
client_config_dict = Defaults.get_client_config()

# Customize the configuration
client_config_dict["connect_timeout"] = 15.0
client_config_dict["user_agent"] = "MyApp/1.0"

# Create a config object from the dictionary
config = ClientConfig.from_dict(client_config_dict)
```

---

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
- **[Types API](types.md)**: Review type definitions and enumerations.
