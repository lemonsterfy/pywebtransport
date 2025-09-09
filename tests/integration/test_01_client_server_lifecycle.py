"""
Integration tests for the basic client-server connection lifecycle.
"""

import asyncio

import pytest

from pywebtransport import ClientError, ServerApp, SessionState, WebTransportClient, WebTransportSession

pytestmark = pytest.mark.asyncio


async def test_successful_connection_and_session(
    server_app: ServerApp, server: tuple[str, int], client: WebTransportClient
) -> None:
    """Verify a client can connect, establish a session, and then close it."""
    host, port = server
    url = f"https://{host}:{port}/"
    handler_called = asyncio.Event()

    @server_app.route(path="/")
    async def basic_handler(session: WebTransportSession) -> None:
        handler_called.set()
        try:
            await session.wait_closed()
        except asyncio.CancelledError:
            pass

    session = None
    try:
        session = await client.connect(url=url)
        assert session.is_ready
        await asyncio.wait_for(handler_called.wait(), timeout=1.0)
    finally:
        if session and not session.is_closed:
            await session.close()


async def test_client_initiated_close(
    server_app: ServerApp, server: tuple[str, int], client: WebTransportClient
) -> None:
    """Verify that when a client closes a session, its local state becomes closed."""
    host, port = server
    url = f"https://{host}:{port}/"
    server_entered = asyncio.Event()

    @server_app.route(path="/")
    async def simple_handler(session: WebTransportSession) -> None:
        server_entered.set()
        try:
            await session.wait_closed()
        except asyncio.CancelledError:
            pass

    session = await client.connect(url=url)
    assert session.is_ready
    await asyncio.wait_for(server_entered.wait(), timeout=1.0)

    await session.close(reason="Client-initiated close")

    await asyncio.wait_for(session.wait_closed(), timeout=1.0)
    assert session.is_closed is True


async def test_server_initiated_close(
    server_app: ServerApp, server: tuple[str, int], client: WebTransportClient
) -> None:
    """Verify a client correctly handles a server-initiated close."""
    host, port = server
    url = f"https://{host}:{port}/close-me"

    @server_app.route(path="/close-me")
    async def immediate_close_handler(session: WebTransportSession) -> None:
        await session.close(reason="Server closed immediately.")

    session = await client.connect(url=url)
    assert session.is_ready

    try:
        await asyncio.wait_for(session.wait_closed(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("session.wait_closed() timed out waiting for server-initiated close.")

    assert session.is_closed is True
    assert session.state == SessionState.CLOSED


async def test_connection_to_non_existent_route_fails(
    server: tuple[str, int], client: WebTransportClient, server_app: ServerApp
) -> None:
    """Verify that connecting to a non-existent route fails with a ClientError."""
    host, port = server
    url = f"https://{host}:{port}/nonexistent"

    with pytest.raises(ClientError) as exc_info:
        await client.connect(url=url)

    error_message = str(exc_info.value).lower()
    assert "404" in error_message or "route not found" in error_message or "timeout" in error_message
