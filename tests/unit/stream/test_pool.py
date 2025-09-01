"""Unit tests for the pywebtransport.stream.pool module."""

import asyncio
from collections.abc import Callable
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from _pytest.logging import LogCaptureFixture
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
        stream.stream_id = object()
        return stream

    return _factory


class TestStreamPool:
    @pytest.mark.parametrize("pool_size", [0, -1])
    def test_init_invalid_pool_size(self, mock_session: Any, pool_size: int) -> None:
        with pytest.raises(ValueError, match="Pool size must be a positive integer."):
            StreamPool(session=mock_session, pool_size=pool_size)

    def test_create_factory_method(self, mock_session: Any) -> None:
        pool = StreamPool.create(session=mock_session, pool_size=5)

        assert isinstance(pool, StreamPool)
        assert pool._pool_size == 5

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mock_session: Any, mocker: MockerFixture) -> None:
        initialize_mock = mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        close_all_mock = mocker.patch.object(StreamPool, "close_all", new_callable=mocker.AsyncMock)

        async with StreamPool(session=mock_session):
            initialize_mock.assert_awaited_once()

        close_all_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_stream_reuses_from_pool(
        self, mock_session: Any, mock_stream_factory: Callable[[], Any], mocker: MockerFixture
    ) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        async with StreamPool(session=mock_session, pool_size=1) as pool:
            stream = mock_stream_factory()
            pool._available.append(stream)
            pool._total_managed_streams = 1

            reused_stream = await pool.get_stream()

            assert reused_stream is stream
            assert not pool._available
            mock_session.create_bidirectional_stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_stream_discards_stale_stream_from_pool(
        self, mock_session: Any, mock_stream_factory: Callable[[], Any], mocker: MockerFixture
    ) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        async with StreamPool(session=mock_session, pool_size=1) as pool:
            stale_stream = mock_stream_factory()
            type(stale_stream).is_closed = PropertyMock(return_value=True)
            fresh_stream = mock_stream_factory()
            mock_session.create_bidirectional_stream.return_value = fresh_stream
            pool._available.append(stale_stream)
            pool._total_managed_streams = 1

            new_stream = await pool.get_stream()

            assert new_stream is fresh_stream
            assert pool._total_managed_streams == 1
            mock_session.create_bidirectional_stream.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_stream_creation_failure_updates_count(self, mock_session: Any) -> None:
        mock_session.create_bidirectional_stream.side_effect = StreamError("Failed to create")
        async with StreamPool(session=mock_session, pool_size=1) as pool:
            if pool._maintenance_task:
                pool._maintenance_task.cancel()
            with pytest.raises(StreamError):
                await pool.get_stream()

            assert pool._total_managed_streams == 0

    @pytest.mark.asyncio
    async def test_get_stream_with_timeout(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        async with StreamPool(session=mock_session, pool_size=1) as pool:
            pool._total_managed_streams = 1

            with pytest.raises(StreamError, match="Timeout waiting for a stream"):
                await pool.get_stream(timeout=0.01)

    @pytest.mark.asyncio
    async def test_return_stream_to_full_pool_closes_it(
        self, mock_session: Any, mock_stream_factory: Callable[[], Any], mocker: MockerFixture
    ) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        async with StreamPool(session=mock_session, pool_size=1) as pool:
            stream_in_pool = mock_stream_factory()
            pool._available.append(stream_in_pool)
            pool._total_managed_streams = 1
            another_stream = mock_stream_factory()

            await pool.return_stream(another_stream)

            assert len(pool._available) == 1
            assert pool._available[0] is stream_in_pool
            assert pool._total_managed_streams == 1
            cast(AsyncMock, another_stream.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_return_stale_stream_updates_count(
        self, mock_session: Any, mock_stream_factory: Callable[[], Any], mocker: MockerFixture
    ) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        async with StreamPool(session=mock_session, pool_size=1) as pool:
            pool._total_managed_streams = 1
            stale_stream = mock_stream_factory()
            type(stale_stream).is_closed = True

            await pool.return_stream(stale_stream)

            assert not pool._available
            assert pool._total_managed_streams == 0
            cast(AsyncMock, stale_stream.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_stream_concurrent_respects_pool_size(
        self, mock_session: Any, mock_stream_factory: Callable[[], Any]
    ) -> None:
        create_stream_mock = mock_session.create_bidirectional_stream

        async def slow_create() -> Any:
            await asyncio.sleep(0.02)
            return mock_stream_factory()

        create_stream_mock.side_effect = slow_create

        async with StreamPool(session=mock_session, pool_size=1) as pool:
            task_a = asyncio.create_task(pool.get_stream())
            await asyncio.sleep(0.01)
            task_b = asyncio.create_task(pool.get_stream())
            await asyncio.sleep(0.01)

            create_stream_mock.assert_called_once()
            assert not task_b.done()

            stream_a = await task_a
            await pool.return_stream(stream_a)
            stream_b = await asyncio.wait_for(task_b, timeout=1.0)

            assert stream_b is stream_a
            create_stream_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_handles_maintenance_task_states(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        pool = StreamPool(session=mock_session)
        async with pool:
            event = asyncio.Event()

            async def wait_for_event_and_return_none(e: asyncio.Event) -> None:
                await e.wait()

            real_task = asyncio.create_task(wait_for_event_and_return_none(event))
            pool._maintenance_task = real_task
            await pool.close_all()
            assert real_task.cancelled()

            event.set()
            await asyncio.sleep(0)
            done_task = asyncio.create_task(wait_for_event_and_return_none(event))
            pool._maintenance_task = done_task
            await pool.close_all()

            pool._maintenance_task = None
            await pool.close_all()

    @pytest.mark.asyncio
    async def test_close_all_handles_stream_close_errors(
        self,
        mock_session: Any,
        mock_stream_factory: Callable[[], Any],
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        mocker.patch.object(StreamPool, "_initialize_pool", new_callable=mocker.AsyncMock)
        async with StreamPool(session=mock_session, pool_size=2) as pool:
            stream1 = mock_stream_factory()
            stream2 = mock_stream_factory()
            stream1.close.side_effect = ValueError("Close failed")
            pool._available.extend([stream1, stream2])

        stream1.close.assert_awaited_once()
        stream2.close.assert_awaited_once()
        assert "Errors occurred while closing pooled streams" in caplog.text

    @pytest.mark.asyncio
    async def test_internal_methods_are_safe_before_activation(self, mock_session: Any) -> None:
        pool = StreamPool(session=mock_session)
        await pool._fill_pool()
        await pool._initialize_pool()
        await pool._maintain_pool_loop()

    @pytest.mark.asyncio
    async def test_initialize_pool_handles_fill_failure(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch.object(StreamPool, "_fill_pool", side_effect=ValueError("Fill failed"))
        close_all_mock = mocker.patch.object(StreamPool, "close_all", new_callable=mocker.AsyncMock)

        async with StreamPool(session=mock_session):
            pass

        close_all_mock.assert_awaited()

    @pytest.mark.asyncio
    async def test_initialize_pool_is_noop_if_already_managed(self, mock_session: Any, mocker: MockerFixture) -> None:
        fill_pool_mock = mocker.patch.object(StreamPool, "_fill_pool")
        pool = StreamPool(session=mock_session)
        pool._condition = asyncio.Condition()
        pool._total_managed_streams = 1

        await pool._initialize_pool()

        fill_pool_mock.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "side_effects, expected_managed, expected_available",
        [
            ("all_success", 3, 3),
            ("partial_failure", 0, 0),
            ("total_failure", 0, 0),
        ],
    )
    async def test_fill_pool_scenarios(
        self,
        mock_session: Any,
        mock_stream_factory: Callable[[], Any],
        side_effects: str,
        expected_managed: int,
        expected_available: int,
    ) -> None:
        pool = StreamPool(session=mock_session, pool_size=3)
        pool._condition = asyncio.Condition()
        s1, s2, s3 = mock_stream_factory(), mock_stream_factory(), mock_stream_factory()
        effects = {
            "all_success": [s1, s2, s3],
            "partial_failure": [s1, StreamError("Creation failed"), s3],
            "total_failure": [StreamError("Fail 1"), StreamError("Fail 2"), StreamError("Fail 3")],
        }
        mock_session.create_bidirectional_stream.side_effect = effects[side_effects]

        await pool._fill_pool()

        assert pool._total_managed_streams == expected_managed
        assert len(pool._available) == expected_available

    @pytest.mark.asyncio
    async def test_fill_pool_when_session_is_closed(self, mock_session: Any) -> None:
        type(mock_session).is_closed = PropertyMock(return_value=True)
        pool = StreamPool(session=mock_session, pool_size=3)
        pool._condition = asyncio.Condition()

        await pool._fill_pool()

        assert pool._total_managed_streams == 0
        mock_session.create_bidirectional_stream.assert_not_called()

    def test_start_maintenance_task_is_idempotent(self, mock_session: Any, mocker: MockerFixture) -> None:
        create_task_mock = mocker.patch("asyncio.create_task")
        pool = StreamPool(session=mock_session)
        mocker.patch.object(pool, "_maintain_pool_loop", new=MagicMock(return_value=None))

        pool._start_maintenance_task()
        pool._start_maintenance_task()

        create_task_mock.assert_called_once()

    def test_start_maintenance_task_handles_no_event_loop(self, mock_session: Any, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.create_task", side_effect=RuntimeError("no loop"))
        pool = StreamPool(session=mock_session)
        pool._start_maintenance_task()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "initial_managed, should_fill",
        [(0, True), (10, False)],
        ids=["pool_needs_fill", "pool_is_full"],
    )
    async def test_maintenance_loop_scenarios(
        self, mock_session: Any, mocker: MockerFixture, initial_managed: int, should_fill: bool
    ) -> None:
        class StopTest(Exception):
            pass

        fill_pool_mock = mocker.patch.object(StreamPool, "_fill_pool", new_callable=mocker.AsyncMock)
        sleep_mock = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        if should_fill:
            fill_pool_mock.side_effect = StopTest
        else:
            sleep_mock.side_effect = StopTest
        pool = StreamPool(session=mock_session, pool_size=10)
        pool._condition = asyncio.Condition()
        pool._total_managed_streams = initial_managed

        await pool._maintain_pool_loop()

        if should_fill:
            fill_pool_mock.assert_awaited_once()
        else:
            fill_pool_mock.assert_not_called()
            sleep_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_maintenance_loop_crashes_safely(
        self, mock_session: Any, mocker: MockerFixture, caplog: LogCaptureFixture
    ) -> None:
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        mocker.patch.object(StreamPool, "_fill_pool", side_effect=ValueError("Pool filler crashed"))
        pool = StreamPool(session=mock_session)
        pool._condition = asyncio.Condition()

        await pool._maintain_pool_loop()

        assert "Stream pool maintenance task crashed" in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["close_all", "get_stream", "return_stream"])
    async def test_methods_raise_if_not_activated(
        self, method_name: str, mock_session: Any, mock_stream_factory: Callable[[], Any]
    ) -> None:
        pool = StreamPool(session=mock_session)
        method = getattr(pool, method_name)
        args = (mock_stream_factory(),) if method_name == "return_stream" else ()

        with pytest.raises(StreamError, match="StreamPool has not been activated"):
            await method(*args)
