"""Unit tests for the pywebtransport.pool.stream module."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio

from pywebtransport import WebTransportSession, WebTransportStream
from pywebtransport.pool import StreamPool


class TestStreamPool:
    @pytest.fixture
    def mock_session(self) -> MagicMock:
        session = MagicMock(spec=WebTransportSession)
        session.create_bidirectional_stream = AsyncMock()
        return session

    @pytest.fixture
    def mock_stream(self) -> MagicMock:
        stream = MagicMock(spec=WebTransportStream)
        stream.close = AsyncMock()
        return stream

    @pytest.fixture
    def pool(self, mock_session: MagicMock) -> StreamPool:
        return StreamPool(session=mock_session, max_size=5)

    @pytest_asyncio.fixture
    async def running_pool(self, pool: StreamPool) -> AsyncGenerator[StreamPool, None]:
        async with pool:
            yield pool

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
        self, pool: StreamPool, mock_session: MagicMock, mock_stream: MagicMock
    ) -> None:
        mock_session.create_bidirectional_stream.return_value = mock_stream

        stream = await pool._factory()

        assert stream is mock_stream
        mock_session.create_bidirectional_stream.assert_awaited_once_with()

    def test_initialization(self, pool: StreamPool) -> None:
        assert pool._max_size == 5
        assert pool._factory is not None
