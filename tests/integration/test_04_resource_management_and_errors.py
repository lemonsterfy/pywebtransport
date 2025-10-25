"""Integration tests for resource management and error handling."""

import asyncio

import pytest

from pywebtransport import (
    ClientConfig,
    ClientError,
    ConnectionError,
    ServerApp,
    StreamError,
    WebTransportClient,
    WebTransportSession,
)

pytestmark = pytest.mark.asyncio


async def idle_handler(session: WebTransportSession) -> None:
    try:
        await session.wait_closed()
    except asyncio.CancelledError:
        pass


@pytest.mark.parametrize(
    "server_app",
    [{"max_connections": 1}],
    indirect=True,
)
async def test_max_connections_limit_rejection(
    server_app: ServerApp, server: tuple[str, int], client_config: ClientConfig
) -> None:
    server_app.route(path="/")(idle_handler)
    host, port = server
    url = f"https://{host}:{port}/"

    async with WebTransportClient(config=client_config) as client1:
        async with await client1.connect(url=url) as session1:
            assert session1.is_ready, "First client should connect successfully."

            async with WebTransportClient(config=client_config) as client2:
                with pytest.raises((ClientError, ConnectionError, asyncio.TimeoutError)):
                    await client2.connect(url=url)


@pytest.mark.parametrize("server_app", [{"max_streams_per_connection": 2}], indirect=True)
async def test_max_streams_limit(server_app: ServerApp, server: tuple[str, int], client_config: ClientConfig) -> None:
    server_app.route(path="/")(idle_handler)
    host, port = server
    url = f"https://{host}:{port}/"

    client_with_limit_config = client_config.update(max_streams=2)
    async with WebTransportClient(config=client_with_limit_config) as client:
        async with await client.connect(url=url) as session:
            _ = await session.create_bidirectional_stream()
            _ = await session.create_bidirectional_stream()

            with pytest.raises(StreamError, match="stream limit"):
                await session.create_bidirectional_stream()


@pytest.mark.parametrize("server_app", [{"connection_cleanup_interval": 0.1}], indirect=True)
async def test_server_cleans_up_closed_connection(
    server_app: ServerApp, server: tuple[str, int], client_config: ClientConfig
) -> None:
    server_app.route(path="/")(idle_handler)
    host, port = server
    url = f"https://{host}:{port}/"
    connection_manager = server_app.server.connection_manager

    assert len(await connection_manager.get_all_resources()) == 0

    async with WebTransportClient(config=client_config) as client:
        async with await client.connect(url=url) as session:
            assert session.is_ready

            timeout_at = asyncio.get_running_loop().time() + 1.0
            while len(await connection_manager.get_all_resources()) < 1:
                if asyncio.get_running_loop().time() > timeout_at:
                    pytest.fail("Connection was not added to manager in time.")
                await asyncio.sleep(0.05)
            assert len(await connection_manager.get_all_resources()) == 1

    timeout_at = asyncio.get_running_loop().time() + 2.0
    while len(await connection_manager.get_all_resources()) > 0:
        if asyncio.get_running_loop().time() > timeout_at:
            pytest.fail("Server did not clean up closed connection in time.")
        await asyncio.sleep(0.05)

    assert len(await connection_manager.get_all_resources()) == 0
