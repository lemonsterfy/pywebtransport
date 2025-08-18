"""Unit tests for the pywebtransport.stream.manager module."""

import asyncio
from typing import Any, AsyncGenerator, cast
from unittest import mock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import StreamError, StreamState, WebTransportSendStream, WebTransportStream
from pywebtransport.stream import StreamManager
from pywebtransport.stream.manager import StreamType
from pywebtransport.types import StreamId

TEST_STREAM_ID: StreamId = 4


class TestStreamManager:
    @pytest.fixture
    async def manager(self, mock_session: Any) -> AsyncGenerator[StreamManager, None]:
        async with StreamManager(mock_session) as mgr:
            yield mgr

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec("pywebtransport.session.WebTransportSession", instance=True)
        session._create_stream_on_protocol = mocker.AsyncMock(return_value=TEST_STREAM_ID)
        return session

    @pytest.fixture
    def mock_stream(self, mocker: MockerFixture) -> Any:
        stream = mocker.create_autospec(WebTransportStream, instance=True)
        stream.stream_id = TEST_STREAM_ID
        type(stream).is_closed = mocker.PropertyMock(return_value=False)
        stream.close = mocker.AsyncMock()
        stream.state = StreamState.OPEN
        stream.direction = "bidirectional"
        return stream

    def test_init_and_create(self, mock_session: Any) -> None:
        manager = StreamManager(mock_session, max_streams=50)
        assert manager._max_streams == 50
        assert manager._creation_semaphore is None

        manager_from_factory = StreamManager.create(mock_session, max_streams=20, stream_cleanup_interval=10.0)
        assert manager_from_factory._max_streams == 20
        assert manager_from_factory._cleanup_interval == 10.0

    @pytest.mark.asyncio
    async def test_len_and_contains(self, manager: StreamManager, mock_stream: Any) -> None:
        assert len(manager) == 0
        assert TEST_STREAM_ID not in manager
        assert "not-an-id" not in manager

        await manager.add_stream(mock_stream)

        assert len(manager) == 1
        assert TEST_STREAM_ID in manager

    @pytest.mark.asyncio
    async def test_async_iterator(self, manager: StreamManager, mock_stream: Any) -> None:
        await manager.add_stream(mock_stream)

        streams_iterated: list[StreamType] = []
        async for stream in manager:
            streams_iterated.append(stream)

        assert len(streams_iterated) == 1
        assert streams_iterated[0].stream_id == TEST_STREAM_ID

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_session: Any, mocker: MockerFixture) -> None:
        start_mock = mocker.patch.object(StreamManager, "_start_cleanup_task")
        shutdown_mock = mocker.patch.object(StreamManager, "shutdown", new_callable=mocker.AsyncMock)

        async with StreamManager(mock_session):
            start_mock.assert_called_once_with()

        shutdown_mock.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_create_bidirectional_stream(
        self, manager: StreamManager, mock_session: Any, mocker: MockerFixture
    ) -> None:
        add_stream_mock = mocker.patch.object(manager, "add_stream", new_callable=mocker.AsyncMock)

        stream = await manager.create_bidirectional_stream()

        mock_session._create_stream_on_protocol.assert_awaited_once_with(is_unidirectional=False)
        add_stream_mock.assert_awaited_once()
        assert isinstance(stream, WebTransportStream)
        assert stream.stream_id == TEST_STREAM_ID

    @pytest.mark.asyncio
    async def test_create_unidirectional_stream(
        self, manager: StreamManager, mock_session: Any, mocker: MockerFixture
    ) -> None:
        add_stream_mock = mocker.patch.object(manager, "add_stream", new_callable=mocker.AsyncMock)

        stream = await manager.create_unidirectional_stream()

        mock_session._create_stream_on_protocol.assert_awaited_once_with(is_unidirectional=True)
        add_stream_mock.assert_awaited_once()
        assert isinstance(stream, WebTransportSendStream)
        assert stream.stream_id == TEST_STREAM_ID

    @pytest.mark.asyncio
    async def test_add_and_remove_stream(self, manager: StreamManager, mock_stream: Any) -> None:
        await manager.add_stream(mock_stream)

        stats = await manager.get_stats()
        assert stats["total_created"] == 1
        assert stats["current_count"] == 1
        assert stats["max_concurrent"] == 1

        await manager.add_stream(mock_stream)
        assert len(manager) == 1

        removed_stream = await manager.remove_stream(mock_stream.stream_id)
        assert removed_stream is mock_stream

        stats_after_remove = await manager.get_stats()
        assert stats_after_remove["total_closed"] == 1
        assert stats_after_remove["current_count"] == 0

    @pytest.mark.asyncio
    async def test_get_all_streams(self, manager: StreamManager, mock_stream: Any) -> None:
        await manager.add_stream(mock_stream)

        streams = await manager.get_all_streams()

        assert len(streams) == 1
        assert streams[0] is mock_stream

    @pytest.mark.asyncio
    async def test_get_stats(self, manager: StreamManager, mock_stream: Any) -> None:
        await manager.add_stream(mock_stream)

        stats = await manager.get_stats()

        assert stats["active_streams"] == 1
        assert stats["max_streams"] == 100
        assert stats["states"] == {"open": 1}
        assert stats["directions"] == {"bidirectional": 1}

    @pytest.mark.asyncio
    async def test_create_stream_releases_semaphore_on_error(self, mock_session: Any) -> None:
        mock_session._create_stream_on_protocol.side_effect = RuntimeError("Protocol error")

        async with StreamManager(mock_session, max_streams=1) as manager:
            with pytest.raises(RuntimeError, match="Protocol error"):
                await manager.create_bidirectional_stream()

            assert manager._creation_semaphore is not None
            assert not manager._creation_semaphore.locked()
            assert manager._creation_semaphore._value == 1

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, mock_session: Any) -> None:
        async with StreamManager(mock_session, max_streams=1) as manager:
            mock_session._create_stream_on_protocol.return_value = 1
            stream1 = await manager.create_unidirectional_stream()

            with pytest.raises(StreamError, match=r"Cannot create new stream: stream limit \(1\) reached."):
                await manager.create_unidirectional_stream()

            assert manager._creation_semaphore is not None
            assert manager._creation_semaphore.locked()

            await manager.remove_stream(stream1.stream_id)

            mock_session._create_stream_on_protocol.return_value = 2
            stream2 = await manager.create_unidirectional_stream()
            assert stream2 is not None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_stream(self, manager: StreamManager) -> None:
        removed_stream = await manager.remove_stream(999)

        assert removed_stream is None
        stats = await manager.get_stats()
        assert stats["total_closed"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_closed_streams(self, manager: StreamManager, mocker: MockerFixture) -> None:
        stream_open = mocker.create_autospec(WebTransportStream, instance=True)
        stream_open.stream_id = 1
        type(stream_open).is_closed = mocker.PropertyMock(return_value=False)
        stream_closed = mocker.create_autospec(WebTransportStream, instance=True)
        stream_closed.stream_id = 2
        type(stream_closed).is_closed = mocker.PropertyMock(return_value=True)
        await manager.add_stream(stream_open)
        await manager.add_stream(stream_closed)
        assert len(manager) == 2

        cleaned_count = await manager.cleanup_closed_streams()

        assert cleaned_count == 1
        assert len(manager) == 1
        assert 1 in manager
        assert 2 not in manager

    @pytest.mark.asyncio
    async def test_cleanup_with_no_closed_streams(self, manager: StreamManager, mock_stream: Any) -> None:
        await manager.add_stream(mock_stream)

        cleaned_count = await manager.cleanup_closed_streams()

        assert cleaned_count == 0
        assert len(manager) == 1

    @pytest.mark.asyncio
    async def test_periodic_cleanup(self, mock_session: Any, mocker: MockerFixture) -> None:
        cleanup_called_event = asyncio.Event()

        async def cleanup_side_effect(*args: Any, **kwargs: Any) -> int:
            cleanup_called_event.set()
            return 0

        cleanup_mock = mocker.patch.object(StreamManager, "cleanup_closed_streams", side_effect=cleanup_side_effect)

        async with StreamManager(mock_session, stream_cleanup_interval=0.01):
            try:
                await asyncio.wait_for(cleanup_called_event.wait(), timeout=1)
            except asyncio.TimeoutError:
                pytest.fail("Periodic cleanup task did not run as expected.")

            assert cleanup_mock.call_count >= 1

    @pytest.mark.asyncio
    async def test_periodic_cleanup_handles_exception(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch.object(StreamManager, "cleanup_closed_streams", side_effect=ValueError("Cleanup failed"))
        mock_logger_error = mocker.patch("pywebtransport.stream.manager.logger.error")

        async with StreamManager(mock_session, stream_cleanup_interval=0.01):
            await asyncio.sleep(0.05)

        assert mock_logger_error.call_count > 0
        mock_logger_error.assert_any_call("Stream cleanup cycle failed: Cleanup failed", exc_info=mock.ANY)

    @pytest.mark.asyncio
    async def test_shutdown(self, manager: StreamManager, mocker: MockerFixture) -> None:
        close_all_mock = mocker.patch.object(manager, "close_all_streams", new_callable=mocker.AsyncMock)
        assert manager._cleanup_task is not None
        the_task = manager._cleanup_task

        await manager.shutdown()

        assert the_task.done()
        close_all_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_no_task(self, mock_session: Any, mocker: MockerFixture) -> None:
        close_all_mock = mocker.patch.object(StreamManager, "close_all_streams", new_callable=mocker.AsyncMock)
        manager = StreamManager(mock_session)

        await manager.__aenter__()
        assert manager._cleanup_task is not None
        manager._cleanup_task.cancel()
        await asyncio.sleep(0)

        await manager.shutdown()

        close_all_mock.assert_awaited_once()
        await manager.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_close_all_streams(self, manager: StreamManager, mock_stream: Any) -> None:
        await manager.add_stream(mock_stream)

        await manager.close_all_streams()

        cast(mock.AsyncMock, mock_stream.close).assert_awaited_once()
        assert len(manager) == 0

    @pytest.mark.asyncio
    async def test_close_all_streams_empty(self, manager: StreamManager) -> None:
        await manager.close_all_streams()

        assert len(manager) == 0
