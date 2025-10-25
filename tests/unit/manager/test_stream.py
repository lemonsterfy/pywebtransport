"""Unit tests for the pywebtransport.manager.stream module."""

import asyncio
from typing import AsyncGenerator, cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import (
    StreamError,
    WebTransportReceiveStream,
    WebTransportSendStream,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.manager import StreamManager
from pywebtransport.manager.stream import StreamType
from pywebtransport.types import StreamDirection, StreamId, StreamState


@pytest.fixture
def manager(
    mock_stream_factory: AsyncMock,
    mock_session_factory: MagicMock,
) -> StreamManager:
    """Fixture for a StreamManager instance."""
    return StreamManager(
        stream_factory=mock_stream_factory,
        session_factory=mock_session_factory,
        max_streams=10,
        stream_cleanup_interval=0.01,
    )


@pytest.fixture
def mock_session() -> MagicMock:
    """Fixture for a mock WebTransportSession."""
    return MagicMock(spec=WebTransportSession)


@pytest.fixture
def mock_session_factory(mock_session: MagicMock) -> MagicMock:
    """Fixture for a mock session factory."""
    return MagicMock(return_value=mock_session)


@pytest.fixture
def mock_stream_factory(mocker: MockerFixture) -> MagicMock:
    """Fixture for a mock stream factory that returns sequential stream IDs."""
    return cast(MagicMock, mocker.AsyncMock(side_effect=[i for i in range(0, 100, 2)]))


@pytest_asyncio.fixture
async def running_manager(
    manager: StreamManager,
) -> AsyncGenerator[StreamManager, None]:
    """Fixture for a running StreamManager within a context."""
    async with manager as mgr:
        yield mgr


class TestStreamManager:
    """Test suite for the StreamManager class."""

    def create_mock_stream(
        self,
        mocker: MockerFixture,
        stream_id: StreamId,
        is_closed: bool = False,
        stream_type: type[StreamType] = WebTransportStream,
        state: StreamState = StreamState.OPEN,
    ) -> MagicMock:
        """Helper to create a mock stream with specific properties."""
        stream = mocker.create_autospec(stream_type, instance=True)
        stream.stream_id = stream_id
        is_closed_mock = PropertyMock(return_value=is_closed)
        type(stream).is_closed = is_closed_mock

        stream.close = AsyncMock()
        if hasattr(stream, "state"):
            stream.state = state if not is_closed else StreamState.CLOSED
        if hasattr(stream, "direction"):
            if stream_type is WebTransportStream:
                stream.direction = StreamDirection.BIDIRECTIONAL
            elif stream_type is WebTransportSendStream:
                stream.direction = StreamDirection.SEND_ONLY
            elif stream_type is WebTransportReceiveStream:
                stream.direction = StreamDirection.RECEIVE_ONLY
        return stream

    @pytest.mark.asyncio
    async def test_add_stream(self, running_manager: StreamManager, mocker: MockerFixture) -> None:
        """Test adding an externally created stream."""
        stream = self.create_mock_stream(mocker, 1)
        await running_manager.add_stream(stream=stream)
        assert len(running_manager) == 1
        assert 1 in running_manager

        stats = await running_manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["current_count"] == 1

    @pytest.mark.asyncio
    async def test_add_stream_idempotent(self, running_manager: StreamManager, mocker: MockerFixture) -> None:
        """Test that adding an existing stream does not increment stats."""
        stream = self.create_mock_stream(mocker, 1)
        await running_manager.add_stream(stream=stream)
        await running_manager.add_stream(stream=stream)  # Add again

        assert len(running_manager) == 1
        stats = await running_manager.get_stats()
        assert stats["total_created"] == 1

    @pytest.mark.asyncio
    async def test_aiter(self, running_manager: StreamManager) -> None:
        """Test asynchronous iteration over the managed streams."""
        s1 = await running_manager.create_bidirectional_stream()
        s2 = await running_manager.create_unidirectional_stream()

        streams = {s async for s in running_manager}
        assert streams == {s1, s2}

    @pytest.mark.asyncio
    async def test_async_context_manager(self, manager: StreamManager, mocker: MockerFixture) -> None:
        start_spy = mocker.spy(manager, "_start_background_tasks")
        shutdown_spy = mocker.spy(manager, "shutdown")

        async with manager as mgr:
            assert mgr is manager
            assert manager._lock is not None
            start_spy.assert_called_once()

        shutdown_spy.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_closed_streams(self, running_manager: StreamManager, mocker: MockerFixture) -> None:
        """Test that cleanup correctly handles both created and external streams."""
        open_stream = await running_manager.create_bidirectional_stream()
        closed_stream_mock = self.create_mock_stream(mocker, 99, is_closed=True)
        await running_manager.add_stream(stream=closed_stream_mock)

        assert len(running_manager) == 2
        count = await running_manager.cleanup_closed_streams()

        assert count == 1
        assert len(running_manager) == 1
        assert open_stream.stream_id in running_manager
        assert closed_stream_mock.stream_id not in running_manager

        stats = await running_manager.get_stats()
        assert stats["total_closed"] == 1
        assert stats["semaphore_value"] == 9  # 10 max - 1 open stream

    @pytest.mark.asyncio
    async def test_cleanup_on_empty_manager(self, running_manager: StreamManager) -> None:
        """Test that cleanup does nothing when the manager is empty."""
        assert len(running_manager) == 0
        count = await running_manager.cleanup_closed_streams()
        assert count == 0
        stats = await running_manager.get_stats()
        assert stats["total_closed"] == 0

    @pytest.mark.asyncio
    async def test_contains(self, running_manager: StreamManager) -> None:
        """Test the __contains__ method for checking stream existence."""
        stream = await running_manager.create_bidirectional_stream()
        assert stream.stream_id in running_manager
        assert 999 not in running_manager
        assert "not-an-id" not in running_manager

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_factory_error(
        self,
        running_manager: StreamManager,
        mock_stream_factory: AsyncMock,
        method_name: str,
    ) -> None:
        """Test that the semaphore is released if the stream factory fails."""
        mock_stream_factory.side_effect = ValueError("Factory failed")

        with pytest.raises(ValueError, match="Factory failed"):
            await getattr(running_manager, method_name)()

        stats = await running_manager.get_stats()
        assert stats["semaphore_value"] == 10
        assert len(running_manager) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["create_bidirectional_stream", "create_unidirectional_stream"])
    async def test_create_stream_limit_reached(self, running_manager: StreamManager, method_name: str) -> None:
        """Test that creating a stream fails when the limit is reached."""
        running_manager._max_resources = 1
        running_manager._creation_semaphore = asyncio.Semaphore(1)

        await getattr(running_manager, method_name)()
        with pytest.raises(StreamError, match="stream limit"):
            await getattr(running_manager, method_name)()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "create_method_name, factory_arg, expected_stream_type",
        [
            ("create_bidirectional_stream", False, WebTransportStream),
            ("create_unidirectional_stream", True, WebTransportSendStream),
        ],
    )
    async def test_create_streams(
        self,
        running_manager: StreamManager,
        mock_stream_factory: AsyncMock,
        create_method_name: str,
        factory_arg: bool,
        expected_stream_type: type,
    ) -> None:
        """Test creation of bidirectional and unidirectional streams."""
        create_method = getattr(running_manager, create_method_name)
        stream = cast(WebTransportStream | WebTransportSendStream, await create_method())

        assert isinstance(stream, expected_stream_type)
        assert stream.stream_id == 0
        assert len(running_manager) == 1
        mock_stream_factory.assert_awaited_once_with(factory_arg)

        stats = await running_manager.get_stats()
        assert stats["semaphore_value"] == 9

    @pytest.mark.asyncio
    async def test_get_stats(self, running_manager: StreamManager, mocker: MockerFixture) -> None:
        """Test that get_stats aggregates data correctly."""
        await running_manager.create_bidirectional_stream()
        await running_manager.create_unidirectional_stream()
        recv_stream = self.create_mock_stream(
            mocker, 4, stream_type=WebTransportReceiveStream, state=StreamState.CLOSED
        )
        await running_manager.add_stream(stream=recv_stream)

        stats = await running_manager.get_stats()
        assert stats["states"] == {StreamState.OPEN: 2, StreamState.CLOSED: 1}
        assert stats["directions"] == {
            StreamDirection.BIDIRECTIONAL: 1,
            StreamDirection.SEND_ONLY: 1,
            StreamDirection.RECEIVE_ONLY: 1,
        }
        assert not stats["semaphore_locked"]
        assert stats["semaphore_value"] == 8

    @pytest.mark.asyncio
    async def test_get_stats_on_empty_manager(self, running_manager: StreamManager) -> None:
        """Test that get_stats returns default values for an empty manager."""
        stats = await running_manager.get_stats()
        assert stats["current_count"] == 0
        assert stats["total_created"] == 0
        assert stats["total_closed"] == 0
        assert stats["states"] == {}
        assert stats["directions"] == {}
        assert stats["semaphore_value"] == 10

    def test_initialization(self, manager: StreamManager) -> None:
        """Test that the manager initializes with correct properties."""
        assert manager._max_resources == 10
        assert manager._cleanup_interval == 0.01
        assert manager._stream_factory is not None
        assert manager._session_factory is not None

    @pytest.mark.asyncio
    async def test_manager_inactive_methods(self, manager: StreamManager, mocker: MockerFixture) -> None:
        """Test that key methods raise errors or return safely when the manager is not active."""
        mock_stream = self.create_mock_stream(mocker, 0)

        with pytest.raises(StreamError, match="has not been activated"):
            await manager.add_stream(stream=mock_stream)
        with pytest.raises(StreamError, match="has not been activated"):
            await manager.create_bidirectional_stream()
        with pytest.raises(StreamError, match="has not been activated"):
            await manager.create_unidirectional_stream()
        with pytest.raises(StreamError, match="has not been activated"):
            async for _ in manager:
                pass

        assert await manager.remove_stream(stream_id=0) is None
        assert await manager.cleanup_closed_streams() == 0
        assert await manager.get_stats() == {}

    @pytest.mark.asyncio
    async def test_remove_external_stream(self, running_manager: StreamManager, mocker: MockerFixture) -> None:
        """Test removing an externally-added stream does not release the semaphore."""
        external_stream = self.create_mock_stream(mocker, 99)
        await running_manager.add_stream(stream=external_stream)

        await running_manager.remove_stream(stream_id=external_stream.stream_id)

        stats = await running_manager.get_stats()
        assert stats["semaphore_value"] == 10  # Should be unchanged

    @pytest.mark.asyncio
    async def test_remove_stream(self, running_manager: StreamManager) -> None:
        """Test removing a manager-created stream correctly releases the semaphore."""
        stream = await running_manager.create_bidirectional_stream()
        assert len(running_manager) == 1

        removed = await running_manager.remove_stream(stream_id=stream.stream_id)
        assert removed is stream
        assert len(running_manager) == 0

        stats = await running_manager.get_stats()
        assert stats["total_closed"] == 1
        assert stats["semaphore_value"] == 10

    @pytest.mark.asyncio
    async def test_remove_stream_not_found(self, running_manager: StreamManager) -> None:
        """Test that removing a non-existent stream does nothing."""
        removed = await running_manager.remove_stream(stream_id=999)
        assert removed is None

        stats = await running_manager.get_stats()
        assert stats["total_closed"] == 0
        assert stats["semaphore_value"] == 10

    @pytest.mark.asyncio
    async def test_shutdown_closes_open_streams(self, manager: StreamManager, mocker: MockerFixture) -> None:
        """Test that the manager closes all open streams on shutdown."""
        mocker.patch.object(manager, "_periodic_cleanup", new_callable=AsyncMock)
        open_stream = self.create_mock_stream(mocker, 0, is_closed=False)
        closed_stream = self.create_mock_stream(mocker, 1, is_closed=True)

        async with manager:
            await manager.add_stream(stream=open_stream)
            await manager.add_stream(stream=closed_stream)

        open_stream.close.assert_awaited_once()
        closed_stream.close.assert_not_awaited()
