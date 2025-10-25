"""Generic, reusable asynchronous object pool."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import AsyncContextManager, Generic, Self, TypeVar

__all__: list[str] = []

T = TypeVar("T")


class _AsyncObjectPool(ABC, Generic[T]):
    """A generic, robust asynchronous object pool implementation."""

    def __init__(self, *, max_size: int, factory: Callable[[], Awaitable[T]]) -> None:
        """Initialize the asynchronous object pool."""
        if max_size <= 0:
            raise ValueError("Pool max_size must be a positive integer.")

        self._factory = factory
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(value=max_size)
        self._pool: deque[T] = deque()
        self._active_count = 0
        self._closed = False

    async def __aenter__(self) -> Self:
        """Enter the async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and close the pool."""
        await self.close()

    async def close(self) -> None:
        """Close the pool and dispose of all currently available objects."""
        if self._closed:
            return

        self._closed = True

        async with self._lock:
            close_tasks = [self._dispose(obj) for obj in self._pool]
            self._pool.clear()
            await asyncio.gather(*close_tasks, return_exceptions=True)

    async def acquire(self) -> T:
        """Acquire an object from the pool, creating a new one if necessary."""
        if self._closed:
            raise RuntimeError("Cannot acquire from a closed pool.")

        await self._semaphore.acquire()

        async with self._lock:
            if self._pool:
                return self._pool.popleft()

        try:
            new_obj = await self._factory()
            async with self._lock:
                self._active_count += 1
            return new_obj
        except Exception:
            self._semaphore.release()
            raise

    def get(self) -> AsyncContextManager[T]:
        """Return an async context manager for acquiring and automatically releasing an object."""
        return _PooledObject(pool=self)

    async def release(self, obj: T) -> None:
        """Release an object, returning it to the pool."""
        if self._closed:
            await self._dispose(obj)
            return

        async with self._lock:
            self._pool.append(obj)

        self._semaphore.release()

    @abstractmethod
    async def _dispose(self, obj: T) -> None:
        """Dispose of a pooled object. Subclasses must implement this."""
        raise NotImplementedError


class _PooledObject(AsyncContextManager[T]):
    """An async context manager for safely acquiring and releasing a pooled object."""

    def __init__(self, pool: _AsyncObjectPool[T]) -> None:
        """Initialize the pooled object context manager."""
        self._pool = pool
        self._obj: T | None = None

    async def __aenter__(self) -> T:
        """Acquire the object from the pool."""
        self._obj = await self._pool.acquire()
        return self._obj

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Release the object back to the pool."""
        if self._obj is not None:
            await self._pool.release(self._obj)
