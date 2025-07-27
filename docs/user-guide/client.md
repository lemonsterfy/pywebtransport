# Client Development Guide

This guide covers the essential patterns for building a WebTransport client with PyWebTransport. You will learn how to connect to a server, manage sessions, and communicate using streams and datagrams.

## Core Concepts

Client-side development revolves around two main objects:

1.  **`WebTransportClient`**: The main object for managing configurations and initiating connections. Its lifecycle should be managed with an `async with` block to ensure resources are properly cleaned up.
2.  **`WebTransportSession`**: Represents a single connection to a server. It is created by `client.connect()` and should also be managed with `async with`. This object is your gateway to creating streams and sending datagrams.

## 1. Establishing a Connection

The most fundamental task is to connect to a server. This involves creating a client, defining a configuration, and establishing a session.

For development, you'll often connect to a server using a self-signed certificate. To make this work, you must configure the client to skip certificate verification.

```python
# basic_client.py
import asyncio
import ssl

from pywebtransport import ClientConfig, WebTransportClient
from pywebtransport.exceptions import ConnectionError, TimeoutError


async def main() -> None:
    # 1. Create a client configuration
    # For self-signed certs, we must disable certificate verification.
    # In production, you should use ssl.CERT_REQUIRED.
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE)

    print("Attempting to connect to https://127.0.0.1:4433...")

    try:
        # 2. Create the client and manage its lifecycle with async with
        async with WebTransportClient.create(config=config) as client:

            # 3. Connect to the server and manage the session with async with
            async with await client.connect("https://127.0.0.1:4433/") as session:
                print(f"Connection successful! Session ID: {session.session_id}")

                # The session is now ready for communication.
                # We will add communication logic in the next steps.

                print("Closing session.")

        print("Client resources cleaned up.")

    except ConnectionError as e:
        print(f"Connection failed: {e}")
    except TimeoutError:
        print("Connection timed out.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())

```

This example demonstrates the robust "double `async with`" pattern, which guarantees that both the session and the client's underlying resources are always closed correctly, even if errors occur.

## 2. Communicating with Streams and Datagrams

Once a session is established, you can use it to send and receive data.

- **Streams** are reliable and ordered, perfect for requests, responses, or file transfers.
- **Datagrams** are fast and unreliable, ideal for real-time updates or game state synchronization.

The following example connects to the echo server from the Server Development Guide.

```python
# echo_client.py
import asyncio
import ssl

from pywebtransport import ClientConfig, WebTransportClient
from pywebtransport.exceptions import ConnectionError


async def main() -> None:
    config = ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=10.0,  # Connection timeout in seconds
        read_timeout=10.0,  # Stream read timeout
    )

    try:
        async with WebTransportClient.create(config=config) as client:
            async with await client.connect("https://127.0.0.1:4433/") as session:
                print("Connection established.")

                # --- Datagram Example ---
                print("\nTesting Datagrams:")
                datagram_message = b"Hello, Datagrams!"
                await session.datagrams.send(datagram_message)
                print(f"  Sent: {datagram_message!r}")
                response = await session.datagrams.receive()
                print(f"  Received: {response!r}")

                # --- Bidirectional Stream Example ---
                print("\nTesting Bidirectional Stream:")
                # Create a new bidirectional stream
                stream = await session.create_bidirectional_stream()

                stream_message = b"Hello, Streams!"
                # Write data to the stream and close our side of it
                await stream.write_all(stream_message)
                print(f"  Sent: {stream_message!r}")

                # Read the echoed data from the server
                response = await stream.read_all()
                print(f"  Received: {response!r}")

    except ConnectionError as e:
        print(f"Connection failed: {e}")
    except asyncio.TimeoutError:
        print("An operation timed out.")


if __name__ == "__main__":
    asyncio.run(main())

```

### Key Communication Patterns

- **`session.datagrams.send()` / `receive()`**: For sending and receiving single, unreliable packets.
- **`session.create_bidirectional_stream()`**: Creates a stream for two-way, reliable communication.
- **`session.create_unidirectional_stream()`**: Creates a stream for one-way, reliable communication (client-to-server).
- **`stream.write_all()`**: Writes a complete message to a stream and closes the sending direction. This is a convenient shortcut for `stream.write()` followed by `stream.close_write()`.
- **`stream.read_all()`**: Reads all data from a stream until the peer closes its sending direction.

## 3. Handling Errors

Network applications must be resilient to errors. The most common exceptions you should handle are:

- **`ConnectionError`**: Raised when the client cannot establish a connection to the server (e.g., server is down, firewall blocks the port).
- **`TimeoutError`** (from `asyncio`): Raised if an operation (like connecting or reading) takes longer than the configured timeout.
- **`SessionError`**: A general error related to a session that is already connected.

Here is a robust pattern for handling these exceptions:

```python
# error_handling_client.py
import asyncio
import ssl

from pywebtransport import ClientConfig, WebTransportClient
from pywebtransport.exceptions import ConnectionError, SessionError


async def main() -> None:
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=5.0)

    try:
        async with WebTransportClient.create(config=config) as client:
            # Intentionally connect to a non-existent port to trigger an error
            async with await client.connect("https://127.0.0.1:9999") as _:
                ...  # This code will not be reached

    except ConnectionError as e:
        # This block will be executed
        print(f"Caught expected error: Connection failed. Details: {e}")
    except asyncio.TimeoutError:
        print("Caught expected error: Connection timed out.")
    except SessionError as e:
        print(f"A session-level error occurred: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())

```

