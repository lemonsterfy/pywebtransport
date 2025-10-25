"""Unit tests for the pywebtransport.pool.session module."""

from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio

from pywebtransport import URL, WebTransportClient, WebTransportSession
from pywebtransport.pool import SessionPool


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=WebTransportClient)
    client.connect = AsyncMock()
    return client


@pytest.fixture
def mock_session() -> MagicMock:
    session = MagicMock(spec=WebTransportSession)
    session.close = AsyncMock()
    return session


@pytest.fixture
def pool(mock_client: MagicMock) -> SessionPool:
    return SessionPool(client=mock_client, url=URL("https://localhost:4433"), max_size=5)


@pytest_asyncio.fixture
async def running_pool(pool: SessionPool) -> AsyncGenerator[SessionPool, None]:
    async with pool:
        yield pool


class TestSessionPool:
    @pytest.mark.asyncio
    async def test_dispose_closes_session(self, pool: SessionPool, mock_session: MagicMock) -> None:
        type(mock_session).is_closed = PropertyMock(return_value=False)

        await pool._dispose(mock_session)

        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispose_ignores_already_closed_session(self, pool: SessionPool, mock_session: MagicMock) -> None:
        type(mock_session).is_closed = PropertyMock(return_value=True)

        await pool._dispose(mock_session)

        mock_session.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_factory_creates_session(
        self, pool: SessionPool, mock_client: MagicMock, mock_session: MagicMock
    ) -> None:
        mock_client.connect.return_value = mock_session

        session = await pool._factory()

        assert session is mock_session
        mock_client.connect.assert_awaited_once_with(url="https://localhost:4433")

    def test_initialization(self, pool: SessionPool) -> None:
        assert pool._max_size == 5
        assert pool._factory is not None
