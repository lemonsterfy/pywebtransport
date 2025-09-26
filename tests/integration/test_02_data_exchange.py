"""Integration tests for data exchange over streams and datagrams."""

import asyncio

import pytest

from pywebtransport import (
    ServerApp,
    WebTransportClient,
    WebTransportReceiveStream,
    WebTransportSession,
    WebTransportStream,
)

pytestmark = pytest.mark.asyncio


async def test_bidirectional_stream_echo(
    server: tuple[str, int], client: WebTransportClient, server_app: ServerApp
) -> None:
    """Verify that data sent on a bidirectional stream is echoed back."""
    host, port = server
    server_handler_finished = asyncio.Event()

    @server_app.route(path="/echo")
    async def echo_handler(session: WebTransportSession) -> None:
        """Echo data on any incoming bidirectional stream."""
        try:
            async for stream in session.incoming_streams():
                if isinstance(stream, WebTransportStream):
                    data = await stream.read_all()
                    await stream.write_all(data=data)
        except asyncio.CancelledError:
            pass
        finally:
            server_handler_finished.set()

    session = await client.connect(url=f"https://{host}:{port}/echo")
    async with session:
        stream = await session.create_bidirectional_stream()
        test_message = b"Hello, bidirectional world!"
        await stream.write_all(data=test_message)
        response = await stream.read_all()
        assert response == test_message

    await asyncio.wait_for(server_handler_finished.wait(), timeout=1.0)


async def test_unidirectional_stream_to_server(
    server: tuple[str, int], client: WebTransportClient, server_app: ServerApp
) -> None:
    """Verify that data sent on a unidirectional stream is received by the server."""
    host, port = server
    data_queue: asyncio.Queue[bytes] = asyncio.Queue()

    @server_app.route(path="/uni")
    async def uni_handler(session: WebTransportSession) -> None:
        """Read from the first incoming unidirectional stream and put data in a queue."""
        try:
            stream = await anext(session.incoming_streams())
            if isinstance(stream, WebTransportReceiveStream):
                data = await stream.read_all()
                await data_queue.put(data)
        except (asyncio.CancelledError, StopAsyncIteration):
            pass

    session = await client.connect(url=f"https://{host}:{port}/uni")
    async with session:
        stream = await session.create_unidirectional_stream()
        test_message = b"Hello, unidirectional world!"
        await stream.write_all(data=test_message)

    received_data = await asyncio.wait_for(data_queue.get(), timeout=2.0)
    assert received_data == test_message


async def test_datagram_echo(server: tuple[str, int], client: WebTransportClient, server_app: ServerApp) -> None:
    """Verify that a datagram sent to the server is echoed back."""
    host, port = server
    server_handler_finished = asyncio.Event()

    @server_app.route(path="/datagram")
    async def datagram_echo_handler(session: WebTransportSession) -> None:
        """Echo any received datagram."""
        datagram_transport = await session.datagrams
        try:
            data = await datagram_transport.receive(timeout=2.0)
            await datagram_transport.send(data=data)
        except asyncio.CancelledError:
            pass
        finally:
            server_handler_finished.set()

    session = await client.connect(url=f"https://{host}:{port}/datagram")
    async with session:
        datagram_transport = await session.datagrams
        test_message = b"Hello, datagram world!"
        await datagram_transport.send(data=test_message)
        response = await datagram_transport.receive(timeout=2.0)
        assert response == test_message

    await asyncio.wait_for(server_handler_finished.wait(), timeout=1.0)


async def test_concurrent_streams_and_datagrams(
    server: tuple[str, int], client: WebTransportClient, server_app: ServerApp
) -> None:
    """Verify that streams and datagrams can be used concurrently."""
    host, port = server
    num_concurrent_ops = 5

    @server_app.route(path="/concurrent")
    async def concurrent_handler(session: WebTransportSession) -> None:
        """Handle both stream and datagram echoes concurrently."""

        async def _handle_streams() -> None:
            try:
                async for stream in session.incoming_streams():
                    if isinstance(stream, WebTransportStream):
                        data = await stream.read_all()
                        await stream.write_all(data=data)
            except asyncio.CancelledError:
                pass

        async def _handle_datagrams() -> None:
            datagram_transport = await session.datagrams
            while not session.is_closed:
                try:
                    data = await datagram_transport.receive(timeout=0.1)
                    await datagram_transport.send(data=data)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

        stream_task = asyncio.create_task(_handle_streams())
        datagram_task = asyncio.create_task(_handle_datagrams())
        try:
            await session.wait_closed()
        finally:
            stream_task.cancel()
            datagram_task.cancel()

    async def _stream_worker(*, session: WebTransportSession, i: int) -> bool:
        stream = await session.create_bidirectional_stream()
        msg = f"Stream worker {i}".encode()
        await stream.write_all(data=msg)
        response = await stream.read_all()
        return response == msg

    async def _datagram_worker(*, session: WebTransportSession, i: int) -> bool:
        datagram_transport = await session.datagrams
        msg = f"Datagram worker {i}".encode()
        await datagram_transport.send(data=msg)
        response = await datagram_transport.receive(timeout=2.0)
        return response == msg

    session = await client.connect(url=f"https://{host}:{port}/concurrent")
    async with session:
        stream_tasks = [_stream_worker(session=session, i=i) for i in range(num_concurrent_ops)]
        datagram_tasks = [_datagram_worker(session=session, i=i) for i in range(num_concurrent_ops)]
        all_tasks = stream_tasks + datagram_tasks
        results = await asyncio.gather(*all_tasks, return_exceptions=True)

    for result in results:
        assert not isinstance(result, Exception), f"A worker failed with an exception: {result}"
        assert result is True, "A worker returned a failure result."
