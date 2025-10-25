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

from pywebtransport import (
    ConnectionError,
    ServerApp,
    ServerConfig,
    SessionError,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.utils import generate_self_signed_cert

# For local development, we can generate a self-signed certificate.
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
    """A background task to handle incoming datagrams."""
    try:
        datagram_transport = await session.create_datagram_transport()
        while True:
            data = await datagram_transport.receive()
            await datagram_transport.send(data=b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        # The session was closed, so we exit the loop.
        pass


async def handle_streams(session: WebTransportSession) -> None:
    """A background task to handle incoming streams."""
    try:
        async for stream in session.incoming_streams():
            # A client's bidirectional stream appears as an incoming stream on the server.
            if isinstance(stream, WebTransportStream):
                data = await stream.read_all()
                await stream.write_all(data=b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        # The session was closed, so we exit the loop.
        pass


@app.route(path="/")
async def echo_handler(session: WebTransportSession) -> None:
    """The main session handler for the / path."""
    # We create two concurrent tasks to handle datagrams and streams simultaneously.
    datagram_task = asyncio.create_task(handle_datagrams(session))
    stream_task = asyncio.create_task(handle_streams(session))
    try:
        # Wait until the session is closed by the client.
        await session.wait_closed()
    finally:
        # Once the session is closed, we ensure our background tasks are cleaned up.
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
    # We disable SSL certificate verification because we are using a self-signed cert.
    # For production, you should use a proper certificate and validation.
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
# Create a client and connect to get a session
config = ClientConfig(verify_mode=ssl.CERT_NONE)

async with WebTransportClient(config=config) as client:
    session = await client.connect(url=url)
    # Use the session object
    print(f"Session to {session.path} is ready.")
    await session.close()
```

### Datagrams

Send and receive unreliable, out-of-order messages.

```python
# Get the datagrams interface (must be awaited on first access)
datagrams = await session.create_datagram_transport()

# Send a datagram
await datagrams.send(data=b"unreliable message")

# Receive a datagram
data = await datagrams.receive()
```

### Streams

Provide reliable, ordered communication channels.

```python
# Create a bidirectional stream
stream = await session.create_bidirectional_stream()

# Write data and close the write-end
await stream.write_all(data=b"reliable message")

# Read all data until the stream is closed by the peer
response = await stream.read_all()
```

## Next Steps

Now that you have a basic connection working, explore more advanced topics:

- **[Installation Guide](installation.md)**: Learn how to install the library.
- **[Server API](api-reference/server.md)**: Build and manage WebTransport servers.
- **[Client API](api-reference/client.md)**: Learn how to create and manage client connections.
- **[API Reference](api-reference/index.md)**: Explore the complete API documentation.
