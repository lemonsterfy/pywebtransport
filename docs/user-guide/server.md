# Server Development Guide

This guide provides a comprehensive overview of building WebTransport servers using PyWebTransport's high-level `ServerApp` framework.

## Core Concepts

The server framework is built around three main components:

1.  **`ServerApp`**: The main application object that manages the server lifecycle, routing, and configuration.
2.  **`@app.route(path)`**: A decorator to register an asynchronous function as a handler for a specific URL path.
3.  **`WebTransportSession`**: An object passed to your handler, representing a single client connection. It's your primary interface for sending and receiving data.

## 1. Creating a Basic Server

A minimal PyWebTransport server requires three things:

1.  An instance of `ServerApp`.
2.  A `ServerConfig` object with valid TLS certificates.
3.  At least one route handler.

For local development, you can easily generate a self-signed certificate.

```python
# basic_server.py
from pywebtransport import ServerApp, ServerConfig, WebTransportSession
from pywebtransport.utils import generate_self_signed_cert

# Generate a certificate and key for localhost
# Note: In production, use a certificate from a trusted authority.
generate_self_signed_cert("localhost")

# Create a server configuration
config = ServerConfig.create(
    certfile="localhost.crt",
    keyfile="localhost.key",
)

# Initialize the ServerApp
app = ServerApp(config=config)


@app.route("/")
async def handle_root_session(session: WebTransportSession) -> None:
    """
    This handler is called for each new client connecting to '/'.
    """
    if session.connection:
        print(f"Session received from {session.connection.remote_address} for path {session.path}")
    else:
        print(f"Session received for path {session.path}, but connection details are unavailable.")

    # Keep the session alive until the client closes it
    try:
        await session.wait_closed()
    finally:
        print(f"Session {session.session_id} closed.")


if __name__ == "__main__":
    # Run the server on localhost, port 4433
    app.run(host="127.0.0.1", port=4433)

```

To run this server, execute `python basic_server.py`. It will start listening for connections on `https://127.0.0.1:4433`.

## 2. Handling Streams and Datagrams

Your route handler's main purpose is to manage communication with the client using streams and datagrams.

### Echo Server Example

Let's expand the previous example into a full echo server. This is a common pattern for testing and demonstrates how to handle both reliable streams and unreliable datagrams.

```python
# echo_server.py
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
    """A task to listen for incoming datagrams and echo them back."""
    print("Datagram handler started.")
    try:
        while True:
            data = await session.datagrams.receive()
            print(f"Received datagram: {data!r}")
            await session.datagrams.send(b"ECHO: " + data)
    except (ConnectionError, SessionError, asyncio.CancelledError):
        # This block is executed when the session is closed.
        print("Datagram handler stopped.")


async def handle_streams(session: WebTransportSession) -> None:
    """A task to listen for incoming streams and echo their data."""
    print("Stream handler started.")
    try:
        # session.incoming_streams() is an async iterator
        async for stream in session.incoming_streams():
            print(f"Received new stream: {stream.stream_id}")
            if isinstance(stream, WebTransportStream):
                # Read all data from the stream
                data = await stream.read_all()
                print(f"Received stream data: {data!r}")
                # Echo the data back on the same stream
                await stream.write_all(b"ECHO: " + data)
            print(f"Stream {stream.stream_id} finished.")
    except (ConnectionError, SessionError, asyncio.CancelledError):
        print("Stream handler stopped.")


@app.route("/")
async def echo_handler(session: WebTransportSession) -> None:
    """
    The main handler runs two tasks concurrently: one for datagrams
    and one for streams.
    """
    if session.connection:
        print(f"Session received from {session.connection.remote_address}")
    else:
        print("Session received, but connection details are unavailable.")

    # Create and run tasks for handling datagrams and streams
    datagram_task = asyncio.create_task(handle_datagrams(session))
    stream_task = asyncio.create_task(handle_streams(session))

    try:
        # Wait until the session is closed by the client or a network error.
        await session.wait_closed()
    finally:
        # Clean up the tasks when the session is over.
        print(f"Session {session.session_id} closing. Cleaning up tasks.")
        datagram_task.cancel()
        stream_task.cancel()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4433)

```

This example demonstrates a key pattern: running long-lived tasks to process incoming data for the duration of a session.

## 3. Routing

You can define handlers for different URL paths. The `ServerApp` will match the path from the client's connection URL and invoke the corresponding handler.

```python
# routing_server.py
from pywebtransport import ServerApp, ServerConfig, WebTransportSession
from pywebtransport.utils import generate_self_signed_cert

generate_self_signed_cert("localhost")
config = ServerConfig.create(certfile="localhost.crt", keyfile="localhost.key")
app = ServerApp(config=config)


@app.route("/")
async def home(session: WebTransportSession) -> None:
    stream = await session.create_unidirectional_stream()
    await stream.write_all(b"Welcome to the home page!")
    await session.close()  # Close session after sending the message


@app.route("/api/v1/status")
async def api_status(session: WebTransportSession) -> None:
    stream = await session.create_unidirectional_stream()
    await stream.write_all(b'{"status": "ok"}')
    await session.close()


# Note: The server will automatically reject connections for paths
# that do not have a registered route.

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4433)

```

## 4. Application Lifecycle (Startup and Shutdown)

For more complex applications, you may need to initialize resources (like database connections) on startup and clean them up on shutdown. Use the `@app.on_startup` and `@app.on_shutdown` decorators for this.

