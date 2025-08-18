"""
Integration tests for high-level ServerApp features.
"""

import asyncio

import pytest

from pywebtransport import ClientError, Headers, ServerApp, WebTransportClient, WebTransportSession, WebTransportStream

pytestmark = pytest.mark.asyncio


async def test_routing_to_path_one(server: tuple[str, int], client: WebTransportClient, server_app: ServerApp) -> None:
    """Verify the ServerApp routes a connection to the correct handler for the first path."""
    host, port = server
    handler_one_called = asyncio.Event()
    handler_two_called = asyncio.Event()

    @server_app.route("/path_one")
    async def handler_one(session: WebTransportSession) -> None:
        handler_one_called.set()
        await session.close()

    @server_app.route("/path_two")
    async def handler_two(session: WebTransportSession) -> None:
        handler_two_called.set()
        await session.close()

    async with await client.connect(f"https://{host}:{port}/path_one"):
        await asyncio.wait_for(handler_one_called.wait(), timeout=2.0)

    assert handler_one_called.is_set()
    assert not handler_two_called.is_set()


async def test_routing_to_path_two(server: tuple[str, int], client: WebTransportClient, server_app: ServerApp) -> None:
    """Verify the ServerApp routes a connection to the correct handler for the second path."""
    host, port = server
    handler_one_called = asyncio.Event()
    handler_two_called = asyncio.Event()

    @server_app.route("/path_one")
    async def handler_one(session: WebTransportSession) -> None:
        handler_one_called.set()
        await session.close()

    @server_app.route("/path_two")
    async def handler_two(session: WebTransportSession) -> None:
        handler_two_called.set()
        await session.close()

    async with await client.connect(f"https://{host}:{port}/path_two"):
        await asyncio.wait_for(handler_two_called.wait(), timeout=2.0)

    assert handler_two_called.is_set()
    assert not handler_one_called.is_set()


async def test_pattern_routing_with_params(
    server: tuple[str, int], client: WebTransportClient, server_app: ServerApp
) -> None:
    """Verify that pattern-based routes can capture path parameters."""
    host, port = server

    @server_app.pattern_route(r"/items/([a-zA-Z0-9-]+)")
    async def item_handler(session: WebTransportSession) -> None:
        try:
            stream = await anext(session.incoming_streams())
            if isinstance(stream, WebTransportStream):
                _ = await stream.read_all()
                path_params = getattr(session, "path_params", ())
                item_id = path_params[0] if path_params else "not-found"
                response_message = f"Accessed item: {item_id}".encode()
                await stream.write_all(response_message)
        except asyncio.CancelledError:
            pass

    async with await client.connect(f"https://{host}:{port}/items/123-abc") as session:
        stream = await session.create_bidirectional_stream()
        await stream.write_all(b"get item data")
        response = await stream.read_all()
        assert response == b"Accessed item: 123-abc"


async def test_middleware_accepts_session(
    server: tuple[str, int], client: WebTransportClient, server_app: ServerApp
) -> None:
    """Verify that a middleware can allow a session to proceed."""
    host, port = server
    handler_was_reached = asyncio.Event()

    async def auth_middleware(session: WebTransportSession) -> bool:
        return session.headers.get("x-auth-token") == "valid-token"

    server_app.add_middleware(auth_middleware)

    @server_app.route("/protected")
    async def protected_handler(session: WebTransportSession) -> None:
        handler_was_reached.set()
        await session.close()

    headers: Headers = {"x-auth-token": "valid-token"}
    async with await client.connect(f"https://{host}:{port}/protected", headers=headers):
        await asyncio.wait_for(handler_was_reached.wait(), timeout=2.0)


async def test_middleware_rejects_session(
    server: tuple[str, int], client: WebTransportClient, server_app: ServerApp
) -> None:
    """Verify that a middleware can reject a session."""
    host, port = server

    async def auth_middleware(session: WebTransportSession) -> bool:
        return session.headers.get("x-auth-token") == "valid-token"

    server_app.add_middleware(auth_middleware)

    @server_app.route("/protected")
    async def protected_handler(session: WebTransportSession) -> None:
        pytest.fail("Rejected session reached the route handler.")

    headers: Headers = {"x-auth-token": "invalid-token"}
    with pytest.raises(ClientError) as exc_info:
        await client.connect(f"https://{host}:{port}/protected", headers=headers)

    error_message = str(exc_info.value).lower()
    assert "403" in error_message or "rejected by middleware" in error_message or "timeout" in error_message
