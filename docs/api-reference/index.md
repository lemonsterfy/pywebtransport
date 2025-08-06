# API Reference

Complete reference documentation for PyWebTransport's public APIs.

---

## Overview

PyWebTransport provides a comprehensive WebTransport implementation for Python with async/await support. The API is designed in layers, from high-level convenience functions to low-level protocol control, enabling both rapid development and fine-grained customization.

**Key Features:**

- Full WebTransport protocol implementation (bidirectional streams, unidirectional streams, datagrams).
- High-performance async client and server application frameworks.
- Production-ready components for connection pooling, management, and load balancing.
- Comprehensive monitoring and debugging capabilities.
- Type-safe API with complete type annotations.
- Extensive test coverage (unit, integration, end-to-end).

---

## Core APIs

Essential interfaces for WebTransport development.

| Module                      | Description                                               | Key Classes                                              |
| :-------------------------- | :-------------------------------------------------------- | :------------------------------------------------------- |
| **[Client](client.md)**     | High-level client and connection management abstractions. | `WebTransportClient`, `ClientPool`, `ReconnectingClient` |
| **[Server](server.md)**     | High-level server application framework with routing.     | `ServerApp`, `WebTransportServer`, `ServerMonitor`       |
| **[Session](session.md)**   | Session lifecycle and communication management.           | `WebTransportSession`, `SessionManager`                  |
| **[Stream](stream.md)**     | Reliable, ordered, and multiplexed stream communication.  | `WebTransportStream`, `WebTransportSendStream`           |
| **[Datagram](datagram.md)** | Unreliable, low-latency datagram messaging.               | `WebTransportDatagramDuplexStream`                       |

---

## Infrastructure APIs

Lower-level APIs for advanced use cases and customization.

| Module                          | Description                                       | Key Classes                                           |
| :------------------------------ | :------------------------------------------------ | :---------------------------------------------------- |
| **[Connection](connection.md)** | Low-level connection management and pooling.      | `WebTransportConnection`, `ConnectionPool`            |
| **[Protocol](protocol.md)**     | Low-level WebTransport protocol implementation.   | `WebTransportProtocolHandler`                         |
| **[Events](events.md)**         | Asynchronous, event-driven programming framework. | `EventEmitter`, `EventBus`, `Event`                   |
| **[Exceptions](exceptions.md)** | Exception hierarchy and error handling patterns.  | `WebTransportError`, `StreamError`, `ConnectionError` |

---

## Configuration & Support

Configuration management and development utilities.

| Module                         | Description                                     | Key Classes / Concepts                          |
| :----------------------------- | :---------------------------------------------- | :---------------------------------------------- |
| **[Configuration](config.md)** | Client and server configuration data classes.   | `ClientConfig`, `ServerConfig`, `ConfigBuilder` |
| **[Constants](constants.md)**  | Protocol constants and default values.          | `WebTransportConstants`, `ErrorCodes`           |
| **[Types](types.md)**          | Core type aliases, protocols, and enumerations. | `StreamId`, `SessionId`, `StreamState`          |
| **[Utils](utils.md)**          | Helper functions for common tasks.              | Logging, Networking, Security, Validation       |

---

## See Also

- **[Installation Guide](../installation.md)** - In-depth setup and installation guide.
- **[Quick Start](../quickstart.md)** - A 5-minute tutorial to get started.
- **[Client API](client.md)** - Detailed client API reference and usage patterns.
- **[Server API](server.md)** - Detailed server API reference and usage patterns.
