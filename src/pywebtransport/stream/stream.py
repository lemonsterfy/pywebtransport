"""Core objects representing a reliable WebTransport stream."""

from __future__ import annotations

import asyncio
import time
import weakref
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from pywebtransport.constants import DEFAULT_BUFFER_SIZE, DEFAULT_STREAM_LINE_LIMIT, MAX_BUFFER_SIZE
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import FlowControlError, StreamError, TimeoutError
from pywebtransport.types import Data, EventType, StreamDirection, StreamId, StreamState
from pywebtransport.utils import ensure_bytes, format_duration, get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__: list[str] = [
    "StreamDiagnostics",
    "StreamStats",
    "WebTransportReceiveStream",
    "WebTransportSendStream",
    "WebTransportStream",
]

logger = get_logger(name=__name__)


@dataclass(frozen=True, kw_only=True)
class StreamDiagnostics:
    """A structured, immutable snapshot of a stream's health."""

    stats: StreamStats
    read_buffer_size: int
    write_buffer_size: int


@dataclass(kw_only=True)
class StreamStats:
    """Statistics for a WebTransport stream."""

    stream_id: StreamId
    created_at: float
    closed_at: float | None = None
    bytes_sent: int = 0
    bytes_received: int = 0
    writes_count: int = 0
    reads_count: int = 0
    total_write_time: float = 0.0
    total_read_time: float = 0.0
    max_write_time: float = 0.0
    max_read_time: float = 0.0
    write_errors: int = 0
    read_errors: int = 0
    flow_control_errors: int = 0

    @property
    def avg_read_time(self) -> float:
        """Get the average time for a read operation in seconds."""
        return self.total_read_time / max(1, self.reads_count)

    @property
    def avg_write_time(self) -> float:
        """Get the average time for a write operation in seconds."""
        return self.total_write_time / max(1, self.writes_count)

    @property
    def uptime(self) -> float:
        """Get the total uptime of the stream in seconds."""
        end_time = self.closed_at or get_timestamp()
        return end_time - self.created_at

    def to_dict(self) -> dict[str, Any]:
        """Convert the statistics to a dictionary."""
        return asdict(obj=self)


