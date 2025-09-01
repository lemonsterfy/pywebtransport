"""
WebTransport stream pooling for efficient stream reuse.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import TYPE_CHECKING, Self, Type

from pywebtransport.exceptions import StreamError
from pywebtransport.stream.stream import WebTransportStream
from pywebtransport.utils import get_logger

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__ = ["StreamPool"]

logger = get_logger("stream.pool")


class StreamPool:
    """Manages a pool of reusable WebTransport streams for a session."""

    def __init__(
        self,
        session: WebTransportSession,
        *,
        pool_size: int = 10,
        maintenance_interval: float = 60.0,
    ):
        """Initialize the stream pool."""
        if pool_size <= 0:
            raise ValueError("Pool size must be a positive integer.")

        self._session = session
        self._pool_size = pool_size
        self._maintenance_interval = maintenance_interval
        self._available: list[WebTransportStream] = []
        self._total_managed_streams = 0
        self._condition: asyncio.Condition | None = None
        self._maintenance_task: asyncio.Task[None] | None = None

    @classmethod
    def create(
        cls,
        session: WebTransportSession,
        *,
        pool_size: int = 10,
    ) -> Self:
        """Create a new stream pool instance."""
        return cls(session, pool_size=pool_size)

    async def __aenter__(self) -> Self:
        """Enter the async context and initialize the pool."""
        self._condition = asyncio.Condition()
        await self._initialize_pool()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and close all streams in the pool."""
        await self.close_all()

    async def close_all(self) -> None:
        """Close all idle streams and shut down the pool."""
        if self._condition is None:
            raise StreamError(
                "StreamPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass

        streams_to_close: list[WebTransportStream] = []
        async with self._condition:
            streams_to_close.extend(self._available)
            self._available.clear()
            self._total_managed_streams = 0

        if streams_to_close:
            try:
                async with asyncio.TaskGroup() as tg:
                    for s in streams_to_close:
                        tg.create_task(s.close())
            except* Exception as eg:
                logger.error(f"Errors occurred while closing pooled streams: {eg.exceptions}")
            logger.info(f"Closed {len(streams_to_close)} idle streams from the pool.")

    async def get_stream(self, *, timeout: float | None = None) -> WebTransportStream:
        """Get a stream from the pool, creating a new one if necessary."""
        if self._condition is None:
            raise StreamError(
                "StreamPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        async with self._condition:
            while True:
                while self._available:
                    stream = self._available.pop(0)
                    if not stream.is_closed:
                        logger.debug(f"Reusing stream {stream.stream_id} from pool.")
                        return stream
                    else:
                        logger.debug(f"Discarding stale stream {stream.stream_id} from pool.")
                        self._total_managed_streams -= 1

                if self._total_managed_streams < self._pool_size:
                    self._total_managed_streams += 1
                    break

                logger.debug("Pool is full. Waiting for a stream to be returned.")
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    raise StreamError(f"Timeout waiting for a stream from the pool after {timeout}s.") from None

        try:
            logger.debug("Creating new stream as pool was empty or depleted.")
            return await self._session.create_bidirectional_stream()
        except Exception:
            async with self._condition:
                self._total_managed_streams -= 1
                self._condition.notify()
            raise

    async def return_stream(self, stream: WebTransportStream) -> None:
        """Return a stream to the pool for potential reuse."""
        if self._condition is None:
            raise StreamError(
                "StreamPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        should_close = stream.is_closed
        async with self._condition:
            if not should_close:
                if len(self._available) >= self._pool_size:
                    should_close = True
                else:
                    self._available.append(stream)
                    logger.debug(f"Returned stream {stream.stream_id} to pool.")
                    self._condition.notify()

            if should_close:
                if self._total_managed_streams > len(self._available):
                    self._total_managed_streams -= 1
                    self._condition.notify()

        if should_close:
            await stream.close()

    async def _fill_pool(self) -> None:
        """Create new streams concurrently until the pool reaches its target size."""
        if self._condition is None:
            return
        if self._session.is_closed:
            logger.warning("Session closed, cannot replenish stream pool.")
            return

        created_streams: list[WebTransportStream] = []
        needed = 0
        async with self._condition:
            needed = self._pool_size - self._total_managed_streams
            if needed <= 0:
                return
            self._total_managed_streams += needed

        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(self._session.create_bidirectional_stream()) for _ in range(needed)]
            created_streams = [task.result() for task in tasks if task.done() and not task.exception()]
        except* Exception as eg:
            logger.error(f"Failed to create {needed} streams for the pool: {eg.exceptions}")
            async with self._condition:
                self._total_managed_streams -= needed
                self._condition.notify_all()

        if created_streams:
            async with self._condition:
                successful_count = len(created_streams)
                if successful_count < needed:
                    self._total_managed_streams -= needed - successful_count
                self._available.extend(created_streams)
                if successful_count > 0:
                    self._condition.notify_all()

    async def _initialize_pool(self) -> None:
        """Initialize the pool by pre-filling it with new streams."""
        if self._condition is None:
            return

        needs_fill = False
        async with self._condition:
            if self._total_managed_streams == 0:
                needs_fill = True

        if needs_fill:
            try:
                await self._fill_pool()
                self._start_maintenance_task()
                logger.info(f"Stream pool initialized with {self._total_managed_streams} streams.")
            except Exception as e:
                logger.error(f"Error initializing stream pool: {e}")
                await self.close_all()

    async def _maintain_pool_loop(self) -> None:
        """Periodically check and replenish the stream pool."""
        if self._condition is None:
            return

        try:
            while True:
                await asyncio.sleep(self._maintenance_interval)
                needs_fill = False
                async with self._condition:
                    if self._total_managed_streams < self._pool_size:
                        logger.debug(
                            f"Replenishing pool. Size ({self._total_managed_streams}) "
                            f"is below target ({self._pool_size})."
                        )
                        needs_fill = True
                if needs_fill:
                    await self._fill_pool()
        except asyncio.CancelledError:
            logger.info("Stream pool maintenance task cancelled.")
        except Exception as e:
            logger.error(f"Stream pool maintenance task crashed: {e}", exc_info=e)

    def _start_maintenance_task(self) -> None:
        """Start the periodic pool maintenance task if not already running."""
        if self._maintenance_task is None:
            coro = self._maintain_pool_loop()
            try:
                self._maintenance_task = asyncio.create_task(coro)
            except RuntimeError:
                coro.close()
                self._maintenance_task = None
                logger.warning("Could not start pool maintenance task: no running event loop.")
