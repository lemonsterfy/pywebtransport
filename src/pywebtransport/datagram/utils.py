"""
WebTransport Datagram Utilities.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pywebtransport.utils import get_logger, get_timestamp

if TYPE_CHECKING:
    from pywebtransport.datagram.transport import WebTransportDatagramDuplexStream


__all__ = [
    "create_heartbeat_datagram",
    "datagram_throughput_test",
    "is_heartbeat_datagram",
]

logger = get_logger("datagram.utils")


def create_heartbeat_datagram() -> bytes:
    """Create a new heartbeat datagram payload."""
    return b"HEARTBEAT:" + str(int(get_timestamp())).encode("utf-8")


def is_heartbeat_datagram(data: bytes) -> bool:
    """Check if the given data is a heartbeat datagram."""
    return data.startswith(b"HEARTBEAT:")


async def datagram_throughput_test(
    datagram_stream: WebTransportDatagramDuplexStream,
    *,
    duration: float = 10.0,
    datagram_size: int = 1000,
) -> dict[str, Any]:
    """Run a throughput test on the datagram stream."""
    if datagram_size > datagram_stream.max_datagram_size:
        raise ValueError(f"datagram_size {datagram_size} exceeds max size {datagram_stream.max_datagram_size}")

    test_data = b"X" * datagram_size
    start_time = get_timestamp()
    end_time = start_time + duration
    sent_count = 0
    error_count = 0

    while get_timestamp() < end_time:
        try:
            if not await datagram_stream.try_send(test_data):
                await asyncio.sleep(0.01)
            sent_count += 1
        except Exception:
            error_count += 1
        await asyncio.sleep(0.001)

    actual_duration = get_timestamp() - start_time
    throughput_dps = sent_count / max(1, actual_duration)
    return {
        "duration": actual_duration,
        "datagrams_sent": sent_count,
        "errors": error_count,
        "throughput_dps": throughput_dps,
        "throughput_bps": throughput_dps * datagram_size * 8,  # in bits per second
        "error_rate": error_count / max(1, sent_count + error_count),
    }
