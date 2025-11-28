# PyWebTransport

[![PyPI version](https://badge.fury.io/py/pywebtransport.svg)](https://badge.fury.io/py/pywebtransport)
[![Python Versions](https://img.shields.io/pypi/pyversions/pywebtransport.svg)](https://pypi.org/project/pywebtransport/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://github.com/lemonsterfy/pywebtransport/workflows/CI/badge.svg)](https://github.com/lemonsterfy/pywebtransport/actions)
[![Coverage](https://codecov.io/gh/lemonsterfy/pywebtransport/branch/main/graph/badge.svg)](https://codecov.io/gh/lemonsterfy/pywebtransport)
[![Docs](https://readthedocs.org/projects/pywebtransport/badge/?version=latest)](https://docs.pywebtransport.org/en/latest/)

An async-native WebTransport stack for Python.

## Features

- **Full Async Support**: Built from the ground up on `asyncio` for high-performance, non-blocking I/O.
- **High-Level Frameworks**: Includes a `ServerApp` with routing and middleware, and a versatile `WebTransportClient` with helpers for fleet management, auto-reconnection, and browser-like navigation.
- **Advanced Messaging**: Built-in managers for Pub/Sub and RPC (JSON-RPC 2.0 compliant), plus pluggable serializers (`JSON`, `MsgPack`, `Protobuf`) for structured data.
- **Complete Protocol Implementation**: Full support for bidirectional and unidirectional streams, as well as unreliable datagrams.
- **Lifecycle and Resource Management**: Robust, async context-managed components for handling connections, sessions, streams, monitoring, pooling, and resource management.
- **Event-Driven Architecture**: A powerful `EventEmitter` system for decoupled, asynchronous communication between components.
- **Type-Safe and Tested**: A fully type-annotated API with extensive test coverage (unit, integration, E2E, performance, benchmark) to ensure reliability and maintainability.

## Installation

```bash
pip install pywebtransport
```

## Quick Start

### Server

```python
# server.py
import asyncio

from pywebtransport import Event, ServerApp, ServerConfig, WebTransportSession, WebTransportStream
from pywebtransport.types import EventType
from pywebtransport.utils import generate_self_signed_cert

generate_self_signed_cert(hostname="localhost")

app = ServerApp(
    config=ServerConfig(
        certfile="localhost.crt",
        keyfile="localhost.key",
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=10,
    )
)


@app.route(path="/")
async def echo_handler(session: WebTransportSession) -> None:
    async def on_datagram(event: Event) -> None:
        if isinstance(event.data, dict) and isinstance(event.data.get("data"), bytes):
            await session.send_datagram(data=b"ECHO: " + event.data["data"])

    async def on_stream(event: Event) -> None:
        if isinstance(event.data, dict):
            stream = event.data.get("stream")
            if isinstance(stream, WebTransportStream):
                asyncio.create_task(handle_stream(stream))

    session.events.on(event_type=EventType.DATAGRAM_RECEIVED, handler=on_datagram)
    session.events.on(event_type=EventType.STREAM_OPENED, handler=on_stream)

    try:
        await session.events.wait_for(event_type=EventType.SESSION_CLOSED)
    finally:
        session.events.off(event_type=EventType.DATAGRAM_RECEIVED, handler=on_datagram)
        session.events.off(event_type=EventType.STREAM_OPENED, handler=on_stream)


async def handle_stream(stream: WebTransportStream) -> None:
    try:
        data = await stream.read_all()
        await stream.write_all(data=b"ECHO: " + data)
    except Exception:
        pass


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4433)
```

### Client

```python
# client.py
import asyncio
import ssl

from pywebtransport import ClientConfig, WebTransportClient
from pywebtransport.types import EventType


async def main() -> None:
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=10,
    )

    async with WebTransportClient(config=config) as client:
        session = await client.connect(url="https://127.0.0.1:4433/")

        await session.send_datagram(data=b"Hello, Datagram!")

        event = await session.events.wait_for(event_type=EventType.DATAGRAM_RECEIVED, timeout=5.0)
        if isinstance(event.data, dict):
            print(f"Datagram: {event.data.get('data')!r}")

        stream = await session.create_bidirectional_stream()
        await stream.write_all(data=b"Hello, Stream!")

        response = await stream.read_all()
        print(f"Stream: {response!r}")

        await session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

## Documentation

- **[API Reference](docs/api-reference/index.md)** - Explore the complete API documentation.

## Requirements

- Python 3.12+
- TLS 1.3

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on the development setup, testing, and pull request process.

## Sponsors

<p>
  <a href="https://www.fastly.com/" target="_blank" rel="noopener noreferrer">
    <img
      src="https://upload.wikimedia.org/wikipedia/commons/8/8a/Fastly_logo.svg"
      alt="Fastly"
      width="100"
    />
  </a>
</p>

## Acknowledgments

- [aioquic](https://github.com/aiortc/aioquic) for the underlying QUIC protocol implementation.
- [WebTransport Working Group](https://datatracker.ietf.org/wg/webtrans/) for defining and standardizing the WebTransport protocol.

## Support

- **Issues**: [GitHub Issues](https://github.com/lemonsterfy/pywebtransport/issues)
- **Discussions**: [GitHub Discussions](https://github.com/lemonsterfy/pywebtransport/discussions)
- **Email**: lemonsterfy@gmail.com

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
