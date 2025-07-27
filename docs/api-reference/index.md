# API Reference

Complete reference documentation for PyWebTransport's public APIs.

## Overview

PyWebTransport provides a comprehensive WebTransport implementation for Python with async/await support. The API is designed in layers, from high-level convenience functions to low-level protocol control, enabling both rapid development and fine-grained customization.

**Key Features:**

- Full WebTransport protocol implementation (bidirectional streams, unidirectional streams, datagrams)
- High-performance async client and server implementations
- Production-ready connection pooling and load balancing
- Comprehensive monitoring and debugging capabilities
- Type-safe API with complete type annotations
- Extensive test coverage (unit, integration, end-to-end)

## Core APIs

Essential interfaces for WebTransport development.

| Module                    | Description                                                 | Key Classes                                                                 |
| ------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------------------- |
| **[Client](client.md)**   | WebTransport client with connection management and pooling. | `WebTransportClient`, `ClientPool`, `ReconnectingClient`                    |
| **[Server](server.md)**   | WebTransport server with routing and middleware support.    | `WebTransportServer`, `ServerApp`, `ServerMonitor`                          |
| **[Session](session.md)** | Session lifecycle and communication management.             | `WebTransportSession`, `SessionStats`                                       |
| **[Stream](stream.md)**   | Reliable ordered communication with flow control.           | `WebTransportStream`, `WebTransportSendStream`, `WebTransportReceiveStream` |

## Infrastructure APIs

Lower-level APIs for advanced use cases and customization.

| Module                          | Description                           | Key Classes                                                          |
| ------------------------------- | ------------------------------------- | -------------------------------------------------------------------- |
| **[Datagram](datagram.md)**     | Unreliable low-latency messaging.     | `WebTransportDatagramDuplexStream`, `DatagramReliabilityLayer`       |
| **[Connection](connection.md)** | Low-level connection management.      | `WebTransportConnection`, `ConnectionPool`, `ConnectionLoadBalancer` |
| **[Protocol](protocol.md)**     | WebTransport protocol implementation. | `WebTransportProtocolHandler`                                        |
| **[Events](events.md)**         | Event-driven programming support.     | `EventEmitter`, `EventBus`                                           |

## Configuration & Support

Configuration management and development utilities.

| Module                          | Description                                | Key Classes                                           |
| ------------------------------- | ------------------------------------------ | ----------------------------------------------------- |
| **[Configuration](config.md)**  | Client and server configuration.           | `ClientConfig`, `ServerConfig`, `ConfigBuilder`       |
| **[Types](types.md)**           | Type aliases, protocols, and enumerations. | `StreamId`, `SessionId`, `StreamDirection`            |
| **[Constants](constants.md)**   | Protocol constants and default values.     | `WebTransportConstants`, `ErrorCodes`                 |
| **[Exceptions](exceptions.md)** | Error handling and recovery patterns.      | `WebTransportError`, `StreamError`, `ConnectionError` |
| **[Utils](utils.md)**           | Debugging tools and utility functions.     | Validation, formatting, diagnostics                   |

## See Also

- **[Installation](installation.md)** - Setup and installation guide
- **[Quick Start](../quickstart.md)** - 5-minute tutorial
- **[Client Guide](../user-guide/client.md)** - Client development patterns
- **[Server Guide](../user-guide/server.md)** - Server development patterns
