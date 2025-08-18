"""
Configuration and fixtures for pywebtransport integration tests.
"""

import asyncio
import socket
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio

from pywebtransport import ClientConfig, ServerApp, ServerConfig, WebTransportClient
from pywebtransport.utils import generate_self_signed_cert


def find_free_port() -> int:
    """Find and return an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return cast(int, s.getsockname()[1])


@pytest.fixture(scope="session")
def certificates_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate self-signed certificates in a temporary directory for the session."""
    cert_dir = tmp_path_factory.mktemp("certs")
    generate_self_signed_cert(hostname="localhost", output_dir=str(cert_dir))
    return cert_dir


@pytest.fixture(scope="module")
def server_config(certificates_dir: Path) -> ServerConfig:
    """Provide a base ServerConfig configured with the test certificates."""
    return ServerConfig(
        certfile=str(certificates_dir / "localhost.crt"),
        keyfile=str(certificates_dir / "localhost.key"),
        max_connections=10,
        connection_idle_timeout=5.0,
    )


@pytest.fixture(scope="module")
def client_config(certificates_dir: Path) -> ClientConfig:
    """Provide a ClientConfig that trusts the self-signed server certificate."""
    return ClientConfig(
        ca_certs=str(certificates_dir / "localhost.crt"),
        connect_timeout=5.0,
    )


@pytest.fixture
def server_app(request: pytest.FixtureRequest, server_config: ServerConfig) -> ServerApp:
    """Provide a ServerApp instance, supporting indirect parametrization for config overrides."""
    config_overrides = getattr(request, "param", {})
    if config_overrides and isinstance(config_overrides, dict):
        custom_config = server_config.update(**config_overrides)
        return ServerApp(config=custom_config)

    return ServerApp(config=server_config)


@pytest_asyncio.fixture
async def server(
    server_app: ServerApp,
) -> AsyncGenerator[tuple[str, int], None]:
    """Start a WebTransport server in a background task for a test."""
    host = "127.0.0.1"
    port = find_free_port()

    async with server_app:
        server_task = asyncio.create_task(server_app.serve(host=host, port=port))
        await asyncio.sleep(0.1)

        try:
            yield host, port
        finally:
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass


@pytest_asyncio.fixture
async def client(client_config: ClientConfig) -> AsyncGenerator[WebTransportClient, None]:
    """Provide a WebTransportClient instance for the duration of a test."""
    async with WebTransportClient.create(config=client_config) as wt_client:
        yield wt_client