```python
# lifecycle_server.py
import asyncio

from pywebtransport import ServerApp, ServerConfig, WebTransportSession
from pywebtransport.utils import generate_self_signed_cert


# A dummy database connection pool
class DatabasePool:
    async def connect(self) -> None:
        print("Database pool connected.")

    async def close(self) -> None:
        print("Database pool closed.")


db_pool = DatabasePool()

generate_self_signed_cert("localhost")
config = ServerConfig.create(certfile="localhost.crt", keyfile="localhost.key")
app = ServerApp(config=config)


@app.on_startup
async def startup_handler() -> None:
    """This is called once when the server starts."""
    print("Server is starting up...")
    await db_pool.connect()


@app.on_shutdown
async def shutdown_handler() -> None:
    """This is called once when the server shuts down."""
    print("Server is shutting down...")
    await db_pool.close()


@app.route("/")
async def handler(session: WebTransportSession) -> None:
    # You can now assume db_pool is connected
    await session.close(code=0, reason="Work done.")


if __name__ == "__main__":
    # You can also run the server manually for more control
    async def main() -> None:
        async with app:
            await app.serve(host="127.0.0.1", port=4433)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped by user.")

```

This approach gives you fine-grained control over the application's lifecycle, which is essential for managing resources in a production environment.

## 5. Advanced Server Patterns

Once you are comfortable with the basics, you can build more complex applications by managing state across multiple sessions and handling work concurrently.

### Pattern 1: State Management and Broadcasting (Chat Room)

A common use case for WebTransport is a multi-user chat application. This requires the server to:

1.  Maintain a set of all active client sessions.
2.  Receive a message from one client.
3.  Broadcast that message to all other connected clients.

This pattern demonstrates how to manage shared state between different sessions.

```python
# chat_server.py
import asyncio
from typing import Set

from pywebtransport import ServerApp, ServerConfig, WebTransportSession
from pywebtransport.exceptions import ConnectionError, SessionError
from pywebtransport.utils import generate_self_signed_cert

# --- Shared State ---
# This set will store all active session objects.
# In a real application, you might use a more complex structure
# to store user information alongside the session.
ACTIVE_SESSIONS: Set[WebTransportSession] = set()


def add_session(session: WebTransportSession) -> None:
    """Adds a new session to our shared state."""
    print(f"Session {session.session_id} joined.")
    ACTIVE_SESSIONS.add(session)


def remove_session(session: WebTransportSession) -> None:
    """Removes a session from our shared state."""
    print(f"Session {session.session_id} left.")
    ACTIVE_SESSIONS.discard(session)


async def broadcast_message(sender_session: WebTransportSession, message: str) -> None:
    """Sends a message to all connected clients except the sender."""
    print(f"Broadcasting from {sender_session.session_id}: {message}")

    # We use asyncio.gather to send messages concurrently.
    # A simple loop would also work but would be slower.
    await asyncio.gather(
        *(session.datagrams.send(message.encode()) for session in ACTIVE_SESSIONS if session != sender_session),
        return_exceptions=True,  # Don't let one failed send stop others
    )


# --- Server Setup ---
generate_self_signed_cert("localhost")
app = ServerApp(
    config=ServerConfig.create(
        certfile="localhost.crt",
        keyfile="localhost.key",
    )
)


@app.route("/chat")
async def chat_handler(session: WebTransportSession) -> None:
    """
    The handler for each client connecting to the chat.
    """
    add_session(session)
    try:
        # Listen for incoming messages in a loop
        while True:
            try:
                # We use datagrams for low-latency chat messages.
                data = await session.datagrams.receive()
                # In a real app, you'd parse this as JSON.
                await broadcast_message(session, data.decode())
            except (ConnectionError, SessionError):
                # The client disconnected.
                break
    finally:
        # No matter how the session ends, remove it from the active set.
        remove_session(session)


if __name__ == "__main__":
    print("Chat server running at https://127.0.0.1:4433/chat")
    app.run(host="127.0.0.1", port=4433)

```

### Pattern 2: Concurrent Stream Processing

If a client needs to perform multiple reliable operations at once (like uploading several files), it may open multiple streams concurrently. Your server can process these in parallel to improve throughput.

```python
# concurrent_streams_server.py
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


async def process_single_stream(stream: WebTransportStream) -> None:
    """
    This coroutine handles the logic for one individual stream.
    """
    try:
        print(f"Task started for stream {stream.stream_id}.")
        data = await stream.read_all()

        # Simulate some processing work (e.g., saving a file)
        await asyncio.sleep(1)

        response = f"Processed {len(data)} bytes from stream {stream.stream_id}."
        await stream.write_all(response.encode())
        print(f"Task finished for stream {stream.stream_id}.")
    except Exception as e:
        print(f"Error processing stream {stream.stream_id}: {e}")


@app.route("/upload")
async def upload_handler(session: WebTransportSession) -> None:
    """
    This handler accepts multiple incoming streams and creates a
    separate task to process each one concurrently.
    """
    print(f"Session {session.session_id} ready to receive concurrent uploads.")
    try:
        tasks = []
        # session.incoming_streams() is an async iterator
        async for stream in session.incoming_streams():
            if isinstance(stream, WebTransportStream):
                # Don't await the processing here. Instead, create a task
                # to run it in the background.
                task = asyncio.create_task(process_single_stream(stream))
                tasks.append(task)

        # Wait for all the processing tasks to complete.
        if tasks:
            print(f"Waiting for {len(tasks)} upload tasks to complete...")
            await asyncio.gather(*tasks)
            print("All upload tasks finished.")

    except (ConnectionError, SessionError):
        pass  # Session closed
    finally:
        print(f"Session {session.session_id} closed.")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4433)

```

## Next Steps

- **[Client Guide](client.md)**: Learn how to build a client to connect to your server.
- **[API Reference](../api-reference/server.md)**: Explore the full `ServerApp` and `ServerConfig` API.
