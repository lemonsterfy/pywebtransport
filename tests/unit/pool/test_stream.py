"""Unit tests for the pywebtransport.pool.stream module."""

from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio

from pywebtransport import WebTransportStream
from pywebtransport.manager import StreamManager
from pywebtransport.pool import StreamPool


@pytest.fixture
def mock_stream() -> MagicMock:
    stream = MagicMock(spec=WebTransportStream)
    stream.close = AsyncMock()
    return stream


@pytest.fixture
def mock_stream_manager() -> MagicMock:
    manager = MagicMock(spec=StreamManager)
    manager.create_bidirectional_stream = AsyncMock()
    return manager


@pytest.fixture
def pool(mock_stream_manager: MagicMock) -> StreamPool:
    return StreamPool(stream_manager=mock_stream_manager, max_size=5)


@pytest_asyncio.fixture
async def running_pool(pool: StreamPool) -> AsyncGenerator[StreamPool, None]:
    async with pool:
        yield pool


class TestStreamPool:
    @pytest.mark.asyncio
    async def test_dispose_closes_stream(self, pool: StreamPool, mock_stream: MagicMock) -> None:
        type(mock_stream).is_closed = PropertyMock(return_value=False)

        await pool._dispose(mock_stream)

        mock_stream.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispose_ignores_already_closed_stream(self, pool: StreamPool, mock_stream: MagicMock) -> None:
        type(mock_stream).is_closed = PropertyMock(return_value=True)

        await pool._dispose(mock_stream)

        mock_stream.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_factory_creates_stream(
        self, pool: StreamPool, mock_stream_manager: MagicMock, mock_stream: MagicMock
    ) -> None:
        mock_stream_manager.create_bidirectional_stream.return_value = mock_stream

        stream = await pool._factory()

        assert stream is mock_stream
        mock_stream_manager.create_bidirectional_stream.assert_awaited_once_with()

    def test_initialization(self, pool: StreamPool) -> None:
        assert pool._max_size == 5
        assert pool._factory is not None
