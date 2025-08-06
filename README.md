# PyWebTransport

[![PyPI version](https://badge.fury.io/py/pywebtransport.svg)](https://badge.fury.io/py/pywebtransport)
[![Python Versions](https://img.shields.io/pypi/pyversions/pywebtransport.svg)](https://pypi.org/project/pywebtransport/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://github.com/lemonsterfy/pywebtransport/workflows/CI/badge.svg)](https://github.com/lemonsterfy/pywebtransport/actions)
[![Coverage](https://codecov.io/gh/lemonsterfy/pywebtransport/branch/main/graph/badge.svg)](https://codecov.io/gh/lemonsterfy/pywebtransport)
[![Docs](https://readthedocs.org/projects/pywebtransport/badge/?version=latest)](https://pywebtransport.readthedocs.io/en/latest/)

A high-performance, async-native WebTransport implementation for Python.

## Features

- Full WebTransport protocol implementation (bidirectional streams, unidirectional streams, datagrams).
- High-performance async client and server application frameworks.
- Production-ready components for connection pooling, management, and load balancing.
- Comprehensive monitoring and debugging capabilities.
- Type-safe API with complete type annotations.
- Extensive test coverage (unit, integration, end-to-end).

## Installation

```bash
pip install pywebtransport
```

## Quick Start

### Server

```python
# server.py
import asyncio

from pywebtransport import ServerApp, ServerConfig, WebTransportSession, WebTransportStream
from pywebtransport.exceptions import ConnectionError, SessionError
from pywebtransport.utils import generate_self_signed_cert

generate_self_signed_cert("localhost")

app = ServerApp(
    config=ServerConfig.create(
        certfile="localhost.crt",
        keyfile="localhost.key",
    )
)


async def handle_datagrams(session: WebTransportSession) -> None:
    try:
        datagrams = await session.datagrams
        while True:
            data = await datagrams.receive()
            await datagrams.send(b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        pass


async def handle_streams(session: WebTransportSession) -> None:
    try:
        async for stream in session.incoming_streams():
            if isinstance(stream, WebTransportStream):
                data = await stream.read_all()
                await stream.write_all(b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        pass


@app.route("/")
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
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE)

    async with WebTransportClient.create(config=config) as client:
        session = await client.connect("https://127.0.0.1:4433/")

        print("Connection established. Testing datagrams...")
        datagrams = await session.datagrams
        await datagrams.send(b"Hello, Datagram!")
        response = await datagrams.receive()
        print(f"Datagram echo: {response!r}\n")

        print("Testing streams...")
        stream = await session.create_bidirectional_stream()
        await stream.write_all(b"Hello, Stream!")
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

- **[Installation Guide](docs/installation.md)** - Setup and installation
- **[Quick Start](docs/quickstart.md)** - 5-minute tutorial
- **[API Reference](docs/api-reference/)** - Complete API documentation

## Requirements

- Python 3.11+
- asyncio support
- TLS 1.3

**Dependencies:**

- aioquic >= 1.2.0
- cryptography >= 45.0.4

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details.

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

- [aioquic](https://github.com/aiortc/aioquic) for QUIC protocol implementation
- [WebTransport Working Group](https://datatracker.ietf.org/wg/webtrans/) for protocol standardization

## Support

- **Issues**: [GitHub Issues](https://github.com/lemonsterfy/pywebtransport/issues)
- **Discussions**: [GitHub Discussions](https://github.com/lemonsterfy/pywebtransport/discussions)
- **Email**: lemonsterfy@gmail.com
