"""Unit tests for the pywebtransport.stream.pool module."""

import asyncio
from typing import Any, AsyncGenerator, Callable, cast
from unittest import mock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import StreamError, WebTransportSession, WebTransportStream
from pywebtransport.stream import StreamPool


@pytest.fixture
def mock_session(mocker: MockerFixture) -> Any:
    session = mocker.create_autospec(WebTransportSession, instance=True)
    session.create_bidirectional_stream = mocker.AsyncMock()
    type(session).is_closed = mocker.PropertyMock(return_value=False)
    return session


@pytest.fixture
def mock_stream_factory(mocker: MockerFixture) -> Callable[[], Any]:
    def _factory() -> Any:
        stream = mocker.create_autospec(WebTransportStream, instance=True)
        stream.close = mocker.AsyncMock()
        type(stream).is_closed = mocker.PropertyMock(return_value=False)
        stream.stream_id = mocker.sentinel.stream_id
        return stream

    return _factory


@pytest.fixture
async def populated_pool(mock_session: Any, mock_stream_factory: Callable[[], Any]) -> AsyncGenerator[StreamPool, None]:
    streams = [mock_stream_factory() for _ in range(2)]
    mock_session.create_bidirectional_stream.side_effect = streams
    async with StreamPool(session=mock_session, pool_size=2) as pool:
        yield pool


class TestStreamPoolInitialization:
    def test_init_success(self, mock_session: Any) -> None:
        pool = StreamPool(session=mock_session, pool_size=5, maintenance_interval=120)

        assert pool._session is mock_session
        assert pool._pool_size == 5
        assert pool._maintenance_interval == 120

    def test_create_factory_success(self, mock_session: Any) -> None:
        pool = StreamPool.create(session=mock_session, pool_size=5)

        assert isinstance(pool, StreamPool)
        assert pool._pool_size == 5

    @pytest.mark.parametrize("pool_size", [0, -1])
    def test_init_invalid_pool_size(self, mock_session: Any, pool_size: int) -> None:
        with pytest.raises(ValueError, match="Pool size must be a positive integer."):
            StreamPool(session=mock_session, pool_size=pool_size)


class TestStreamPoolLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_pool_is_idempotent(
        self, mock_session: Any, mock_stream_factory: Callable[[], Any], mocker: MockerFixture
    ) -> None:
        streams = [mock_stream_factory() for _ in range(2)]
        mock_session.create_bidirectional_stream.side_effect = streams

        async with StreamPool(session=mock_session, pool_size=2) as pool:
            fill_pool_spy = mocker.spy(pool, "_fill_pool")
            fill_pool_spy.reset_mock()
            assert pool._total_managed_streams == 2

            await pool._initialize_pool()

            fill_pool_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_all_on_uninitialized_pool_fails(self, mock_session: Any) -> None:
        pool = StreamPool(session=mock_session)

        with pytest.raises(StreamError, match="StreamPool has not been activated"):
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_async_context_manager_calls_close_all(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        close_all_mock = mocker.patch.object(StreamPool, "close_all", new_callable=mocker.AsyncMock)

        async with StreamPool(session=mock_session):
            pass

        close_all_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fill_pool_stops_if_session_closed(
        self, mock_session: Any, mock_stream_factory: Callable[[], Any], mocker: MockerFixture
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        mock_session.create_bidirectional_stream.side_effect = [mock_stream_factory() for _ in range(5)]
        type(mock_session).is_closed = mocker.PropertyMock(side_effect=[False, False, True])

        async with StreamPool(session=mock_session, pool_size=5) as pool:
            assert pool._total_managed_streams == 2
            mock_logger.warning.assert_called_once_with("Session closed during stream pool replenishment.")

    @pytest.mark.asyncio
    async def test_initialize_pool_does_not_raise_on_error(self, mock_session: Any, mocker: MockerFixture) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        mock_session.create_bidirectional_stream.side_effect = RuntimeError("Creation failed")

        async with StreamPool(session=mock_session):
            pass

        mock_logger.error.assert_called_with("Error initializing stream pool: Creation failed")

    @pytest.mark.asyncio
    async def test_close_all_cancels_maintenance_task(self, populated_pool: StreamPool) -> None:
        task = populated_pool._maintenance_task
        assert task is not None
        assert not task.done()

        await populated_pool.close_all()

        assert task.done()

    @pytest.mark.asyncio
    async def test_close_all_waits_for_cancelled_task(self, mock_session: Any, mocker: MockerFixture) -> None:
        task_is_running = asyncio.Event()
        task_has_finished = asyncio.Event()

        async def controlled_coro() -> None:
            task_is_running.set()
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                await asyncio.sleep(0.01)
                task_has_finished.set()
                raise

        mocker.patch.object(StreamPool, "_maintain_pool_loop", side_effect=controlled_coro)

        async with StreamPool(session=mock_session) as pool:
            await task_is_running.wait()
            await pool.close_all()
            assert task_has_finished.is_set()


class TestStreamPoolOperations:
    @pytest.mark.asyncio
    async def test_get_stream_from_pool(self, populated_pool: StreamPool) -> None:
        assert populated_pool._available is not None
        initial_qsize = populated_pool._available.qsize()
        assert initial_qsize == 2

        stream = await populated_pool.get_stream()

        assert stream is not None
        assert populated_pool._available.qsize() == initial_qsize - 1

    @pytest.mark.asyncio
    async def test_return_stream_to_pool(self, populated_pool: StreamPool) -> None:
        stream = await populated_pool.get_stream()
        assert populated_pool._available is not None
        assert populated_pool._available.qsize() == 1

        await populated_pool.return_stream(stream)

        assert populated_pool._available.qsize() == 2

    @pytest.mark.asyncio
    async def test_get_stream_from_empty_pool(
        self,
        populated_pool: StreamPool,
        mock_session: Any,
        mock_stream_factory: Callable[[], Any],
    ) -> None:
        for _ in range(populated_pool._pool_size):
            await populated_pool.get_stream()
        assert populated_pool._available is not None
        assert populated_pool._available.empty()
        mock_session.create_bidirectional_stream.reset_mock()
        new_stream = mock_stream_factory()
        mock_session.create_bidirectional_stream.side_effect = [new_stream]

        stream = await populated_pool.get_stream()

        assert stream is new_stream
        mock_session.create_bidirectional_stream.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_stale_stream_from_pool(
        self,
        populated_pool: StreamPool,
        mock_stream_factory: Callable[[], Any],
        mocker: MockerFixture,
    ) -> None:
        stale_stream = mock_stream_factory()
        type(stale_stream).is_closed = mocker.PropertyMock(return_value=True)
        healthy_stream = mock_stream_factory()
        assert populated_pool._available is not None
        while not populated_pool._available.empty():
            populated_pool._available.get_nowait()
        await populated_pool._available.put(stale_stream)
        await populated_pool._available.put(healthy_stream)
        populated_pool._total_managed_streams = 2

        stream = await populated_pool.get_stream()

        assert stream is healthy_stream
        assert not stream.is_closed
        assert populated_pool._total_managed_streams == 1
        assert populated_pool._available.empty()

    @pytest.mark.asyncio
    async def test_return_closed_stream(self, populated_pool: StreamPool, mocker: MockerFixture) -> None:
        stream_to_return = await populated_pool.get_stream()
        initial_managed = populated_pool._total_managed_streams
        mocker.patch.object(type(stream_to_return), "is_closed", new_callable=mock.PropertyMock, return_value=True)

        await populated_pool.return_stream(stream_to_return)

        assert populated_pool._total_managed_streams == initial_managed - 1

    @pytest.mark.asyncio
    async def test_return_stream_to_full_pool(
        self, populated_pool: StreamPool, mock_stream_factory: Callable[[], Any]
    ) -> None:
        assert populated_pool._available is not None
        assert populated_pool._available.full()
        stream_to_return = mock_stream_factory()

        await populated_pool.return_stream(stream_to_return)

        cast(mock.AsyncMock, stream_to_return.close).assert_awaited_once()
        assert populated_pool._available.full()
        assert populated_pool._total_managed_streams == populated_pool._pool_size

    @pytest.mark.asyncio
    async def test_get_stream_creation_fails(self, populated_pool: StreamPool, mock_session: Any) -> None:
        for _ in range(populated_pool._pool_size):
            await populated_pool.get_stream()
        mock_session.create_bidirectional_stream.side_effect = ConnectionError("Failed")

        with pytest.raises(StreamError, match="Failed to create a new stream"):
            await populated_pool.get_stream()


class TestStreamPoolMaintenance:
    @pytest.mark.asyncio
    async def test_start_maintenance_task_is_idempotent(self, mocker: MockerFixture) -> None:
        async with StreamPool(session=mocker.MagicMock()) as pool:
            task1 = pool._maintenance_task
            assert task1 is not None

            create_task_spy = mocker.spy(asyncio, "create_task")
            pool._start_maintenance_task()

            task2 = pool._maintenance_task
            assert task1 is task2
            create_task_spy.assert_not_called()

            task1.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task1

    @pytest.mark.asyncio
    async def test_maintain_pool_loop_replenishes(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        mock_stream_factory: Callable[[], Any],
    ) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = [None, asyncio.CancelledError]

        async with StreamPool(session=mock_session, pool_size=3, maintenance_interval=0.1) as pool:
            assert pool._available is not None
            pool._total_managed_streams = 1
            while not pool._available.empty():
                pool._available.get_nowait()

            mock_session.create_bidirectional_stream.reset_mock()
            new_streams = [mock_stream_factory() for _ in range(2)]
            mock_session.create_bidirectional_stream.side_effect = new_streams

            await pool._maintain_pool_loop()

            mock_sleep.assert_awaited_with(0.1)
            assert mock_session.create_bidirectional_stream.call_count == 2
            assert pool._total_managed_streams == 3

    @pytest.mark.asyncio
    async def test_maintain_pool_does_nothing_if_full(
        self, populated_pool: StreamPool, mock_session: Any, mocker: MockerFixture
    ) -> None:
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = [None, asyncio.CancelledError]
        mock_session.create_bidirectional_stream.reset_mock()

        await populated_pool._maintain_pool_loop()

        mock_session.create_bidirectional_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_maintain_pool_loop_crashes(
        self,
        mocker: MockerFixture,
        mock_session: Any,
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = RuntimeError("Something went wrong")

        async with StreamPool(session=mock_session, pool_size=2) as pool:
            await pool._maintain_pool_loop()

            mock_logger.error.assert_called_once()
            assert "Stream pool maintenance task crashed" in mock_logger.error.call_args[0][0]

    def test_start_maintenance_task_no_running_loop(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("no running loop"))
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        pool = StreamPool(session=mock_session)

        pool._start_maintenance_task()

        assert pool._maintenance_task is None
        mock_logger.warning.assert_called_with("Could not start pool maintenance task: no running event loop.")