class _StreamBuffer:
    """An efficient, deque-based buffer for asynchronous data streams."""

    def __init__(self, *, max_size: int = 65536) -> None:
        """Initialize the stream buffer."""
        self._max_size = max_size
        self._buffer: deque[bytes] = deque()
        self._size = 0
        self._eof = False
        self._lock: asyncio.Lock | None = None
        self._data_available: asyncio.Event | None = None

    @property
    def at_eof(self) -> bool:
        """Check if the buffer has reached the end of the stream."""
        return self._eof and not self._buffer

    @property
    def eof(self) -> bool:
        """Check if the end-of-stream has been signaled."""
        return self._eof

    @property
    def size(self) -> int:
        """Get the current number of bytes in the buffer."""
        return self._size

    async def initialize(self) -> None:
        """Initialize asyncio resources for the buffer."""
        if self._lock is not None:
            return

        self._lock = asyncio.Lock()
        self._data_available = asyncio.Event()

    async def feed_data(self, *, data: bytes, eof: bool = False) -> None:
        """Asynchronously feed data into the buffer."""
        if self._lock is None or self._data_available is None:
            raise StreamError(
                message="_StreamBuffer has not been initialized. Its owner must call 'await buffer.initialize()'."
            )
        if self._eof:
            return

        async with self._lock:
            if data:
                self._buffer.append(data)
                self._size += len(data)
                self._data_available.set()
            if eof:
                self._eof = True
                self._data_available.set()

    def find_separator(self, *, separator: bytes) -> int:
        """Find a separator in the buffer and return the length to read."""
        if not self._buffer:
            return -1

        first_chunk = self._buffer[0]
        idx = first_chunk.find(separator)
        if idx != -1:
            return idx + len(separator)

        peek_data = b"".join(self._buffer)
        idx = peek_data.find(separator)
        if idx != -1:
            return idx + len(separator)

        return -1

    async def read(self, *, size: int = -1, timeout: float | None = None) -> tuple[bytes, bool]:
        """Asynchronously read data from the buffer."""
        if self._lock is None or self._data_available is None:
            raise StreamError(
                message="_StreamBuffer has not been initialized. Its owner must call 'await buffer.initialize()'."
            )

        async def _read_logic() -> bytes:
            if self._lock is None or self._data_available is None:
                raise StreamError(
                    message="_StreamBuffer has not been initialized. Its owner must call 'await buffer.initialize()'."
                )
            while True:
                async with self._lock:
                    if self._buffer:
                        read_size = self._size if size == -1 else size
                        if read_size <= 0:
                            return b""

                        chunks = []
                        bytes_read = 0
                        while bytes_read < read_size and self._buffer:
                            chunk = self._buffer[0]
                            needed = read_size - bytes_read
                            if len(chunk) > needed:
                                data_part = chunk[:needed]
                                self._buffer[0] = chunk[needed:]
                                chunks.append(data_part)
                                bytes_read += len(data_part)
                                self._size -= len(data_part)
                            else:
                                data_part = self._buffer.popleft()
                                chunks.append(data_part)
                                bytes_read += len(data_part)
                                self._size -= len(data_part)

                        if not self._buffer and not self._eof:
                            self._data_available.clear()

                        return b"".join(chunks)

                    if self._eof:
                        return b""
                await self.wait_for_data()

        try:
            data = await asyncio.wait_for(_read_logic(), timeout=timeout)
            is_eof_after_read = self._eof and not self._buffer
            return data, is_eof_after_read
        except asyncio.TimeoutError:
            raise TimeoutError(message=f"Read timeout after {timeout}s") from None

    async def wait_for_data(self) -> None:
        """Wait for new data to be available and consume the signal."""
        if self._data_available is None:
            raise StreamError(message="_StreamBuffer not initialized.")
        if self.at_eof:
            return
        await self._data_available.wait()
        self._data_available.clear()


class _StreamBase:
    """Internal mixin for common stream functionality."""

    _stats: StreamStats
    _stream_id: StreamId
    _direction: StreamDirection
    _state: StreamState
    _closed_future: asyncio.Future[None] | None = None
    _is_initialized: bool = False

    @property
    def diagnostics(self) -> StreamDiagnostics:
        """Get a snapshot of the stream's diagnostics and statistics."""
        return StreamDiagnostics(
            stats=self._stats,
            read_buffer_size=getattr(getattr(self, "_buffer", None), "size", 0),
            write_buffer_size=getattr(self, "_write_buffer_size", 0),
        )

    @property
    def direction(self) -> StreamDirection:
        """Get the direction of the stream."""
        return self._direction

    @property
    def is_closed(self) -> bool:
        """Check if the stream is fully closed."""
        return self._state in [
            StreamState.CLOSED,
            StreamState.RESET_RECEIVED,
            StreamState.RESET_SENT,
        ]

    @property
    def state(self) -> StreamState:
        """Get the current state of the stream."""
        return self._state

    @property
    def stream_id(self) -> StreamId:
        """Get the unique ID of the stream."""
        return self._stream_id

    async def wait_closed(self) -> None:
        """Wait until the stream is fully closed."""
        if not self._is_initialized or self._closed_future is None:
            raise StreamError(
                message=(
                    f"{self.__class__.__name__} is not initialized."
                    "Its factory should call 'await stream.initialize()' before use."
                )
            )
        await self._closed_future

    def __str__(self) -> str:
        """Format a concise, human-readable summary of the stream."""
        stats = self._stats
        uptime_str = format_duration(seconds=stats.uptime) if stats.uptime > 0 else "0s"

        return (
            f"Stream({self.stream_id}, state={self.state}, direction={self.direction}, "
            f"uptime={uptime_str}, sent={stats.bytes_sent}, received={stats.bytes_received})"
        )


