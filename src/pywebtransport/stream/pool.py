"""
WebTransport stream pooling for efficient stream reuse.
"""

import asyncio
from types import TracebackType
from typing import TYPE_CHECKING, List, Optional, Type

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
        session: "WebTransportSession",
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

        self._available: asyncio.Queue[WebTransportStream] = asyncio.Queue(maxsize=pool_size)
        self._total_managed_streams = 0
        self._lock = asyncio.Lock()
        self._maintenance_task: Optional[asyncio.Task[None]] = None

    @classmethod
    def create(
        cls,
        session: "WebTransportSession",
        *,
        pool_size: int = 10,
    ) -> "StreamPool":
        """Factory method to create a new stream pool instance."""
        return cls(session, pool_size=pool_size)

    async def __aenter__(self) -> "StreamPool":
        """Enter the async context and initialize the pool."""
        await self._initialize_pool()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the async context and close all streams in the pool."""
        await self.close_all()

    async def close_all(self) -> None:
        """Close all idle streams and shut down the pool."""
        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass

        streams_to_close: List[WebTransportStream] = []
        while not self._available.empty():
            try:
                streams_to_close.append(self._available.get_nowait())
            except asyncio.QueueEmpty:
                break

        if streams_to_close:
            close_tasks = [s.close() for s in streams_to_close]
            await asyncio.gather(*close_tasks, return_exceptions=True)
            logger.info(f"Closed {len(streams_to_close)} idle streams from the pool.")

        async with self._lock:
            self._total_managed_streams = 0

    async def get_stream(self, *, timeout: Optional[float] = None) -> WebTransportStream:
        """Get a stream from the pool, creating a new one if necessary."""
        while not self._available.empty():
            try:
                stream = self._available.get_nowait()
                if not stream.is_closed:
                    logger.debug(f"Reusing stream {stream.stream_id} from pool.")
                    return stream
                else:
                    logger.debug(f"Discarding stale stream {stream.stream_id} from pool.")
                    async with self._lock:
                        self._total_managed_streams -= 1
            except asyncio.QueueEmpty:
                break

        logger.debug("Pool is empty, creating a new unpooled stream.")
        try:
            return await self._session.create_bidirectional_stream()
        except Exception as e:
            raise StreamError("Failed to create a new stream as pool was empty") from e

    async def return_stream(self, stream: WebTransportStream) -> None:
        """Return a stream to the pool for potential reuse."""
        if stream.is_closed:
            async with self._lock:
                if self._total_managed_streams > self._available.qsize():
                    self._total_managed_streams -= 1
            return

        try:
            self._available.put_nowait(stream)
            logger.debug(f"Returned stream {stream.stream_id} to pool.")
        except asyncio.QueueFull:
            logger.debug(f"Stream pool is full, closing returned stream {stream.stream_id}.")
            await stream.close()

    async def _initialize_pool(self) -> None:
        """Initialize the pool by pre-filling it with new streams."""
        try:
            async with self._lock:
                if self._total_managed_streams > 0:
                    return
                await self._fill_pool()
                self._start_maintenance_task()
                logger.info(f"Stream pool initialized with {self._total_managed_streams} streams.")
        except Exception as e:
            logger.error(f"Error initializing stream pool: {e}")
            await self.close_all()
            raise

    async def _fill_pool(self) -> None:
        """Create new streams until the pool reaches its target size."""
        while self._total_managed_streams < self._pool_size and self._available.qsize() < self._pool_size:
            if self._session.is_closed:
                logger.warning("Session closed during stream pool replenishment.")
                break
            try:
                stream = await self._session.create_bidirectional_stream()
                await self._available.put(stream)
                self._total_managed_streams += 1
            except Exception as e:
                logger.error(f"Failed to create a new stream for the pool: {e}")
                break

    def _start_maintenance_task(self) -> None:
        """Start the periodic pool maintenance task if not already running."""
        if self._maintenance_task is None:
            try:
                self._maintenance_task = asyncio.create_task(self._maintain_pool_loop())
            except RuntimeError:
                self._maintenance_task = None
                logger.warning("Could not start pool maintenance task: no running event loop.")

    async def _maintain_pool_loop(self) -> None:
        """Periodically check and replenish the stream pool."""
        try:
            while True:
                await asyncio.sleep(self._maintenance_interval)
                async with self._lock:
                    current_total = self._total_managed_streams
                    if current_total < self._pool_size:
                        logger.debug(f"Replenishing pool. Size ({current_total}) is below target ({self._pool_size}).")
                        await self._fill_pool()
        except asyncio.CancelledError:
            logger.info("Stream pool maintenance task cancelled.")
        except Exception as e:
            logger.error(f"Stream pool maintenance task crashed: {e}", exc_info=e)
