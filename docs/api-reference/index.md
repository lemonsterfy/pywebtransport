# API Reference

Complete reference documentation for PyWebTransport's public APIs.

---

## Overview

PyWebTransport provides a comprehensive and robust WebTransport implementation for Python with a pure async/await design. The API is structured in layers, from a high-level application framework to low-level protocol control, enabling both rapid development and fine-grained customization.

---

## Application-Layer APIs

The primary entry points for building WebTransport applications. These abstractions are designed for ease of use and cover the most common use cases.

| Module                          | Description                                           | Key Classes                                                                      |
| :------------------------------ | :---------------------------------------------------- | :------------------------------------------------------------------------------- |
| **[Client](client.md)**         | High-level client abstractions and fleet management.  | `WebTransportClient`, `ClientFleet`, `ReconnectingClient`, `WebTransportBrowser` |
| **[Monitor](monitor.md)**       | Health and performance monitoring for key components. | `ClientMonitor`, `ConnectionMonitor`, `ServerMonitor`, `SessionMonitor`          |
| **[Pool](pool.md)**             | Reusable object pools for sessions and streams.       | `SessionPool`, `StreamPool`                                                      |
| **[Pub/Sub](pubsub.md)**        | High-level framework for publish/subscribe messaging. | `PubSubManager`, `Subscription`                                                  |
| **[RPC](rpc.md)**               | Framework for Remote Procedure Calls (JSON-RPC 2.0).  | `RpcManager`, `RpcRequest`, `RpcSuccessResponse`                                 |
| **[Server](server.md)**         | High-level server application framework with routing. | `ServerApp`, `WebTransportServer`, `ServerCluster`, `RequestRouter`              |
| **[Serializer](serializer.md)** | Framework for structured data serialization.          | `JSONSerializer`, `MsgPackSerializer`, `ProtobufSerializer`                      |

---

## Core APIs

Foundational components that provide the core logic and building blocks for the high-level APIs. Use these for more advanced customization and control.

| Module                          | Description                                                 | Key Classes                                                                      |
| :------------------------------ | :---------------------------------------------------------- | :------------------------------------------------------------------------------- |
| **[Connection](connection.md)** | Core connection abstraction and load balancing.             | `WebTransportConnection`, `ConnectionLoadBalancer`                               |
| **[Datagram](datagram.md)**     | Unreliable, low-latency datagram messaging and utilities.   | `StructuredDatagramTransport`, `DatagramReliabilityLayer`, `DatagramBroadcaster` |
| **[Manager](manager.md)**       | Generic resource lifecycle managers.                        | `ConnectionManager`, `SessionManager`                                            |
| **[Session](session.md)**       | Session lifecycle and communication management abstraction. | `WebTransportSession`                                                            |
| **[Stream](stream.md)**         | Reliable, ordered stream communication abstractions.        | `WebTransportStream`, `WebTransportSendStream`, `WebTransportReceiveStream`      |

---

## Foundational APIs

Cross-cutting components that provide essential utilities, data structures, and constants used throughout the library.

| Module                          | Description                                       | Key Classes / Concepts                  |
| :------------------------------ | :------------------------------------------------ | :-------------------------------------- |
| **[Configuration](config.md)**  | Client and server configuration data classes.     | `ClientConfig`, `ServerConfig`          |
| **[Constants](constants.md)**   | Protocol constants and default values.            | `ErrorCodes`                            |
| **[Events](events.md)**         | Asynchronous, event-driven programming framework. | `EventEmitter`, `Event`, `EventHandler` |
| **[Exceptions](exceptions.md)** | Exception hierarchy and error handling patterns.  | `WebTransportError`, `StreamError`      |
| **[Types](types.md)**           | Core type aliases, protocols, and enumerations.   | `StreamId`, `SessionId`, `StreamState`  |
| **[Utils](utils.md)**           | Helper functions and utilities.                   | `Timer`                                 |

---

## See Also

- **[Client API](client.md)**: Learn how to create and manage client connections.
- **[Connection API](connection.md)**: Manage the underlying QUIC connection lifecycle.
- **[Server API](server.md)**: Build and manage WebTransport servers.
- **[Session API](session.md)**: Learn about the `WebTransportSession` lifecycle and management.