class WebTransportReceiveStream(_StreamBase, EventEmitter):
    """A receive-only WebTransport stream."""

    def __init__(self, *, stream_id: StreamId, session: WebTransportSession) -> None:
        """Initialize the receive stream."""
        EventEmitter.__init__(self)
        self._stream_id = stream_id
        self._session = weakref.ref(session)
        self._state: StreamState = StreamState.OPEN
        self._direction = StreamDirection.RECEIVE_ONLY
        self._stats = StreamStats(stream_id=stream_id, created_at=get_timestamp())
        self._buffer: _StreamBuffer | None = None
        config = session.connection.config if session and session.connection else None
        self._buffer_size = getattr(config, "stream_buffer_size", DEFAULT_BUFFER_SIZE)
        self._read_timeout: float | None = getattr(config, "read_timeout", None)

    @property
    def is_readable(self) -> bool:
        """Check if the stream is currently readable."""
        return self._state in [
            StreamState.OPEN,
            StreamState.HALF_CLOSED_LOCAL,
            StreamState.HALF_CLOSED_REMOTE,
        ]

    async def __aenter__(self) -> Self:
        """Enter async context, returning the activated stream instance."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, ensuring the stream is aborted."""
        if not self.is_closed:
            await self.abort()

    async def abort(self, *, code: int = 0) -> None:
        """Abort the reading side of the stream."""
        session = self._session()
        if session and session.protocol_handler:
            session.protocol_handler.abort_stream(stream_id=self._stream_id, error_code=code)
        await self._set_state(new_state=StreamState.RESET_SENT)

    async def initialize(self) -> None:
        """Initialize asyncio resources for the stream."""
        if self._is_initialized:
            return

        self._buffer = _StreamBuffer(max_size=self._buffer_size)
        await self._buffer.initialize()
        self._closed_future = asyncio.get_running_loop().create_future()

        session = self._session()
        if session and session.protocol_handler:
            handler = session.protocol_handler
            handler.on(
                event_type=EventType.STREAM_DATA_RECEIVED,
                handler=self._on_data_received,
            )
            handler.on(
                event_type=EventType.STREAM_CLOSED,
                handler=self._on_stream_closed,
            )

        self._is_initialized = True

    async def read(self, *, size: int = 8192) -> bytes:
        """Read up to `size` bytes of data from the stream."""
        if not self._is_initialized:
            raise StreamError(
                message=(
                    f"{self.__class__.__name__} is not initialized."
                    "Its factory should call 'await stream.initialize()' before use."
                )
            )
        if self.is_closed:
            return b""
        if not self.is_readable:
            raise StreamError(message=f"Stream not readable in current state: {self._state}")

        start_time = time.time()
        try:
            if self._buffer is None:
                raise StreamError(message="Internal state error: buffer is None despite stream being initialized.")

            data, is_eof = await self._buffer.read(size=size, timeout=self._read_timeout)

            if data:
                self._stats.reads_count += 1
                self._stats.bytes_received += len(data)
                read_time = time.time() - start_time
                self._stats.total_read_time += read_time
                self._stats.max_read_time = max(self._stats.max_read_time, read_time)

            if is_eof:
                new_state = (
                    StreamState.CLOSED
                    if self._state == StreamState.HALF_CLOSED_LOCAL
                    else StreamState.HALF_CLOSED_REMOTE
                )
                await self._set_state(new_state=new_state)

            return data
        except TimeoutError:
            self._stats.read_errors += 1
            raise
        except Exception as e:
            self._stats.read_errors += 1
            raise StreamError(message=f"Read operation failed: {e}") from e

    async def read_all(self, *, max_size: int | None = None) -> bytes:
        """Read the entire content of a stream into a single bytes object."""
        chunks = []
        total_size = 0

        try:
            async for chunk in self.read_iter():
                chunks.append(chunk)
                total_size += len(chunk)
                if max_size and total_size > max_size:
                    raise StreamError(message=f"Stream size exceeds maximum of {max_size} bytes")
            return b"".join(chunks)
        except StreamError as e:
            logger.error("Error reading stream to bytes: %s", e, exc_info=True)
            raise

    async def read_iter(self, *, chunk_size: int = 8192) -> AsyncIterator[bytes]:
        """Iterate over the stream's data in chunks."""
        while self.is_readable:
            data = await self.read(size=chunk_size)
            if not data:
                break
            yield data

    async def readexactly(self, *, n: int) -> bytes:
        """Read exactly n bytes from the stream."""
        if n < 0:
            raise ValueError("n must be a non-negative integer.")
        if n == 0:
            return b""

        buffer = bytearray()
        while len(buffer) < n:
            chunk = await self.read(size=n - len(buffer))
            if not chunk:
                raise asyncio.IncompleteReadError(bytes(buffer), n)
            buffer.extend(chunk)
        return bytes(buffer)

    async def readline(self, *, limit: int = DEFAULT_STREAM_LINE_LIMIT) -> bytes:
        """Read one line from the stream."""
        return await self.readuntil(separator=b"\n", limit=limit)

    async def readuntil(self, *, separator: bytes = b"\n", limit: int | None = None) -> bytes:
        """Read data from the stream until a separator is found."""
        if not self.is_readable:
            raise StreamError(message="Stream not readable.")
        if not separator:
            raise ValueError("Separator cannot be empty.")
        if self._buffer is None:
            raise StreamError(message="Internal state error: buffer is not initialized.")

        while True:
            limit_in_buffer = self._buffer.find_separator(separator=separator)
            if limit_in_buffer != -1:
                if limit is not None and limit_in_buffer > limit:
                    raise StreamError(f"Separator not found within the configured limit of {limit} bytes.")
                return await self.readexactly(n=limit_in_buffer)

            if limit is not None and self._buffer.size > limit:
                raise StreamError(f"Separator not found within the configured limit of {limit} bytes.")

            if self._buffer.eof:
                return await self.read(size=-1)

            await self._buffer.wait_for_data()

    async def _on_data_received(self, event: Event) -> None:
        """Handle incoming data events from the protocol layer."""
        if self._buffer is None or not isinstance(event.data, dict) or event.data.get("stream_id") != self._stream_id:
            return

        data = event.data.get("data", b"")
        end_stream = event.data.get("end_stream", False)
        await self._buffer.feed_data(data=data, eof=end_stream)

    async def _on_stream_closed(self, event: Event) -> None:
        """Handle the remote stream closure event."""
        if isinstance(event.data, dict) and event.data.get("stream_id") == self._stream_id:
            await self._set_state(new_state=StreamState.CLOSED)

    async def _set_state(self, new_state: StreamState) -> None:
        """Set the new state of the stream and trigger teardown if closed."""
        if self._state == new_state:
            return

        old_state = self._state
        self._state = new_state
        logger.debug("Stream %d state: %s -> %s", self._stream_id, old_state, new_state)

        is_functionally_complete = self.is_closed or new_state == StreamState.HALF_CLOSED_REMOTE
        if is_functionally_complete and (self._closed_future and not self._closed_future.done()):
            if self._stats.closed_at is None:
                self._stats.closed_at = get_timestamp()
            await self._teardown()

    async def _teardown(self) -> None:
        """Clean up all resources and event listeners for the stream."""
        if self._closed_future and not self._closed_future.done():
            self._closed_future.set_result(None)

        session = self._session()
        if session and session.protocol_handler:
            handler = session.protocol_handler
            handler.off(
                event_type=EventType.STREAM_DATA_RECEIVED,
                handler=self._on_data_received,
            )
            handler.off(
                event_type=EventType.STREAM_CLOSED,
                handler=self._on_stream_closed,
            )


