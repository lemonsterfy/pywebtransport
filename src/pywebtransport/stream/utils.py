"""WebTransport stream utility functions."""

from __future__ import annotations

from pywebtransport.exceptions import StreamError
from pywebtransport.stream.stream import WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.utils import get_logger

__all__ = [
    "copy_stream_data",
    "echo_stream",
]

logger = get_logger(name="stream.utils")


async def copy_stream_data(
    *,
    source: WebTransportReceiveStream,
    destination: WebTransportSendStream,
    chunk_size: int = 8192,
) -> int:
    """Copy all data from a source stream to a destination stream."""
    total_bytes = 0
    try:
        async for chunk in source.read_iter(chunk_size=chunk_size):
            await destination.write(data=chunk)
            total_bytes += len(chunk)
        await destination.close()
    except StreamError as e:
        logger.error("Error copying stream data: %s", e, exc_info=True)
        await destination.abort(code=1)
        raise
    return total_bytes


async def echo_stream(*, stream: WebTransportStream) -> None:
    """Echo all data received on a bidirectional stream back to the sender."""
    try:
        async for chunk in stream.read_iter():
            await stream.write(data=chunk)
        await stream.close()
    except StreamError as e:
        logger.error("Error in echo stream: %s", e, exc_info=True)
        await stream.abort(code=1)
