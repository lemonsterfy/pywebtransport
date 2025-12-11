"""High-level abstractions for WebTransport streams."""

from __future__ import annotations

import asyncio
import weakref
from collections import deque
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, AsyncIterator, Self

from pywebtransport._protocol.events import (
    UserGetStreamDiagnostics,
    UserResetStream,
    UserSendStreamData,
    UserStopStream,
    UserStreamRead,
)
from pywebtransport.constants import ErrorCodes
from pywebtransport.events import Event, EventEmitter
from pywebtransport.exceptions import ConnectionError, StreamError, TimeoutError
from pywebtransport.types import Buffer, SessionId, StreamDirection, StreamId, StreamState
from pywebtransport.utils import ensure_buffer, get_logger

if TYPE_CHECKING:
    from pywebtransport.session import WebTransportSession


__all__: list[str] = [
    "StreamDiagnostics",
    "StreamType",
    "WebTransportReceiveStream",
    "WebTransportSendStream",
    "WebTransportStream",
]

_STREAM_EVENT_HISTORY_SIZE = 0
_STREAM_EVENT_QUEUE_SIZE = 16
_STREAM_MAX_EVENT_LISTENERS = 20

logger = get_logger(name=__name__)


@dataclass(kw_only=True)
class StreamDiagnostics:
    """A snapshot of stream diagnostics."""

    stream_id: StreamId
    session_id: SessionId
    direction: StreamDirection
    state: StreamState
    created_at: float
    bytes_sent: int
    bytes_received: int
    read_buffer: bytes
    read_buffer_size: int
    pending_read_requests: list[Any]
    write_buffer: list[tuple[bytes, Any, bool]]
    write_buffer_size: int
    close_code: int | None
    close_reason: str | None
    closed_at: float | None


class _BaseStream:
    """Base class for WebTransport stream handles."""

    _stream_id: StreamId
    events: EventEmitter

    def __init__(self, *, session: WebTransportSession, stream_id: StreamId) -> None:
        """Initialize the base stream handle."""
        self._session = weakref.ref(session)
        self._stream_id = stream_id
        self._cached_state = StreamState.OPEN
        self.events = EventEmitter(
            max_queue_size=_STREAM_EVENT_QUEUE_SIZE,
            max_history=_STREAM_EVENT_HISTORY_SIZE,
            max_listeners=_STREAM_MAX_EVENT_LISTENERS,
        )
        self.events.on(event_type="stream_closed", handler=self._on_closed)

    @property
    def is_closed(self) -> bool:
        """Return True if the stream is fully closed."""
        return self._cached_state == StreamState.CLOSED

    @property
    def session(self) -> WebTransportSession:
        """Get the parent session handle."""
        session = self._session()
        if session is None:
            raise ConnectionError("Session is gone.")
        return session

    @property
    def state(self) -> StreamState:
        """Get the current state of the stream."""
        return self._cached_state

    @property
    def stream_id(self) -> StreamId:
        """Get the unique identifier for this stream."""
        return self._stream_id

    async def diagnostics(self) -> StreamDiagnostics:
        """Get diagnostic information about the stream."""
        fut = asyncio.get_running_loop().create_future()
        event = UserGetStreamDiagnostics(stream_id=self.stream_id, future=fut)
        try:
            await self.session._send_event_to_engine(event=event)
        except ConnectionError as e:
            raise StreamError(f"Connection is closed, cannot get diagnostics: {e}", stream_id=self.stream_id) from e

        diag_data: dict[str, Any] = await fut

        if "write_buffer" in diag_data and isinstance(diag_data["write_buffer"], deque):
            diag_data["write_buffer"] = list(diag_data["write_buffer"])

        return StreamDiagnostics(**diag_data)

    def _on_closed(self, event: Event) -> None:
        """Handle stream closed event."""
        self._cached_state = StreamState.CLOSED

    def __repr__(self) -> str:
        """Provide a developer-friendly representation."""
        return f"<{self.__class__.__name__} id={self.stream_id} state={self._cached_state}>"