class WebTransportSendStream(_StreamBase, EventEmitter):
    """A send-only WebTransport stream."""

    _WRITE_CHUNK_SIZE = 65536

    def __init__(self, *, stream_id: StreamId, session: WebTransportSession) -> None:
        """Initialize the send stream."""
        EventEmitter.__init__(self)
        self._stream_id = stream_id
        self._session = weakref.ref(session)
        self._state: StreamState = StreamState.OPEN
        self._direction = StreamDirection.SEND_ONLY
        self._stats = StreamStats(stream_id=stream_id, created_at=get_timestamp())
        self._write_buffer: deque[dict[str, Any]] = deque()
        self._write_buffer_size = 0
        config = session.connection.config if session and session.connection else None
        self._max_buffer_size = getattr(config, "max_stream_buffer_size", MAX_BUFFER_SIZE)
        self._write_timeout: float | None = getattr(config, "write_timeout", None)
        self._backpressure_limit = self._max_buffer_size * 0.8
        self._write_lock: asyncio.Lock | None = None
        self._new_data_event: asyncio.Event | None = None
        self._backpressure_event: asyncio.Event | None = None
        self._flushed_event: asyncio.Event | None = None
        self._writer_task: asyncio.Task[None] | None = None

    @property
    def is_writable(self) -> bool:
        """Check if the stream is currently writable."""
        return self._state in [StreamState.OPEN, StreamState.HALF_CLOSED_REMOTE]

    async def __aenter__(self) -> Self:
        """Enter async context, returning the activated stream instance."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, ensuring the stream is gracefully closed."""
        if not self.is_closed:
            if exc_type is None:
                await self.close()
            else:
                await self.abort()

    async def abort(self, *, code: int = 0) -> None:
        """Abort the writing side of the stream immediately."""
        session = self._session()
        if session and session.protocol_handler:
            session.protocol_handler.abort_stream(stream_id=self._stream_id, error_code=code)

        await self._set_state(new_state=StreamState.RESET_SENT)

    async def close(self) -> None:
        """Gracefully close the sending side of the stream."""
        if not self.is_writable:
            return

        try:
            await self.write(data=b"", end_stream=True, wait_flush=True)
        except StreamError as e:
            if "Writer loop terminated" in str(e):
                logger.debug("Ignoring error during stream close: %s", e)
            else:
                logger.warning("Ignoring error during stream close: %s", e)

    async def flush(self) -> None:
        """Wait until the internal write buffer is empty."""
        if not self._is_initialized or self._flushed_event is None:
            raise StreamError(
                message=(
                    f"{self.__class__.__name__} is not initialized."
                    "Its factory should call 'await stream.initialize()' before use."
                )
            )
        if self._write_buffer_size == 0:
            return

        try:
            await asyncio.wait_for(self._flushed_event.wait(), timeout=self._write_timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(message="Flush timeout") from None

    async def initialize(self) -> None:
        """Initialize asyncio resources for the stream."""
        if self._is_initialized:
            return

        loop = asyncio.get_running_loop()
        self._write_lock = asyncio.Lock()
        self._new_data_event = asyncio.Event()
        self._backpressure_event = asyncio.Event()
        self._backpressure_event.set()
        self._flushed_event = asyncio.Event()
        self._flushed_event.set()
        self._closed_future = loop.create_future()
        self._ensure_writer_is_running()

        self._is_initialized = True

    async def write(self, *, data: Data, end_stream: bool = False, wait_flush: bool = True) -> None:
        """Write data to the stream, handling backpressure and chunking."""
        if not self._is_initialized:
            raise StreamError(
                message=(
                    f"{self.__class__.__name__} is not initialized."
                    "Its factory should call 'await stream.initialize()' before use."
                )
            )
        if not self.is_writable:
            raise StreamError(message=f"Stream not writable in current state: {self._state}")
        if (
            self._write_lock is None
            or self._new_data_event is None
            or self._flushed_event is None
            or self._backpressure_event is None
        ):
            raise StreamError(message="Internal state error: events are None despite stream being initialized.")

        data_bytes = ensure_bytes(data=data)
        if not data_bytes and not end_stream:
            return

        start_time = time.time()
        completion_future = asyncio.get_running_loop().create_future()

        await self._wait_for_buffer_space(size=len(data_bytes))

        async with self._write_lock:
            if not data_bytes and end_stream:
                self._write_buffer.append({"data": b"", "end_stream": True, "future": completion_future})
            else:
                data_len = len(data_bytes)
                offset = 0
                while offset < data_len:
                    chunk = data_bytes[offset : offset + self._WRITE_CHUNK_SIZE]
                    offset += len(chunk)
                    is_last_chunk = offset >= data_len
                    future_for_this_chunk = (
                        completion_future if (wait_flush or (end_stream and is_last_chunk)) else None
                    )
                    self._write_buffer.append(
                        {
                            "data": chunk,
                            "end_stream": end_stream and is_last_chunk,
                            "future": future_for_this_chunk,
                        }
                    )
                    self._write_buffer_size += len(chunk)

            self._flushed_event.clear()
            self._new_data_event.set()

        if wait_flush or end_stream:
            await asyncio.wait_for(completion_future, timeout=self._write_timeout)

        write_time = time.time() - start_time
        self._stats.writes_count += 1
        self._stats.bytes_sent += len(data_bytes)
        self._stats.total_write_time += write_time
        self._stats.max_write_time = max(self._stats.max_write_time, write_time)

    async def write_all(self, *, data: bytes, chunk_size: int = 8192) -> None:
        """Write a bytes object to a stream in chunks and close it."""
        try:
            for i in range(0, len(data), chunk_size):
                chunk = data[i : i + chunk_size]
                await self.write(data=chunk, wait_flush=False)
            await self.flush()
            await self.close()
        except StreamError as e:
            logger.error("Error writing bytes to stream: %s", e, exc_info=True)
            await self.abort(code=1)
            raise

    def _ensure_writer_is_running(self) -> None:
        """Ensure the background writer task is active."""
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(self._writer_loop())

    async def _on_stream_closed(self, event: Event) -> None:
        """Handle the remote stream closure event."""
        if isinstance(event.data, dict) and event.data.get("stream_id") == self._stream_id:
            await self._set_state(new_state=StreamState.CLOSED)

    async def _set_state(self, new_state: StreamState) -> None:
        """Set the new state of the stream and trigger teardown if closed."""
        if self._state == new_state:
            return

        old_state = self._state
        self._state = new_state
        logger.debug("Stream %d state: %s -> %s", self._stream_id, old_state, new_state)

        is_functionally_complete = self.is_closed or new_state == StreamState.HALF_CLOSED_LOCAL
        if is_functionally_complete and (self._closed_future and not self._closed_future.done()):
            if self._stats.closed_at is None:
                self._stats.closed_at = get_timestamp()
            await self._teardown()

    async def _teardown(self) -> None:
        """Clean up all resources and event listeners for the stream."""
        if self._writer_task and not self._writer_task.done():
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass

        if self._closed_future and not self._closed_future.done():
            self._closed_future.set_result(None)

        session = self._session()
        if session and session.protocol_handler:
            session.protocol_handler.off(
                event_type=EventType.STREAM_CLOSED,
                handler=self._on_stream_closed,
            )

    async def _wait_for_buffer_space(self, size: int) -> None:
        """Wait for enough space in the write buffer, handling backpressure."""
        if self._backpressure_event is None or self._write_lock is None:
            raise StreamError(
                message=(
                    f"{self.__class__.__name__} is not initialized."
                    "Its factory should call 'await stream.initialize()' before use."
                )
            )

        while True:
            async with self._write_lock:
                if self._write_buffer_size + size <= self._max_buffer_size:
                    return

                self._backpressure_event.clear()
                self._stats.flow_control_errors += 1

            try:
                await asyncio.wait_for(self._backpressure_event.wait(), timeout=self._write_timeout)
            except asyncio.TimeoutError:
                raise TimeoutError(message="Write timeout due to backpressure") from None

    async def _writer_loop(self) -> None:
        """The main loop for the background writer task."""
        if (
            self._write_lock is None
            or self._new_data_event is None
            or self._flushed_event is None
            or self._backpressure_event is None
        ):
            raise StreamError(
                message=(
                    f"{self.__class__.__name__} is not initialized."
                    "Its factory should call 'await stream.initialize()' before use."
                )
            )

        try:
            while not self.is_closed:
                item = None
                async with self._write_lock:
                    if not self._write_buffer:
                        self._flushed_event.set()
                        self._new_data_event.clear()
                    else:
                        item = self._write_buffer[0]

                if item is None:
                    await self._new_data_event.wait()
                    continue

                data, end_stream, future = (
                    item["data"],
                    item["end_stream"],
                    item["future"],
                )

                session = self._session()
                if not session or not session.protocol_handler or session.is_closed:
                    if future and not future.done():
                        future.set_exception(StreamError(message="Session is not available for writing."))
                    async with self._write_lock:
                        self._write_buffer.popleft()
                    continue

                handler = session.protocol_handler

                try:
                    handler.send_webtransport_stream_data(stream_id=self._stream_id, data=data, end_stream=end_stream)

                    async with self._write_lock:
                        self._write_buffer.popleft()
                        self._write_buffer_size -= len(data)
                        if self._write_buffer_size < self._backpressure_limit:
                            self._backpressure_event.set()

                    if future and not future.done():
                        future.set_result(None)
                    if end_stream:
                        new_state = (
                            StreamState.CLOSED
                            if self._state == StreamState.HALF_CLOSED_REMOTE
                            else StreamState.HALF_CLOSED_LOCAL
                        )
                        await self._set_state(new_state=new_state)
                        break
                except FlowControlError:
                    self._stats.flow_control_errors += 1
                    if session._data_credit_event:
                        try:
                            await asyncio.wait_for(session._data_credit_event.wait(), timeout=self._write_timeout)
                            session._data_credit_event.clear()
                        except asyncio.TimeoutError:
                            timeout_exc = TimeoutError(message="Timeout waiting for data credit")
                            if future and not future.done():
                                future.set_exception(timeout_exc)
                            self._stats.write_errors += 1
                            logger.error(
                                "Timeout waiting for data credit for stream %d: %s",
                                self._stream_id,
                                timeout_exc,
                                exc_info=True,
                            )
                            await self._set_state(new_state=StreamState.RESET_SENT)
                            break
                    else:
                        stream_exc = StreamError(
                            message="Flow control error but no data credit event available to wait on."
                        )
                        if future and not future.done():
                            future.set_exception(stream_exc)
                        self._stats.write_errors += 1
                        logger.error(
                            "Unrecoverable flow control for stream %d: %s", self._stream_id, stream_exc, exc_info=True
                        )
                        await self._set_state(new_state=StreamState.RESET_SENT)
                        break
                except Exception as e:
                    if future and not future.done():
                        future.set_exception(e)
                    self._stats.write_errors += 1
                    logger.error("Error sending stream data for %d: %s", self._stream_id, e, exc_info=True)
                    await self._set_state(new_state=StreamState.RESET_SENT)
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if self._flushed_event:
                self._flushed_event.set()
            if self._write_lock:
                async with self._write_lock:
                    while self._write_buffer:
                        item = self._write_buffer.popleft()
                        future = item.get("future")
                        if future and not future.done():
                            future.set_exception(
                                StreamError(message="Writer loop terminated before processing this write.")
                            )


class WebTransportStream(WebTransportReceiveStream, WebTransportSendStream):
    """A bidirectional WebTransport stream."""

    def __init__(self, *, stream_id: StreamId, session: WebTransportSession) -> None:
        """Initialize the bidirectional stream."""
        EventEmitter.__init__(self)
        self._stream_id = stream_id
        self._session = weakref.ref(session)
        self._state: StreamState = StreamState.OPEN
        self._direction = StreamDirection.BIDIRECTIONAL
        self._stats = StreamStats(stream_id=stream_id, created_at=get_timestamp())
        self._is_initialized = False
        self._closed_future: asyncio.Future[None] | None = None
        config = session.connection.config if session and session.connection else None
        self._buffer_size = getattr(config, "stream_buffer_size", DEFAULT_BUFFER_SIZE)
        self._read_timeout: float | None = getattr(config, "read_timeout", None)
        self._buffer: _StreamBuffer | None = None
        self._max_buffer_size = getattr(config, "max_stream_buffer_size", MAX_BUFFER_SIZE)
        self._write_timeout: float | None = getattr(config, "write_timeout", None)
        self._backpressure_limit = self._max_buffer_size * 0.8
        self._write_buffer: deque[dict[str, Any]] = deque()
        self._write_buffer_size = 0
        self._write_lock: asyncio.Lock | None = None
        self._new_data_event: asyncio.Event | None = None
        self._backpressure_event: asyncio.Event | None = None
        self._flushed_event: asyncio.Event | None = None
        self._writer_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        """Enter async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, ensuring the stream is gracefully closed."""
        if not self.is_closed:
            if exc_type is None:
                await self.close()
            else:
                await self.abort()

    async def close(self) -> None:
        """Gracefully close the stream's write side."""
        await WebTransportSendStream.close(self=self)

    async def initialize(self) -> None:
        """Initialize all bidirectional resources."""
        if self._is_initialized:
            return

        loop = asyncio.get_running_loop()
        self._closed_future = loop.create_future()

        self._buffer = _StreamBuffer(max_size=self._buffer_size)
        await self._buffer.initialize()

        self._write_lock = asyncio.Lock()
        self._new_data_event = asyncio.Event()
        self._backpressure_event = asyncio.Event()
        self._backpressure_event.set()
        self._flushed_event = asyncio.Event()
        self._flushed_event.set()

        session = self._session()
        if session and session.protocol_handler:
            handler = session.protocol_handler
            handler.on(
                event_type=EventType.STREAM_DATA_RECEIVED,
                handler=self._on_data_received,
            )
            handler.on(
                event_type=EventType.STREAM_CLOSED,
                handler=self._on_stream_closed,
            )
        self._ensure_writer_is_running()

        self._is_initialized = True

    def diagnose_issues(
        self,
        *,
        error_rate_threshold: float = 0.1,
        latency_threshold: float = 1.0,
        stale_threshold: float = 3600.0,
    ) -> list[str]:
        """Diagnose and report a list of potential issues with a stream."""
        issues: list[str] = []
        stats = self._stats

        if self.state == StreamState.RESET_RECEIVED:
            issues.append("Stream was reset by remote peer")
        elif self.state == StreamState.RESET_SENT:
            issues.append("Stream was reset locally")

        if stats.reads_count > 10 and (stats.read_errors / stats.reads_count) > error_rate_threshold:
            issues.append(f"High read error rate: {stats.read_errors}/{stats.reads_count}")
        if stats.writes_count > 10 and (stats.write_errors / stats.writes_count) > error_rate_threshold:
            issues.append(f"High write error rate: {stats.write_errors}/{stats.writes_count}")
        if stats.avg_read_time > latency_threshold:
            issues.append(f"Slow read operations: {stats.avg_read_time:.2f}s average")
        if stats.avg_write_time > latency_threshold:
            issues.append(f"Slow write operations: {stats.avg_write_time:.2f}s average")
        if stats.uptime > stale_threshold and stats.reads_count == 0 and stats.writes_count == 0:
            issues.append("Stream appears stale (long uptime with no activity)")

        return issues

    async def monitor_health(self, *, check_interval: float = 30.0, error_rate_threshold: float = 0.1) -> None:
        """Continuously monitor the health of a stream until it is closed."""
        try:
            while not self.is_closed:
                stats = self._stats
                total_ops = stats.reads_count + stats.writes_count
                total_errors = stats.read_errors + stats.write_errors

                if total_ops > 10 and (total_errors / total_ops) > error_rate_threshold:
                    logger.warning(
                        "Stream %d has high error rate: %d/%d",
                        self.stream_id,
                        total_errors,
                        total_ops,
                    )

                await asyncio.sleep(check_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Stream health monitoring error: %s", e, exc_info=True)

    async def _set_state(self, new_state: StreamState) -> None:
        """Set the new state of the stream and trigger teardown if closed."""
        if self._state == new_state:
            return

        old_state = self._state
        self._state = new_state
        logger.debug("Stream %d state: %s -> %s", self._stream_id, old_state, new_state)

        if self.is_closed and (self._closed_future and not self._closed_future.done()):
            if self._stats.closed_at is None:
                self._stats.closed_at = get_timestamp()
            await self._teardown()

    async def _teardown(self) -> None:
        """Clean up resources for both send and receive sides."""
        await WebTransportReceiveStream._teardown(self=self)
        await WebTransportSendStream._teardown(self=self)
