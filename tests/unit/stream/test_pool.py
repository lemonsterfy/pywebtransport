"""Unit tests for the pywebtransport.stream.pool module."""

import asyncio
from typing import Any, AsyncGenerator, Callable

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
async def stream_pool(mock_session: Any) -> AsyncGenerator[StreamPool, None]:
    pool = StreamPool(session=mock_session)
    yield pool
    if pool._maintenance_task and not pool._maintenance_task.done():
        pool._maintenance_task.cancel()
        try:
            await pool._maintenance_task
        except asyncio.CancelledError:
            pass


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
    async def test_initialize_pool_is_idempotent(self, mock_session: Any, mocker: MockerFixture) -> None:
        pool = StreamPool(session=mock_session, pool_size=2)
        mocker.patch.object(pool, "_fill_pool", wraps=pool._fill_pool)

        await pool._initialize_pool()
        assert pool._fill_pool.call_count == 1
        assert pool._total_managed_streams == 2

        await pool._initialize_pool()
        assert pool._fill_pool.call_count == 1
        assert pool._total_managed_streams == 2

    async def test_close_all_on_uninitialized_pool(self, mock_session: Any) -> None:
        pool = StreamPool(session=mock_session)

        await pool.close_all()

        assert pool._total_managed_streams == 0

    async def test_async_context_manager_handles_exception(self, mock_session: Any, mocker: MockerFixture) -> None:
        pool = StreamPool(session=mock_session)
        close_all_mock = mocker.patch.object(pool, "close_all", new_callable=mocker.AsyncMock)

        with pytest.raises(ValueError, match="Test Exception"):
            async with pool:
                raise ValueError("Test Exception")

        close_all_mock.assert_awaited_once()

    async def test_fill_pool_stops_if_session_closed(self, mock_session: Any, mocker: MockerFixture) -> None:
        pool = StreamPool(session=mock_session, pool_size=5)
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        type(mock_session).is_closed = mocker.PropertyMock(side_effect=[False, False, True])

        await pool._initialize_pool()

        assert pool._total_managed_streams == 2
        mock_logger.warning.assert_called_once_with("Session closed during stream pool replenishment.")

    async def test_initialize_pool_no_exception_raised(self, mock_session: Any, mocker: MockerFixture) -> None:
        pool = StreamPool(session=mock_session)
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        mock_session.create_bidirectional_stream.side_effect = RuntimeError("Creation failed")

        await pool._initialize_pool()

        mock_logger.error.assert_called_with("Failed to create a new stream for the pool: Creation failed")
        assert pool._total_managed_streams == 0
        assert pool._available.empty()

    async def test_close_all_cancels_maintenance_task(self, mock_session: Any, mocker: MockerFixture) -> None:
        pool = StreamPool(session=mock_session)
        mocker.patch("asyncio.sleep", side_effect=asyncio.CancelledError)
        await pool._initialize_pool()
        task = pool._maintenance_task
        assert task is not None and not task.done()

        await pool.close_all()

        assert task.done()

    async def test_close_all_waits_for_cancelled_task(self, mock_session: Any, mocker: MockerFixture) -> None:
        pool = StreamPool(session=mock_session)
        task_is_running = asyncio.Event()

        async def controlled_coro() -> None:
            task_is_running.set()
            await asyncio.sleep(30)

        mocker.patch.object(pool, "_maintain_pool_loop", side_effect=controlled_coro)
        await pool._initialize_pool()
        await task_is_running.wait()

        await pool.close_all()

        assert pool._maintenance_task.done()