class WebTransportReceiveStream(_BaseStream):
    """Represents the readable side of a WebTransport stream."""

    def __init__(self, *, session: WebTransportSession, stream_id: StreamId) -> None:
        """Initialize the receive stream handle."""
        super().__init__(session=session, stream_id=stream_id)
        self._read_buffer: deque[memoryview] = deque()
        self._read_buffer_size = 0
        self._read_eof = False

    @property
    def can_read(self) -> bool:
        """Return True if the stream is readable."""
        return self._cached_state not in (StreamState.RESET_RECEIVED, StreamState.CLOSED)

    @property
    def direction(self) -> StreamDirection:
        """Get the directionality of the stream."""
        return StreamDirection.RECEIVE_ONLY

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context manager."""
        await self.stop_receiving()

    async def close(self) -> None:
        """Close the receiving side of the stream."""
        await self.stop_receiving()

    async def read(self, *, max_bytes: int = -1) -> bytes:
        """Read data from the stream."""
        if self._read_buffer_size > 0:
            if max_bytes == -1:
                return self._consume_buffer(self._read_buffer_size)
            to_read = min(max_bytes, self._read_buffer_size)
            return self._consume_buffer(to_read)

        if self._read_eof:
            return b""

        if self.is_closed:
            self._read_eof = True
            return b""

        try:
            data = await self._read_from_engine(max_bytes=max_bytes)
        except StreamError as e:
            if e.error_code == ErrorCodes.STREAM_STATE_ERROR:
                self._read_eof = True
                return b""
            raise

        if data is None:
            self._read_eof = True
            return b""
        return bytes(data)

    async def read_all(self) -> bytes:
        """Read all data from the stream until EOF."""
        chunks: list[bytes] = []
        try:
            if self._read_buffer_size > 0:
                chunks.append(self._consume_buffer(self._read_buffer_size))

            async for chunk in self:
                chunks.append(chunk)
        except StreamError as e:
            logger.warning("Error during read_all on stream %d: %s", self.stream_id, e)
        return b"".join(chunks)

    async def readexactly(self, *, n: int) -> bytes:
        """Read exactly n bytes from the stream."""
        if n < 0:
            raise ValueError("n must be a non-negative integer")
        if n == 0:
            return b""

        connection = self.session._connection()
        if not connection:
            raise ConnectionError("Connection is gone.")
        max_buffer_size = connection.config.max_stream_read_buffer
        read_timeout = connection.config.read_timeout

        if n > max_buffer_size:
            raise StreamError(
                f"Read request ({n} bytes) exceeds max read buffer ({max_buffer_size} bytes)", stream_id=self.stream_id
            )

        try:
            async with asyncio.timeout(read_timeout):
                while self._read_buffer_size < n:
                    if self._read_eof:
                        partial = self._consume_buffer(self._read_buffer_size)
                        raise asyncio.IncompleteReadError(partial, n)

                    chunk = await self._read_from_engine()
                    if chunk is None:
                        self._read_eof = True
                        partial = self._consume_buffer(self._read_buffer_size)
                        raise asyncio.IncompleteReadError(partial, n)

                    chunk_len = len(chunk)
                    if self._read_buffer_size + chunk_len > max_buffer_size:
                        self._read_buffer.append(chunk)
                        self._read_buffer_size += chunk_len
                        raise StreamError(
                            f"Read buffer limit ({max_buffer_size} bytes) exceeded", stream_id=self.stream_id
                        )

                    self._read_buffer.append(chunk)
                    self._read_buffer_size += chunk_len
        except asyncio.TimeoutError:
            raise TimeoutError(f"readexactly timed out after {read_timeout}s") from None

        return self._consume_buffer(n)

    async def readline(self, *, limit: int = -1) -> bytes:
        """Read a line from the stream."""
        return await self.readuntil(separator=b"\n", limit=limit)

    async def readuntil(self, *, separator: bytes, limit: int = -1) -> bytes:
        """Read data from the stream until a separator is found."""
        if not separator:
            raise ValueError("Separator cannot be empty")

        sep_len = len(separator)
        connection = self.session._connection()
        if not connection:
            raise ConnectionError("Connection is gone.")
        max_buffer_size = connection.config.max_stream_read_buffer
        read_timeout = connection.config.read_timeout

        if limit < 0:
            effective_limit = max_buffer_size
        elif limit > max_buffer_size:
            raise StreamError(
                f"Read limit ({limit}) exceeds max read buffer ({max_buffer_size} bytes)", stream_id=self.stream_id
            )
        else:
            effective_limit = limit

        offset = 0

        try:
            async with asyncio.timeout(read_timeout):
                while True:
                    found_idx = self._find_in_buffer(separator, start=offset)

                    if found_idx != -1:
                        total_len = found_idx + sep_len
                        if total_len > effective_limit:
                            raise StreamError(
                                f"Stream {self.stream_id} line over limit {effective_limit}", stream_id=self.stream_id
                            )
                        return self._consume_buffer(total_len)

                    if self._read_buffer_size > effective_limit:
                        raise StreamError(
                            f"Stream {self.stream_id} separator not found within limit {effective_limit}",
                            stream_id=self.stream_id,
                        )

                    if self._read_buffer_size >= sep_len:
                        offset = self._read_buffer_size - sep_len + 1
                    else:
                        offset = 0

                    if self._read_eof:
                        partial = self._consume_buffer(self._read_buffer_size)
                        raise asyncio.IncompleteReadError(partial, None)

                    chunk = await self._read_from_engine()
                    if chunk is None:
                        self._read_eof = True
                        partial = self._consume_buffer(self._read_buffer_size)
                        raise asyncio.IncompleteReadError(partial, None)

                    chunk_len = len(chunk)
                    if self._read_buffer_size + chunk_len > max_buffer_size:
                        self._read_buffer.append(chunk)
                        self._read_buffer_size += chunk_len
                        raise StreamError(
                            f"Read buffer limit ({max_buffer_size} bytes) exceeded during readuntil",
                            stream_id=self.stream_id,
                        )

                    self._read_buffer.append(chunk)
                    self._read_buffer_size += chunk_len
        except asyncio.TimeoutError:
            raise TimeoutError(f"readuntil timed out after {read_timeout}s") from None

    async def stop_receiving(self, *, error_code: int = ErrorCodes.NO_ERROR) -> None:
        """Signal the peer to stop sending data."""
        fut = asyncio.get_running_loop().create_future()
        event = UserStopStream(stream_id=self.stream_id, error_code=error_code, future=fut)
        await self.session._send_event_to_engine(event=event)
        await fut
        self._cached_state = StreamState.RESET_RECEIVED

    def _consume_buffer(self, n: int) -> bytes:
        """Consume n bytes from the deque buffer."""
        if n == 0:
            return b""

        if n == self._read_buffer_size:
            data = b"".join(self._read_buffer)
            self._read_buffer.clear()
            self._read_buffer_size = 0
            return data

        chunks: list[bytes] = []
        collected = 0

        while collected < n and self._read_buffer:
            chunk = self._read_buffer[0]
            chunk_len = len(chunk)
            needed = n - collected

            if chunk_len <= needed:
                self._read_buffer.popleft()
                chunks.append(chunk.tobytes())
                collected += chunk_len
            else:
                take = chunk[:needed]
                keep = chunk[needed:]
                self._read_buffer[0] = keep
                chunks.append(take.tobytes())
                collected += needed
                break

        self._read_buffer_size -= collected
        return b"".join(chunks)

    def _find_in_buffer(self, sep: bytes, start: int = 0) -> int:
        """Find separator index in the deque buffer."""
        global_idx = 0
        sep_len = len(sep)
        prev_tail = b""

        for chunk in self._read_buffer:
            chunk_bytes = chunk.tobytes()
            chunk_len = len(chunk_bytes)

            if global_idx + chunk_len < start:
                global_idx += chunk_len
                if chunk_len >= sep_len:
                    prev_tail = chunk_bytes[-(sep_len - 1) :] if sep_len > 1 else b""
                else:
                    prev_tail = (prev_tail + chunk_bytes)[-(sep_len - 1) :] if sep_len > 1 else b""
                continue

            local_start = max(0, start - global_idx)
            found = chunk_bytes.find(sep, local_start)
            if found != -1:
                return global_idx + found

            if sep_len > 1 and prev_tail:
                check_window = prev_tail + chunk_bytes[: sep_len - 1]
                seam_found = check_window.find(sep)
                if seam_found != -1:
                    match_abs_idx = (global_idx - len(prev_tail)) + seam_found
                    if match_abs_idx >= start:
                        return match_abs_idx

            if chunk_len >= sep_len:
                prev_tail = chunk_bytes[-(sep_len - 1) :] if sep_len > 1 else b""
            else:
                prev_tail = (prev_tail + chunk_bytes)[-(sep_len - 1) :] if sep_len > 1 else b""

            global_idx += chunk_len

        return -1

    async def _read_from_engine(self, *, max_bytes: int = -1) -> memoryview | None:
        """Fetch data from the engine."""
        connection = self.session._connection()
        if not connection:
            raise ConnectionError("Connection is gone.")

        max_pull_size = connection.config.max_stream_read_buffer
        effective_max_bytes: int
        if max_bytes < 0:
            effective_max_bytes = max_pull_size
        else:
            effective_max_bytes = min(max_bytes, max_pull_size)

        fut = asyncio.get_running_loop().create_future()
        event = UserStreamRead(stream_id=self.stream_id, max_bytes=effective_max_bytes, future=fut)
        await self.session._send_event_to_engine(event=event)

        try:
            timeout = connection.config.read_timeout
            async with asyncio.timeout(delay=timeout):
                result = await fut
            if result:
                return memoryview(result)
            return None
        except asyncio.TimeoutError as e:
            fut.cancel()
            raise TimeoutError(f"Stream {self.stream_id} read operation timed out after {timeout}s") from e
        except Exception:
            raise

    def __aiter__(self) -> AsyncIterator[bytes]:
        """Iterate over the stream chunks."""
        return self

    async def __anext__(self) -> bytes:
        """Get the next chunk of data."""
        try:
            data = await self.read()
        except StreamError as e:
            if e.error_code in (ErrorCodes.NO_ERROR, ErrorCodes.H3_NO_ERROR):
                raise StopAsyncIteration from e
            raise

        if not data:
            raise StopAsyncIteration
        return data


class WebTransportSendStream(_BaseStream):
    """Represents the writable side of a WebTransport stream."""

    @property
    def can_write(self) -> bool:
        """Return True if the stream is writable."""
        return self._cached_state not in (StreamState.HALF_CLOSED_LOCAL, StreamState.CLOSED, StreamState.RESET_SENT)

    @property
    def direction(self) -> StreamDirection:
        """Get the directionality of the stream."""
        return StreamDirection.SEND_ONLY

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context manager."""
        exit_error_code: int | None = None
        match exc_val:
            case asyncio.CancelledError():
                exit_error_code = ErrorCodes.APPLICATION_ERROR
            case BaseException():
                exit_error_code = getattr(exc_val, "error_code", ErrorCodes.APPLICATION_ERROR)
            case None:
                pass

        await self.close(error_code=exit_error_code)

    async def close(self, *, error_code: int | None = None) -> None:
        """Close the sending side of the stream."""
        if error_code is not None:
            await self.stop_sending(error_code=error_code)
            return

        try:
            await self.write(data=b"", end_stream=True)
            self._cached_state = StreamState.HALF_CLOSED_LOCAL
        except StreamError as e:
            logger.debug("Ignoring expected StreamError on stream %s close: %s", self.stream_id, e)
        except Exception as e:
            logger.error("Unexpected error during stream %s close: %s", self.stream_id, e, exc_info=True)
            raise

    async def stop_sending(self, *, error_code: int = ErrorCodes.NO_ERROR) -> None:
        """Stop sending data and reset the stream."""
        fut = asyncio.get_running_loop().create_future()
        event = UserResetStream(stream_id=self.stream_id, error_code=error_code, future=fut)
        await self.session._send_event_to_engine(event=event)
        await fut
        self._cached_state = StreamState.RESET_SENT

    async def write(self, *, data: Buffer, end_stream: bool = False) -> None:
        """Write data to the stream."""
        try:
            buffer_data = ensure_buffer(data=data)
        except TypeError as e:
            logger.debug("Stream %d write failed pre-validation: %s", self.stream_id, e)
            raise

        if not buffer_data and not end_stream:
            return

        connection = self.session._connection()
        if not connection:
            raise ConnectionError("Connection is gone.")

        fut = asyncio.get_running_loop().create_future()
        event = UserSendStreamData(stream_id=self.stream_id, data=buffer_data, end_stream=end_stream, future=fut)
        await self.session._send_event_to_engine(event=event)

        try:
            timeout = connection.config.write_timeout
            async with asyncio.timeout(delay=timeout):
                await fut
        except asyncio.TimeoutError as e:
            fut.cancel()
            raise TimeoutError(f"Stream {self.stream_id} write operation timed out after {timeout}s") from e
        except Exception:
            raise

    async def write_all(self, *, data: Buffer, chunk_size: int = 65536) -> None:
        """Write buffer data to the stream in chunks and close it."""
        try:
            buffer_data = ensure_buffer(data=data)
            offset = 0
            data_len = len(buffer_data)
            while offset < data_len:
                chunk = buffer_data[offset : offset + chunk_size]
                offset += len(chunk)
                is_last_chunk = offset >= data_len
                await self.write(data=chunk, end_stream=is_last_chunk)
            if data_len == 0:
                await self.write(data=b"", end_stream=True)
        except StreamError as e:
            logger.debug("Error writing bytes to stream %d: %s", self.stream_id, e)
            await self.stop_sending(error_code=ErrorCodes.APPLICATION_ERROR)
            raise


class WebTransportStream(WebTransportReceiveStream, WebTransportSendStream):
    """Represents the bidirectional WebTransport stream."""

    @property
    def direction(self) -> StreamDirection:
        """Get the directionality of the stream."""
        return StreamDirection.BIDIRECTIONAL

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context manager."""
        exit_error_code: int | None = None
        match exc_val:
            case asyncio.CancelledError():
                exit_error_code = ErrorCodes.APPLICATION_ERROR
            case BaseException():
                exit_error_code = getattr(exc_val, "error_code", ErrorCodes.APPLICATION_ERROR)
            case None:
                pass
        await self.close(error_code=exit_error_code)

    async def close(self, *, error_code: int | None = None) -> None:
        """Close both sides of the stream."""
        await WebTransportSendStream.close(self, error_code=error_code)
        stop_code = error_code if error_code is not None else ErrorCodes.NO_ERROR
        await WebTransportReceiveStream.stop_receiving(self, error_code=stop_code)


type StreamType = WebTransportStream | WebTransportReceiveStream | WebTransportSendStream
