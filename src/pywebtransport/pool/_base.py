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
        self._lock: asyncio.Lock | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._pool: deque[T] = deque()
        self._active_count = 0
        self._closed = False

    async def __aenter__(self) -> Self:
        """Enter the async context and initialize async resources."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(value=self._max_size)
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context and close the pool."""
        await self.close()

    async def close(self) -> None:
        """Close the pool and dispose of all currently available objects."""
        if self._closed:
            return

        self._closed = True

        objects_to_dispose: list[T] = []
        if self._lock:
            async with self._lock:
                objects_to_dispose = list(self._pool)
                self._pool.clear()
        else:
            objects_to_dispose = list(self._pool)
            self._pool.clear()

        if objects_to_dispose:
            try:
                async with asyncio.TaskGroup() as tg:
                    for obj in objects_to_dispose:
                        tg.create_task(coro=self._dispose(obj))
            except* Exception as eg:
                raise RuntimeError(f"Errors occurred during pool cleanup: {eg.exceptions}") from eg

    async def acquire(self) -> T:
        """Acquire an object from the pool, creating a new one if necessary."""
        if self._closed:
            raise RuntimeError("Cannot acquire from a closed pool.")
        if self._lock is None or self._semaphore is None:
            raise RuntimeError(
                "_AsyncObjectPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

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
        if self._lock is None or self._semaphore is None:
            if self._closed:
                await self._dispose(obj)
                return
            raise RuntimeError(
                "_AsyncObjectPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

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
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Release the object back to the pool."""
        if self._obj is not None:
            await self._pool.release(self._obj)
