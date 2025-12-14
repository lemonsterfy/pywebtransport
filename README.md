<div align="center">
  <img
    src="https://raw.githubusercontent.com/lemonsterfy/pywebtransport/main/docs/assets/favicon.svg"
    alt="PyWebTransport Icon"
    width="100"
  />

# PyWebTransport

_An async-native WebTransport stack for Python_

<br/>

[![PyPI version](https://badge.fury.io/py/pywebtransport.svg)](https://pypi.org/project/pywebtransport/)
[![Python Version](https://img.shields.io/pypi/pyversions/pywebtransport)](https://pypi.org/project/pywebtransport/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![CI](https://github.com/lemonsterfy/pywebtransport/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/lemonsterfy/pywebtransport/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/lemonsterfy/pywebtransport/branch/main/graph/badge.svg)](https://codecov.io/gh/lemonsterfy/pywebtransport)
[![Docs](https://app.readthedocs.org/projects/pywebtransport/badge/?version=latest)](https://docs.pywebtransport.org/)

</div>

## Features

- **Pure Async**: Built entirely on `asyncio` for high-concurrency, non-blocking I/O operations.
- **Event Architecture**: Powered by a Sans-I/O unified state machine and a strictly typed `EventEmitter`.
- **Zero-Copy I/O**: End-to-end support for `memoryview` and buffer protocols to minimize data copying overhead.
- **Structured Messaging**: Transmission of typed Python objects via pluggable serializers (`JSON`, `MsgPack`, `Protobuf`).
- **High-Level Abstractions**: `ServerApp` with routing and middleware, plus `WebTransportClient` utilities for fleet management.
- **Protocol Completeness**: Implementation of bidirectional streams, unidirectional streams, and unreliable datagrams.
- **Resource Safety**: Async context managers for automatic connection, session, and stream lifecycle management.
- **Type-Safe & Tested**: Fully type-annotated API with comprehensive unit, integration, end-to-end, and benchmark coverage.

## Installation

```bash
pip install pywebtransport
```

## Quick Start

### Server

```python
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
        if isinstance(event.data, dict):
            payload = event.data.get("data")
            if payload:
                await session.send_datagram(data=b"ECHO: " + payload)

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

## Interoperability

- **[Public Endpoint](https://interop.pywebtransport.org)**: `https://interop.pywebtransport.org`
  - **/echo**: Bidirectional stream and datagram reflection.
  - **/status**: Global server health and aggregate metrics.
  - **/stats**: Current session statistics and negotiated parameters.

## Documentation

- **[API Reference](docs/api-reference/index.md)** - Explore the complete API documentation.

## Requirements

- Python 3.12+
- TLS 1.3

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) for details on the development setup, testing, and pull request process.

## Sponsors

<div>
  <a href="https://www.fastly.com/" target="_blank" rel="noopener noreferrer">
    <img
      src="https://upload.wikimedia.org/wikipedia/commons/8/8a/Fastly_logo.svg"
      alt="Fastly"
      width="100"
    />
  </a>
</div>

## Acknowledgments

- [aioquic](https://github.com/aiortc/aioquic) for the underlying QUIC protocol implementation.
- [WebTransport Working Group](https://datatracker.ietf.org/wg/webtrans/) for defining and standardizing the WebTransport protocol.

## Support

- **Issues**: [GitHub Issues](https://github.com/lemonsterfy/pywebtransport/issues)
- **Discussions**: [GitHub Discussions](https://github.com/lemonsterfy/pywebtransport/discussions)
- **Email**: lemonsterfy@gmail.com

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
