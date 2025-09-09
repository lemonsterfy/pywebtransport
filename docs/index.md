# PyWebTransport Documentation

Welcome to PyWebTransport, the canonical, async-native WebTransport stack for Python.

## What is PyWebTransport?

PyWebTransport is the canonical, async-native WebTransport stack for Python, enabling low-latency, bidirectional communication over QUIC and HTTP/3. It provides a complete, robust implementation of streams and datagrams alongside a high-level application framework, with a focus on standards compliance, performance, and reliability

**Key Features:**

- **Full Async Support**: Built from the ground up on `asyncio` for high-performance, non-blocking I/O.
- **High-Level Frameworks**: Includes a `ServerApp` with routing and middleware, and a versatile `WebTransportClient` with helpers for pooling, auto-reconnection, and proxying.
- **Complete Protocol Implementation**: Full support for bidirectional and unidirectional streams, as well as unreliable datagrams.
- **Structured Messaging**: Pluggable `JSON`, `MsgPack`, and `Protobuf` serializers for sending and receiving structured data objects over streams and datagrams.
- **Lifecycle and Resource Management**: Robust, async context-managed components for handling connections, sessions, streams, and monitoring.
- **Event-Driven Architecture**: A powerful `EventEmitter` and `EventBus` system for decoupled, asynchronous communication between components.
- **Type-Safe and Tested**: A fully type-annotated API with extensive test coverage (unit, integration, E2E) to ensure reliability and maintainability.

## Core Concepts

### Client and Server

The library provides two main entry points: `WebTransportClient` for creating client connections and `ServerApp` for building server applications with routing and middleware.

### Sessions

A `WebTransportSession` represents an active connection and is the primary interface for communication. Each session can manage multiple streams and datagrams.

### Streams

Streams provide reliable, ordered communication with automatic flow control. Use bidirectional streams for request-response patterns and unidirectional streams for one-way data transfer.

### Datagrams

Datagrams offer low-latency, unreliable, and out-of-order messaging, ideal for real-time applications where speed is more important than guaranteed delivery.

## Use Cases

### Real-time Interactivity

- **Live Collaboration:** Real-time document editing, whiteboarding, and design tools.
- **Instant Messaging:** Live chat, notifications, and signaling services.
- **Interactive Entertainment:** Multiplayer online gaming, virtual reality (VR), and live stream interactions.
- **Real-time Dashboards:** Financial trading platforms, monitoring panels, and live sports updates.

### High-Performance Data Streaming

- **Media Streaming:** Live video, audio feeds, and webcam broadcasting.
- **Large-Scale Data Transfer:** Bulk file uploads/downloads and data synchronization.
- **IoT & Telemetry:** Efficiently aggregating sensor data from a multitude of devices.

### AI & Machine Learning

- **Real-time Inference:** Stream live audio, video, or sensor data to models for analysis.
- **Distributed Training:** Efficiently exchange model gradients and parameters between nodes.
- **Data Augmentation:** Feed large datasets to augmentation pipelines with low latency.

### Modern Backend Architecture

- **Microservice Communication:** A low-latency, high-throughput message bus between services.
- **API Acceleration:** Reduce repetitive HTTP overhead with persistent connections.
- **Edge Computing:** Establish efficient data channels between edge nodes and the cloud.

## Documentation Structure

### Getting Started

- **[Installation](installation.md)** - Setup and installation guide.
- **[Quick Start](quickstart.md)** - 5-minute tutorial to get running.

### API Reference

- **[Complete API Reference](api-reference/index.md)** - All available APIs, including client, server, session, stream, datagrams, and configuration. The API is organized into layers (Application, Core, and Foundational) to help you find the right abstraction for your needs.

## Community

- **GitHub** - [Source code and issues](https://github.com/lemonsterfy/pywebtransport)
- **PyPI** - [Package distribution](https://pypi.org/project/pywebtransport/)

## License

PyWebTransport is released under the MIT License. See [LICENSE](https://github.com/lemonsterfy/pywebtransport/blob/main/LICENSE) for details.
