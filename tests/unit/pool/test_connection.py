"""Unit tests for the pywebtransport.pool.connection module."""

from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig
from pywebtransport.connection import WebTransportConnection
from pywebtransport.pool import ConnectionPool


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(spec=ClientConfig)


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock(spec=WebTransportConnection)
    conn.close = AsyncMock()
    return conn


@pytest.fixture
def patch_create_client(mocker: MockerFixture, mock_connection: MagicMock) -> AsyncMock:
    return mocker.patch.object(WebTransportConnection, "create_client", return_value=mock_connection)


@pytest.fixture
def pool(mock_config: MagicMock) -> ConnectionPool:
    return ConnectionPool(
        config=mock_config,
        host="localhost",
        port=4433,
        path="/",
        max_size=5,
    )


@pytest_asyncio.fixture
async def running_pool(pool: ConnectionPool) -> AsyncGenerator[ConnectionPool, None]:
    async with pool:
        yield pool


class TestConnectionPool:
    @pytest.mark.asyncio
    async def test_dispose_closes_connection(self, pool: ConnectionPool, mock_connection: MagicMock) -> None:
        type(mock_connection).is_closed = PropertyMock(return_value=False)

        await pool._dispose(mock_connection)

        mock_connection.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispose_ignores_already_closed_connection(
        self, pool: ConnectionPool, mock_connection: MagicMock
    ) -> None:
        type(mock_connection).is_closed = PropertyMock(return_value=True)

        await pool._dispose(mock_connection)

        mock_connection.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_factory_creates_connection(
        self,
        pool: ConnectionPool,
        patch_create_client: AsyncMock,
        mock_config: MagicMock,
    ) -> None:
        connection = await pool._factory()

        assert connection is patch_create_client.return_value
        patch_create_client.assert_awaited_once_with(
            config=mock_config,
            host="localhost",
            port=4433,
            path="/",
        )

    def test_initialization(self, pool: ConnectionPool, mock_config: MagicMock) -> None:
        assert pool._max_size == 5
        assert pool._factory is not None