By wrapping your connection and communication logic in a `try...except` block, you can build a client that responds gracefully to network failures.

## 4. Advanced Client Patterns

Beyond simple request-response, you can build fully interactive applications. These patterns show how to handle concurrent tasks and structure your data for more complex scenarios.

### Pattern 1: Building an Interactive Client (Chat)

A real-world client often needs to do two things at once:

1.  Listen for incoming messages from the server.
2.  Listen for input from the user (e.g., keyboard).

This requires running two tasks concurrently. This example builds a client that can connect to the chat server from the advanced server guide.

```python
# interactive_chat_client.py
import asyncio
import ssl
import sys

from pywebtransport import ClientConfig, WebTransportClient, WebTransportSession
from pywebtransport.exceptions import ConnectionError


# This function will run in a separate thread to handle blocking I/O (keyboard input).
def get_user_input(loop: asyncio.AbstractEventLoop, session: WebTransportSession) -> None:
    """Reads from stdin and sends messages to the server."""
    while True:
        message = sys.stdin.readline().strip()
        if message.lower() == "/quit":
            print("Quitting...")
            # We use call_soon_threadsafe because we are in a separate thread.
            loop.call_soon_threadsafe(session.close)
            break
        # We use call_soon_threadsafe because we are in a separate thread.
        loop.call_soon_threadsafe(asyncio.create_task, session.datagrams.send(message.encode()))


async def receive_messages(session: WebTransportSession) -> None:
    """Receives messages from the server and prints them."""
    try:
        while True:
            message = await session.datagrams.receive()
            # We add a carriage return to not overwrite the user's input line.
            print(f"\rReceived: {message.decode()}\n> ", end="")
    except ConnectionError:
        print("\rConnection closed.")


async def main() -> None:
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE)

    try:
        async with WebTransportClient.create(config=config) as client:
            async with await client.connect("https://127.0.0.1:4433/chat") as session:
                print("Connected to chat server. Type messages and press Enter. Type /quit to exit.")
                print("> ", end="")
                sys.stdout.flush()

                loop = asyncio.get_running_loop()

                # Start the blocking input reader in a separate thread
                input_task = loop.run_in_executor(None, get_user_input, loop, session)

                # Start the message receiver task
                receive_task = asyncio.create_task(receive_messages(session))

                # Wait for either task to complete
                done, pending = await asyncio.wait(
                    [input_task, receive_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Clean up pending tasks
                for task in pending:
                    task.cancel()

    except ConnectionError as e:
        print(f"Connection failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

```

### Pattern 2: Implementing an Application Protocol with JSON

For more robust applications, sending raw bytes is not enough. You should define an application-level protocol using a structured format like JSON. This allows you to send different types of messages and include metadata.

Let's modify the chat client to send JSON objects.

```python
# json_chat_client.py
import asyncio
import json
import ssl
import sys

from pywebtransport import ClientConfig, WebTransportClient, WebTransportSession
from pywebtransport.exceptions import ConnectionError

USERNAME = f"User_{asyncio.run(asyncio.sleep(0, result=__import__('random').randint(100, 999)))}"


def get_json_input(loop: asyncio.AbstractEventLoop, session: WebTransportSession) -> None:
    """Reads user input and sends structured JSON messages."""
    while True:
        message_text = sys.stdin.readline().strip()
        if message_text.lower() == "/quit":
            loop.call_soon_threadsafe(asyncio.create_task, session.close())
            break

        # Construct a JSON message
        message = {
            "type": "chat_message",
            "payload": {
                "username": USERNAME,
                "text": message_text,
            },
        }

        # Send the JSON string as bytes
        loop.call_soon_threadsafe(asyncio.create_task, session.datagrams.send(json.dumps(message).encode()))


async def receive_json_messages(session: WebTransportSession) -> None:
    """Receives JSON messages and formats them for display."""
    try:
        while True:
            data = await session.datagrams.receive()
            try:
                message = json.loads(data)
                # Pretty-print the message based on its content
                payload = message.get("payload", {})
                username = payload.get("username", "Unknown")
                text = payload.get("text", "")
                print(f"\r[{username}]: {text}\n> ", end="")
            except json.JSONDecodeError:
                print(f"\rReceived malformed data: {data!r}\n> ", end="")
    except ConnectionError:
        print("\rConnection closed.")


async def main() -> None:
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE)

    try:
        async with WebTransportClient.create(config=config) as client:
            # A corresponding server would need to be running to handle the /json-chat path
            async with await client.connect("https://127.0.0.1:4433/json-chat") as session:
                print(f"Connected as {USERNAME}. Start chatting!")
                print("> ", end="")
                sys.stdout.flush()

                # Announce entry by sending a login message
                login_message = json.dumps({"type": "user_login", "payload": {"username": USERNAME}})
                await session.datagrams.send(login_message.encode())

                loop = asyncio.get_running_loop()
                input_task = loop.run_in_executor(None, get_json_input, loop, session)
                receive_task = asyncio.create_task(receive_json_messages(session))

                done, pending = await asyncio.wait([input_task, receive_task], return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()

    except ConnectionError as e:
        print(f"Connection failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())

```

## Next Steps

- **[Server Guide](server.md)**: Learn how to build the server-side of your application.
- **[API Reference](../api-reference/client.md)**: Explore the full `WebTransportClient` and `ClientConfig` API.
