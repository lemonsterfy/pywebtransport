"""Unit tests for the pywebtransport.pool._base module."""

import asyncio
from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport.pool._base import _AsyncObjectPool, _PooledObject


class ConcretePool(_AsyncObjectPool[MagicMock]):
    async def _dispose(self, obj: MagicMock) -> None:
        if hasattr(obj, "close") and asyncio.iscoroutinefunction(obj.close):
            await obj.close()


class TestAsyncObjectPool:
    @pytest.fixture
    def mock_factory(self, mocker: MockerFixture) -> MagicMock:
        async def factory() -> MagicMock:
            obj = MagicMock()
            obj.close = AsyncMock()
            return obj

        return cast(MagicMock, mocker.AsyncMock(side_effect=factory))

    @pytest.fixture
    def pool(self, mock_factory: AsyncMock) -> ConcretePool:
        return ConcretePool(max_size=2, factory=mock_factory)

    @pytest_asyncio.fixture
    async def running_pool(self, pool: ConcretePool) -> AsyncGenerator[ConcretePool, None]:
        async with pool:
            yield pool

    @pytest.mark.asyncio
    async def test_acquire_factory_exception(self, running_pool: ConcretePool, mock_factory: AsyncMock) -> None:
        mock_factory.side_effect = ValueError("Factory failed")
        assert running_pool._semaphore is not None
        initial_semaphore_value = running_pool._semaphore._value

        with pytest.raises(ValueError, match="Factory failed"):
            await running_pool.acquire()

        assert running_pool._semaphore._value == initial_semaphore_value

    @pytest.mark.asyncio
    async def test_acquire_from_closed_pool(self, running_pool: ConcretePool) -> None:
        await running_pool.close()

        with pytest.raises(RuntimeError, match="Cannot acquire from a closed pool"):
            await running_pool.acquire()

    @pytest.mark.asyncio
    async def test_acquire_release_reuse_cycle(self, running_pool: ConcretePool, mock_factory: AsyncMock) -> None:
        obj1 = await running_pool.acquire()
        mock_factory.assert_awaited_once()
        assert running_pool._active_count == 1

        await running_pool.release(obj1)

        obj2 = await running_pool.acquire()
        mock_factory.assert_awaited_once()
        assert obj1 is obj2

    @pytest.mark.asyncio
    async def test_acquire_respects_max_size(self, running_pool: ConcretePool) -> None:
        obj1 = await running_pool.acquire()
        obj2 = await running_pool.acquire()

        acquire_task = asyncio.create_task(running_pool.acquire())
        await asyncio.sleep(0)
        assert not acquire_task.done()

        await running_pool.release(obj1)
        await asyncio.sleep(0)
        assert acquire_task.done()

        acquired_obj = await acquire_task
        assert acquired_obj is obj1

        await running_pool.release(obj2)
        await running_pool.release(acquired_obj)

    @pytest.mark.asyncio
    async def test_acquire_without_context_manager(self, pool: ConcretePool) -> None:
        with pytest.raises(RuntimeError, match="has not been activated"):
            await pool.acquire()

    @pytest.mark.asyncio
    async def test_aenter_idempotency(self, pool: ConcretePool) -> None:
        await pool.__aenter__()
        lock_1 = pool._lock
        sem_1 = pool._semaphore

        await pool.__aenter__()

        assert pool._lock is lock_1
        assert pool._semaphore is sem_1

        await pool.__aexit__(None, None, None)

    @pytest.mark.asyncio
    async def test_close_disposes_pooled_objects(self, running_pool: ConcretePool) -> None:
        obj1 = await running_pool.acquire()
        obj2 = await running_pool.acquire()
        await running_pool.release(obj1)
        await running_pool.release(obj2)

        await running_pool.close()

        obj1.close.assert_awaited_once()
        obj2.close.assert_awaited_once()
        assert len(running_pool._pool) == 0

    @pytest.mark.asyncio
    async def test_close_idempotency(self, running_pool: ConcretePool) -> None:
        obj = await running_pool.acquire()
        await running_pool.release(obj)

        await running_pool.close()
        await running_pool.close()

        obj.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_uninitialized_pool(self, pool: ConcretePool) -> None:
        assert pool._lock is None

        await pool.close()

        assert pool._closed

    @pytest.mark.asyncio
    async def test_close_with_dispose_exception(self, running_pool: ConcretePool, mocker: MockerFixture) -> None:
        obj = await running_pool.acquire()
        await running_pool.release(obj)

        async def faulty_dispose(o: MagicMock) -> None:
            raise ValueError("Dispose failed")

        mocker.patch.object(running_pool, "_dispose", side_effect=faulty_dispose)

        with pytest.raises(RuntimeError, match="Errors occurred during pool cleanup"):
            await running_pool.close()

    @pytest.mark.asyncio
    async def test_context_manager_closes_pool(self, mock_factory: AsyncMock) -> None:
        pool_instance = ConcretePool(max_size=1, factory=mock_factory)

        async with pool_instance as pool:
            assert not pool._closed
            assert pool._lock is not None
            assert pool._semaphore is not None

        assert pool_instance._closed

    @pytest.mark.asyncio
    async def test_get_returns_pooled_object_manager(self, running_pool: ConcretePool) -> None:
        manager = running_pool.get()

        assert isinstance(manager, _PooledObject)
        assert manager._pool is running_pool

    def test_init_invalid_max_size(self, mock_factory: AsyncMock) -> None:
        with pytest.raises(ValueError, match="must be a positive integer"):
            ConcretePool(max_size=0, factory=mock_factory)
        with pytest.raises(ValueError, match="must be a positive integer"):
            ConcretePool(max_size=-1, factory=mock_factory)

    @pytest.mark.asyncio
    async def test_release_on_uninitialized_closed_pool(self, pool: ConcretePool) -> None:
        await pool.close()
        obj = MagicMock()
        obj.close = AsyncMock()

        await pool.release(obj)

        obj.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_release_to_closed_pool(self, running_pool: ConcretePool) -> None:
        obj = await running_pool.acquire()
        await running_pool.close()

        await running_pool.release(obj)

        obj.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_release_without_context_manager(self, pool: ConcretePool) -> None:
        obj = MagicMock()

        with pytest.raises(RuntimeError, match="has not been activated"):
            await pool.release(obj)