class TestStreamPoolOperations:
    @pytest.fixture(autouse=True)
    async def setup(
        self,
        stream_pool: StreamPool,
        mock_session: Any,
        mock_stream_factory: Callable[[], Any],
    ) -> None:
        streams = [mock_stream_factory() for _ in range(stream_pool._pool_size)]
        mock_session.create_bidirectional_stream.side_effect = streams
        await stream_pool._initialize_pool()

    async def test_get_stream_from_pool(self, stream_pool: StreamPool) -> None:
        initial_qsize = stream_pool._available.qsize()

        stream = await stream_pool.get_stream()

        assert stream is not None
        assert not stream.is_closed
        assert stream_pool._available.qsize() == initial_qsize - 1

    async def test_return_stream_to_pool(self, stream_pool: StreamPool, mock_stream_factory: Callable[[], Any]) -> None:
        await stream_pool.close_all()
        assert stream_pool._available.empty()
        stream_to_return = mock_stream_factory()

        await stream_pool.return_stream(stream_to_return)

        assert stream_pool._available.qsize() == 1
        retrieved_stream = await stream_pool.get_stream()
        assert retrieved_stream is stream_to_return

    async def test_get_stream_from_empty_pool(
        self,
        stream_pool: StreamPool,
        mock_session: Any,
        mock_stream_factory: Callable[[], Any],
    ) -> None:
        for _ in range(stream_pool._pool_size):
            await stream_pool.get_stream()
        assert stream_pool._available.empty()
        mock_session.create_bidirectional_stream.reset_mock()
        new_stream = mock_stream_factory()
        mock_session.create_bidirectional_stream.side_effect = [new_stream]

        stream = await stream_pool.get_stream()

        assert stream is new_stream
        mock_session.create_bidirectional_stream.assert_awaited_once()

    async def test_get_stale_stream_from_pool(
        self,
        stream_pool: StreamPool,
        mock_stream_factory: Callable[[], Any],
        mocker: MockerFixture,
    ) -> None:
        stale_stream = mock_stream_factory()
        type(stale_stream).is_closed = mocker.PropertyMock(return_value=True)
        healthy_stream = mock_stream_factory()
        await stream_pool.close_all()
        await stream_pool._available.put(stale_stream)
        await stream_pool._available.put(healthy_stream)
        stream_pool._total_managed_streams = 2

        stream = await stream_pool.get_stream()

        assert stream is healthy_stream
        assert stream_pool._total_managed_streams == 1

    async def test_return_closed_stream(
        self, stream_pool: StreamPool, mock_stream_factory: Callable[[], Any], mocker: MockerFixture
    ) -> None:
        await stream_pool.get_stream()
        initial_managed = stream_pool._total_managed_streams
        initial_qsize = stream_pool._available.qsize()
        stream_to_return = mock_stream_factory()
        type(stream_to_return).is_closed = mocker.PropertyMock(return_value=True)

        await stream_pool.return_stream(stream_to_return)

        assert stream_pool._available.qsize() == initial_qsize
        assert stream_pool._total_managed_streams == initial_managed - 1

    async def test_return_stream_to_full_pool(
        self, stream_pool: StreamPool, mock_stream_factory: Callable[[], Any]
    ) -> None:
        assert stream_pool._available.full()
        stream_to_return = mock_stream_factory()

        await stream_pool.return_stream(stream_to_return)

        stream_to_return.close.assert_awaited_once()
        assert stream_pool._available.full()

    async def test_get_stream_creation_fails(self, stream_pool: StreamPool, mock_session: Any) -> None:
        for _ in range(stream_pool._pool_size):
            await stream_pool.get_stream()
        mock_session.create_bidirectional_stream.side_effect = ConnectionError("Failed")

        with pytest.raises(StreamError, match="Failed to create a new stream"):
            await stream_pool.get_stream()


class TestStreamPoolMaintenance:
    async def test_start_maintenance_task_is_idempotent(self, mock_session: Any, mocker: MockerFixture) -> None:
        pool = StreamPool(session=mock_session)
        create_task_mock = mocker.patch("asyncio.create_task")
        mocker.patch.object(pool, "_maintain_pool_loop", new=mocker.MagicMock())

        pool._start_maintenance_task()
        create_task_mock.assert_called_once()

        pool._start_maintenance_task()
        create_task_mock.assert_called_once()

    async def test_maintain_pool_loop_replenishes(
        self,
        mocker: MockerFixture,
        mock_session: Any,
        mock_stream_factory: Callable[[], Any],
    ) -> None:
        mock_sleep = mocker.patch("pywebtransport.stream.pool.asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = [None, asyncio.CancelledError]
        pool = StreamPool(session=mock_session, pool_size=3, maintenance_interval=0.1)
        pool._total_managed_streams = 1
        new_streams = [mock_stream_factory(), mock_stream_factory()]
        mock_session.create_bidirectional_stream.side_effect = new_streams

        await pool._maintain_pool_loop()

        mock_sleep.assert_awaited_with(0.1)
        assert mock_session.create_bidirectional_stream.call_count == 2
        assert pool._total_managed_streams == 3
        assert pool._available.qsize() == 2

    async def test_maintain_pool_does_nothing_if_full(self, mock_session: Any, mocker: MockerFixture) -> None:
        mock_sleep = mocker.patch("pywebtransport.stream.pool.asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = [None, asyncio.CancelledError]
        pool = StreamPool(session=mock_session, pool_size=3)
        pool._total_managed_streams = 3

        await pool._maintain_pool_loop()

        mock_session.create_bidirectional_stream.assert_not_called()

    async def test_maintain_pool_loop_crashes(
        self,
        mocker: MockerFixture,
        mock_session: Any,
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        mock_sleep = mocker.patch("pywebtransport.stream.pool.asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_sleep.side_effect = RuntimeError("Something went wrong")
        pool = StreamPool(session=mock_session, pool_size=2)

        await pool._maintain_pool_loop()

        mock_logger.error.assert_called_once()
        assert "Stream pool maintenance task crashed" in mock_logger.error.call_args[0][0]

    def test_start_maintenance_task_no_running_loop(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("no running loop"))
        mock_logger = mocker.patch("pywebtransport.stream.pool.logger")
        pool = StreamPool(session=mock_session)
        mocker.patch.object(pool, "_maintain_pool_loop", new=mocker.MagicMock())

        pool._start_maintenance_task()

        assert pool._maintenance_task is None
        mock_logger.warning.assert_called_with("Could not start pool maintenance task: no running event loop.")
