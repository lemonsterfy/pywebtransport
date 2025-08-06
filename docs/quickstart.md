# Quick Start

Get up and running with PyWebTransport in 5 minutes. This guide covers the essential steps to establish client-server communication using the WebTransport protocol.

## Prerequisites

- Python 3.11 or higher.
- `pip` for installing packages.

## 1. Installation

First, install PyWebTransport from PyPI:

```bash
pip install pywebtransport
```

## 2. Create the Server

The server will listen for connections and echo back any data it receives.

Create a file named `server.py`:

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

## 3. Create the Client

The client will connect to the server, send a message via datagrams and a stream, and print the echoed responses.

Create a file named `client.py`:

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

## 4. Run the Example

First, start the server in your terminal:

```bash
python server.py
```

The server will generate `localhost.crt` and `localhost.key` files and start listening.

In a separate terminal, run the client:

```bash
python client.py
```

You should see output confirming the echoed messages from the server.

## Core Concepts Revisited

### Sessions

A `WebTransportSession` is created by a `WebTransportClient` and represents a single connection. The `WebTransportClient` must be used as an async context manager.

```python
# Client-side session
config = ClientConfig.create(verify_mode=ssl.CERT_NONE)
async with WebTransportClient.create(config=config) as client:
    session = await client.connect(url)
    # Use the session object
    print(f"Session to {session.path} is ready.")
    await session.close()
```

### Datagrams

Send and receive unreliable, out-of-order messages.

```python
# Get the datagrams interface (must be awaited on first access)
datagrams = await session.datagrams

# Send a datagram
await datagrams.send(b"unreliable message")

# Receive a datagram
data = await datagrams.receive()
```

### Streams

Provide reliable, ordered communication channels.

```python
# Create a bidirectional stream
stream = await session.create_bidirectional_stream()

# Write data (and close the write-end)
await stream.write_all(b"reliable message")

# Read data until the stream is closed by the peer
response = await stream.read_all()
```

## Next Steps

Now that you have a basic connection working, explore more advanced topics:

- **[Installation Guide](installation.md)** - In-depth setup and installation guide.
- **[Client API](api-reference/client.md)** - Detailed client API reference and usage patterns.
- **[Server API](api-reference/server.md)** - Detailed server API reference and usage patterns.
- **[API Reference](api-reference/index.md)** - Complete API documentation
