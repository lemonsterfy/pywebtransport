# PyWebTransport Documentation

Welcome to PyWebTransport, a high-performance, async-native WebTransport implementation for Python.

## What is PyWebTransport?

PyWebTransport is a production-grade WebTransport protocol stack for Python, enabling low-latency, bidirectional communication over QUIC and HTTP/3. Built for fully async applications, it supports streams and datagrams with a focus on performance, reliability, and extensibility.

**Key Features:**

- **Full WebTransport Support** - Bidirectional streams, unidirectional streams, and datagrams.
- **High-Performance Async API** - Async/await throughout with optimized connection management using `asyncio`.
- **Production Ready** - Features like connection pooling, load balancing, and comprehensive monitoring.
- **Type Safe** - Complete type annotations for excellent IDE support and robust code.
- **Easy to Use** - A simple, high-level API with sensible defaults and extensive documentation.

## Quick Start

Here’s how to get a simple echo client and server running in under a minute.

### Server

First, create a server that echoes back any data it receives on streams and datagrams.

```python
# server.py
import asyncio

from pywebtransport import ServerApp, ServerConfig, WebTransportSession, WebTransportStream
from pywebtransport.exceptions import ConnectionError, SessionError
from pywebtransport.utils import generate_self_signed_cert

# Generate a self-signed certificate for local development
generate_self_signed_cert("localhost")

# Configure the server
app = ServerApp(
    config=ServerConfig.create(
        certfile="localhost.crt",
        keyfile="localhost.key",
    )
)


async def handle_datagrams(session: WebTransportSession) -> None:
    """Listen for incoming datagrams and echo them back."""
    try:
        while True:
            data = await session.datagrams.receive()
            await session.datagrams.send(b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        pass  # Connection closed


async def handle_streams(session: WebTransportSession) -> None:
    """Listen for incoming streams and echo data back."""
    try:
        async for stream in session.incoming_streams():
            if isinstance(stream, WebTransportStream):
                data = await stream.read_all()
                await stream.write_all(b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        pass  # Connection closed


@app.route("/")
async def echo_handler(session: WebTransportSession) -> None:
    """Run datagram and stream handlers concurrently for a session."""
    datagram_task = asyncio.create_task(handle_datagrams(session))
    stream_task = asyncio.create_task(handle_streams(session))
    try:
        await session.wait_closed()
    finally:
        datagram_task.cancel()
        stream_task.cancel()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4433)

```

### Client

Now, create a client to connect to the server, send data, and print the responses.

```python
# client.py
import asyncio
import ssl

from pywebtransport import ClientConfig, WebTransportClient


async def main() -> None:
    # Create a client with a self-signed certificate
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE)

    async with WebTransportClient.create(config=config) as client:
        # Connect to the server
        async with await client.connect("https://127.0.0.1:4433/") as session:
            print("Connection established. Testing datagrams...")
            await session.datagrams.send(b"Hello, Datagram!")
            response = await session.datagrams.receive()
            print(f"Datagram echo: {response!r}\n")

            print("Testing streams...")
            stream = await session.create_bidirectional_stream()
            await stream.write_all(b"Hello, Stream!")
            response = await stream.read_all()
            print(f"Stream echo: {response!r}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

```

## Core Concepts

### Client and Server

The library provides two main entry points: `WebTransportClient` for creating client connections and `ServerApp` for building server applications with routing and middleware.

### Sessions

A `WebTransportSession` represents an active connection and is the primary interface for communication. Each session can manage multiple streams and datagrams.

### Streams

Streams provide reliable, ordered communication with automatic flow control. Use bidirectional streams for request-response patterns and unidirectional streams for one-way data transfer.

### Datagrams

Datagrams offer low-latency, unreliable messaging, ideal for real-time applications where speed is more important than guaranteed delivery.

## Use Cases

### Real-time Interactive Systems

_For scenarios requiring instant, bidirectional communication._

- **Live Collaboration:** Real-time document editing, whiteboarding, and design tools.
- **Instant Messaging:** Live chat, notifications, and signaling services.
- **Interactive Entertainment:** Multiplayer online gaming, virtual reality (VR), and live stream interactions.
- **Real-time Dashboards:** Financial trading platforms, monitoring panels, and live sports updates.

### High-Performance Data Streaming

_For high-throughput, low-overhead data transport._

- **Media Streaming:** Live video, audio feeds, and webcam broadcasting.
- **Large-Scale Data Transfer:** Bulk file uploads/downloads and data synchronization.
- **IoT & Telemetry:** Efficiently aggregating sensor data from a multitude of devices.

### AI & Machine Learning

_For accelerating data-intensive AI workflows._

- **Real-time Inference:** Stream live audio, video, or sensor data to models for analysis.
- **Distributed Training:** Efficiently exchange model gradients and parameters between nodes.
- **Data Augmentation:** Feed large datasets to augmentation pipelines with low latency.

### Modern Backend Architecture

_For optimizing server-to-server and client-server communication._

- **Microservice Communication:** A low-latency, high-throughput message bus between services.
- **API Acceleration:** Reduce repetitive HTTP overhead with persistent connections.
- **Edge Computing:** Establish efficient data channels between edge nodes and the cloud.

## Documentation Structure

### Getting Started

- **[Installation](installation.md)** - Setup and installation guide
- **[Quick Start](quickstart.md)** - 5-minute tutorial to get running

### User Guides

- **[Client Development](user-guide/client.md)** - Building WebTransport clients
- **[Server Development](user-guide/server.md)** - Creating WebTransport servers

### API Reference

- **[Complete API Reference](api-reference/)** - All available APIs, including client, server, session, stream, datagrams, and configuration.

## Community

- **GitHub** - [Source code and issues](https://github.com/lemonsterfy/pywebtransport)
- **PyPI** - [Package distribution](https://pypi.org/project/pywebtransport/)

## License

PyWebTransport is released under the MIT License. See [LICENSE](https://github.com/lemonsterfy/pywebtransport/blob/main/LICENSE) for details.