class TestPooledObject:
    @pytest.fixture
    def mock_factory(self, mocker: MockerFixture) -> MagicMock:
        async def factory() -> MagicMock:
            return MagicMock()

        return cast(MagicMock, mocker.AsyncMock(side_effect=factory))

    @pytest.fixture
    def pool(self, mock_factory: AsyncMock) -> ConcretePool:
        return ConcretePool(max_size=1, factory=mock_factory)

    @pytest_asyncio.fixture
    async def running_pool(self, pool: ConcretePool) -> AsyncGenerator[ConcretePool, None]:
        async with pool:
            yield pool

    @pytest.mark.asyncio
    async def test_context_manager_acquire_release(self, running_pool: ConcretePool, mocker: MockerFixture) -> None:
        acquire_spy = mocker.spy(running_pool, "acquire")
        release_spy = mocker.spy(running_pool, "release")

        async with _PooledObject(pool=running_pool) as obj:
            assert obj is not None
            acquire_spy.assert_awaited_once()
            release_spy.assert_not_awaited()

        release_spy.assert_awaited_once_with(obj)

    @pytest.mark.asyncio
    async def test_context_manager_handles_no_object(self, running_pool: ConcretePool, mocker: MockerFixture) -> None:
        release_spy = mocker.spy(running_pool, "release")
        pooled_obj = _PooledObject(pool=running_pool)
        pooled_obj._obj = None

        await pooled_obj.__aexit__(None, None, None)

        release_spy.assert_not_awaited()
