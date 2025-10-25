# PyWebTransport

[![PyPI version](https://badge.fury.io/py/pywebtransport.svg)](https://badge.fury.io/py/pywebtransport)
[![Python Versions](https://img.shields.io/pypi/pyversions/pywebtransport.svg)](https://pypi.org/project/pywebtransport/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://github.com/lemonsterfy/pywebtransport/workflows/CI/badge.svg)](https://github.com/lemonsterfy/pywebtransport/actions)
[![Coverage](https://codecov.io/gh/lemonsterfy/pywebtransport/branch/main/graph/badge.svg)](https://codecov.io/gh/lemonsterfy/pywebtransport)
[![Docs](https://readthedocs.org/projects/pywebtransport/badge/?version=latest)](https://pywebtransport.readthedocs.io/en/latest/)

The canonical, async-native WebTransport stack for Python.

## Features

- **Full Async Support**: Built from the ground up on `asyncio` for high-performance, non-blocking I/O.
- **High-Level Frameworks**: Includes a `ServerApp` with routing and middleware, and a versatile `WebTransportClient` with helpers for fleet management, auto-reconnection, and browser-like navigation.
- **Advanced Messaging**: Built-in managers for Pub/Sub and RPC (JSON-RPC 2.0 compliant), plus pluggable serializers (`JSON`, `MsgPack`, `Protobuf`) for structured data.
- **Complete Protocol Implementation**: Full support for bidirectional and unidirectional streams, as well as unreliable datagrams.
- **Lifecycle and Resource Management**: Robust, async context-managed components for handling connections, sessions, streams, monitoring, pooling, and resource management.
- **Event-Driven Architecture**: A powerful `EventEmitter` system for decoupled, asynchronous communication between components.
- **Type-Safe and Tested**: A fully type-annotated API with extensive test coverage (unit, integration, E2E) to ensure reliability and maintainability.

## Installation

```bash
pip install pywebtransport
```

For more detailed instructions, including virtual environments and platform-specific notes, see the [Installation Guide](docs/installation.md).

## Quick Start

### Server

```python
# server.py
import asyncio

from pywebtransport import (
    ConnectionError,
    ServerApp,
    ServerConfig,
    SessionError,
    WebTransportSession,
    WebTransportStream,
)
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


async def handle_datagrams(session: WebTransportSession) -> None:
    try:
        datagram_transport = await session.create_datagram_transport()
        while True:
            data = await datagram_transport.receive()
            await datagram_transport.send(data=b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        pass


async def handle_streams(session: WebTransportSession) -> None:
    try:
        async for stream in session.incoming_streams():
            if isinstance(stream, WebTransportStream):
                data = await stream.read_all()
                await stream.write_all(data=b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        pass


@app.route(path="/")
async def echo_handler(session: WebTransportSession) -> None:
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

```python
# client.py
import asyncio
import ssl

from pywebtransport import ClientConfig, WebTransportClient


async def main() -> None:
    config = ClientConfig(
        verify_mode=ssl.CERT_NONE,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=10,
    )

    async with WebTransportClient(config=config) as client:
        session = await client.connect(url="https://127.0.0.1:4433/")

        print("Connection established. Testing datagrams...")
        datagram_transport = await session.create_datagram_transport()
        await datagram_transport.send(data=b"Hello, Datagram!")
        response = await datagram_transport.receive()
        print(f"Datagram echo: {response!r}\n")

        print("Testing streams...")
        stream = await session.create_bidirectional_stream()
        await stream.write_all(data=b"Hello, Stream!")
        response = await stream.read_all()
        print(f"Stream echo: {response!r}")

        await session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

## Documentation

- **[Installation Guide](docs/installation.md)** - Learn how to install the library.
- **[Quick Start](docs/quickstart.md)** - Discover how to get started with basic client and server setup.
- **[API Reference](docs/api-reference/)** - Explore the complete API documentation.

## Requirements

- Python 3.11+
- asyncio support
- TLS 1.3

**Dependencies:**

- aioquic >= 1.2.0
- cryptography >= 45.0.4

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on the development setup, testing, and pull request process.

**Development Setup:**

```bash
git clone https://github.com/lemonsterfy/pywebtransport.git
cd pywebtransport
pip install -r dev-requirements.txt
pip install -e .
tox
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [aioquic](https://github.com/aiortc/aioquic) for the underlying QUIC protocol implementation.
- [WebTransport Working Group](https://datatracker.ietf.org/wg/webtrans/) for defining and standardizing the WebTransport protocol.

## Support

- **Issues**: [GitHub Issues](https://github.com/lemonsterfy/pywebtransport/issues)
- **Discussions**: [GitHub Discussions](https://github.com/lemonsterfy/pywebtransport/discussions)
- **Email**: lemonsterfy@gmail.com
