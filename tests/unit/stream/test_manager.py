"""Unit tests for the pywebtransport.stream.manager module."""

import asyncio
from typing import Any, List

import pytest
from pytest_mock import MockerFixture

from pywebtransport import StreamState, WebTransportSendStream, WebTransportStream
from pywebtransport.stream import StreamManager
from pywebtransport.stream.manager import StreamType
from pywebtransport.types import StreamId

TEST_STREAM_ID: StreamId = 4


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    session = mocker.create_autospec("pywebtransport.session.WebTransportSession", instance=True)
    session._create_stream_on_protocol = mocker.AsyncMock(return_value=TEST_STREAM_ID)
    return session


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> Any:
    stream = mocker.create_autospec(WebTransportStream, instance=True)
    stream.stream_id = TEST_STREAM_ID
    stream.is_closed = False
    stream.close = mocker.AsyncMock()
    stream.state = StreamState.OPEN
    stream.direction = "bidirectional"
    return stream


@pytest.mark.asyncio
class TestStreamManager:
    async def test_init_and_create(self, mock_session: Any) -> None:
        manager = StreamManager(mock_session, max_streams=50)
        assert manager._max_streams == 50
        assert isinstance(manager._creation_semaphore, asyncio.Semaphore)
        assert manager._creation_semaphore._value == 50

        manager_from_factory = StreamManager.create(mock_session, max_streams=20)
        assert manager_from_factory._max_streams == 20

    async def test_len_and_contains(self, mock_session: Any, mock_stream: Any) -> None:
        manager = StreamManager(mock_session)
        assert len(manager) == 0
        assert TEST_STREAM_ID not in manager
        assert "not-an-id" not in manager

        await manager.add_stream(mock_stream)
        assert len(manager) == 1
        assert TEST_STREAM_ID in manager

    async def test_async_iterator(self, mock_session: Any, mock_stream: Any) -> None:
        manager = StreamManager(mock_session)
        await manager.add_stream(mock_stream)

        streams_iterated: List[StreamType] = []
        async for stream in manager:
            streams_iterated.append(stream)

        assert len(streams_iterated) == 1
        assert streams_iterated[0].stream_id == TEST_STREAM_ID

    async def test_context_manager(self, mock_session: Any, mocker: MockerFixture) -> None:
        start_mock = mocker.patch.object(StreamManager, "_start_cleanup_task")
        shutdown_mock = mocker.patch.object(StreamManager, "shutdown", new_callable=mocker.AsyncMock)

        async with StreamManager(mock_session) as _:
            start_mock.assert_called_once_with()
        shutdown_mock.assert_awaited_once_with()

    async def test_create_bidirectional_stream(self, mock_session: Any, mocker: MockerFixture) -> None:
        add_stream_mock = mocker.patch.object(StreamManager, "add_stream", new_callable=mocker.AsyncMock)

        manager = StreamManager(mock_session)
        stream = await manager.create_bidirectional_stream()

        mock_session._create_stream_on_protocol.assert_awaited_once_with(is_unidirectional=False)
        add_stream_mock.assert_awaited_once()
        assert isinstance(stream, WebTransportStream)
        assert stream.stream_id == TEST_STREAM_ID

    async def test_create_unidirectional_stream(self, mock_session: Any, mocker: MockerFixture) -> None:
        add_stream_mock = mocker.patch.object(StreamManager, "add_stream", new_callable=mocker.AsyncMock)

        manager = StreamManager(mock_session)
        stream = await manager.create_unidirectional_stream()

        mock_session._create_stream_on_protocol.assert_awaited_once_with(is_unidirectional=True)
        add_stream_mock.assert_awaited_once()
        assert isinstance(stream, WebTransportSendStream)
        assert stream.stream_id == TEST_STREAM_ID

    async def test_add_and_remove_stream(self, mock_session: Any, mock_stream: Any) -> None:
        manager = StreamManager(mock_session)
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

    async def test_get_all_streams(self, mock_session: Any, mock_stream: Any) -> None:
        manager = StreamManager(mock_session)
        await manager.add_stream(mock_stream)

        streams = await manager.get_all_streams()
        assert len(streams) == 1
        assert streams[0] is mock_stream

    async def test_get_stats(self, mock_session: Any, mock_stream: Any) -> None:
        manager = StreamManager(mock_session, max_streams=50)
        await manager.add_stream(mock_stream)

        stats = await manager.get_stats()

        assert stats["active_streams"] == 1
        assert stats["max_streams"] == 50
        assert stats["states"] == {"open": 1}
        assert stats["directions"] == {"bidirectional": 1}

    async def test_create_stream_releases_semaphore_on_error(self, mock_session: Any) -> None:
        mock_session._create_stream_on_protocol.side_effect = RuntimeError("Protocol error")
        manager = StreamManager(mock_session, max_streams=1)

        with pytest.raises(RuntimeError, match="Protocol error"):
            await manager.create_bidirectional_stream()

        assert manager._creation_semaphore.locked() is False
        assert manager._creation_semaphore._value == 1

    async def test_concurrency_limit(self, mock_session: Any) -> None:
        manager = StreamManager(mock_session, max_streams=1)

        mock_session._create_stream_on_protocol.return_value = 1
        stream1 = await manager.create_unidirectional_stream()

        with pytest.raises(asyncio.TimeoutError):
            create_task = asyncio.create_task(manager.create_unidirectional_stream())
            await asyncio.wait_for(create_task, timeout=0.01)

        await manager.remove_stream(stream1.stream_id)

        mock_session._create_stream_on_protocol.return_value = 2
        stream2 = await manager.create_unidirectional_stream()
        assert stream2 is not None

    async def test_remove_nonexistent_stream(self, mock_session: Any) -> None:
        manager = StreamManager(mock_session)
        removed_stream = await manager.remove_stream(999)
        assert removed_stream is None
        stats = await manager.get_stats()
        assert stats["total_closed"] == 0

    async def test_cleanup_closed_streams(self, mock_session: Any, mocker: MockerFixture) -> None:
        manager = StreamManager(mock_session)
        stream_open = mocker.create_autospec(WebTransportStream, instance=True)
        stream_open.stream_id = 1
        stream_open.is_closed = False
        stream_closed = mocker.create_autospec(WebTransportStream, instance=True)
        stream_closed.stream_id = 2
        stream_closed.is_closed = True

        await manager.add_stream(stream_open)
        await manager.add_stream(stream_closed)
        assert len(manager) == 2

        cleaned_count = await manager.cleanup_closed_streams()
        assert cleaned_count == 1
        assert len(manager) == 1
        assert 1 in manager
        assert 2 not in manager

    async def test_cleanup_with_no_closed_streams(self, mock_session: Any, mock_stream: Any) -> None:
        manager = StreamManager(mock_session)
        await manager.add_stream(mock_stream)
        cleaned_count = await manager.cleanup_closed_streams()
        assert cleaned_count == 0
        assert len(manager) == 1

    async def test_periodic_cleanup(self, mock_session: Any, mocker: MockerFixture) -> None:
        cleanup_mock = mocker.patch.object(StreamManager, "cleanup_closed_streams", new_callable=mocker.AsyncMock)
        sleep_called_event = asyncio.Event()
        original_sleep = asyncio.sleep

        async def sleep_side_effect(*args: Any, **kwargs: Any) -> None:
            sleep_called_event.set()
            await original_sleep(0)

        sleep_mock = mocker.patch("asyncio.sleep", side_effect=sleep_side_effect)
        manager = StreamManager(mock_session, cleanup_interval=0.01)
        manager._start_cleanup_task()

        try:
            await asyncio.wait_for(sleep_called_event.wait(), timeout=1)
        except asyncio.TimeoutError:
            pytest.fail("Periodic cleanup task did not run as expected.")

        assert sleep_mock.call_count >= 1
        assert cleanup_mock.call_count >= 1
        assert manager._cleanup_task is not None
        manager._cleanup_task.cancel()
        await manager._cleanup_task

    async def test_periodic_cleanup_handles_exception(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch.object(StreamManager, "cleanup_closed_streams", side_effect=ValueError("Cleanup failed"))
        error_logged_event = asyncio.Event()

        def log_side_effect(*args: Any, **kwargs: Any) -> None:
            error_logged_event.set()

        mock_logger_error = mocker.patch("pywebtransport.stream.manager.logger.error", side_effect=log_side_effect)
        manager = StreamManager(mock_session, cleanup_interval=0.01)
        manager._start_cleanup_task()

        try:
            await asyncio.wait_for(error_logged_event.wait(), timeout=1)
        except asyncio.TimeoutError:
            pytest.fail("Periodic cleanup task did not log the error as expected.")

        mock_logger_error.assert_called_once()
        assert "Cleanup failed" in str(mock_logger_error.call_args)
        assert manager._cleanup_task is not None
        manager._cleanup_task.cancel()
        await manager._cleanup_task

    async def test_start_cleanup_task_no_loop(self, mock_session: Any, mocker: MockerFixture) -> None:
        mock_periodic_cleanup = mocker.MagicMock()
        mocker.patch.object(StreamManager, "_periodic_cleanup", new=mock_periodic_cleanup)
        mock_create_task = mocker.patch("asyncio.create_task", side_effect=RuntimeError("no loop"))
        mock_logger_warning = mocker.patch("pywebtransport.stream.manager.logger.warning")

        manager = StreamManager(mock_session)
        manager._start_cleanup_task()

        mock_periodic_cleanup.assert_called_once()
        mock_create_task.assert_called_once_with(mock_periodic_cleanup.return_value)
        mock_logger_warning.assert_called_once_with("Could not start cleanup task: no running event loop.")

    async def test_shutdown(self, mock_session: Any, mocker: MockerFixture) -> None:
        close_all_mock = mocker.patch.object(StreamManager, "close_all_streams", new_callable=mocker.AsyncMock)
        manager = StreamManager(mock_session)

        manager._start_cleanup_task()
        assert manager._cleanup_task is not None

        await manager.shutdown()

        assert manager._cleanup_task.cancelled()
        close_all_mock.assert_awaited_once()

    async def test_shutdown_no_task(self, mock_session: Any, mocker: MockerFixture) -> None:
        close_all_mock = mocker.patch.object(StreamManager, "close_all_streams", new_callable=mocker.AsyncMock)
        manager = StreamManager(mock_session)
        await manager.shutdown()
        close_all_mock.assert_awaited_once()

    async def test_close_all_streams(self, mock_session: Any, mock_stream: Any) -> None:
        manager = StreamManager(mock_session)
        await manager.add_stream(mock_stream)

        await manager.close_all_streams()

        mock_stream.close.assert_awaited_once()
        assert len(manager) == 0

    async def test_close_all_streams_empty(self, mock_session: Any) -> None:
        manager = StreamManager(mock_session)
        await manager.close_all_streams()
