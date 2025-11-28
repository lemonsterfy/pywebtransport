"""Performance benchmark for WebTransport datagrams."""

import asyncio
import logging
import ssl
import uuid
from typing import Any, Final, cast

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from pywebtransport import ClientConfig, Event, WebTransportClient
from pywebtransport.types import EventType

DATAGRAM_SIZE: Final[int] = 64
PPS_BURST_COUNT: Final[int] = 1000
RTT_ECHO_TIMEOUT: Final[float] = 2.0
DATAGRAM_PACING_DELAY: Final[float] = 0.00001
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
ECHO_ENDPOINT: Final[str] = "/echo"
DISCARD_ENDPOINT: Final[str] = "/discard"

logger = logging.getLogger("test_04_datagram_performance")


@pytest.fixture(scope="module")
def client_config() -> ClientConfig:
    """Provide a client configuration suitable for datagram tests."""
    return ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=15.0,
        read_timeout=5.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )


class TestDatagramPerformance:
    """Benchmark tests for datagram round-trip time and send rate."""

    def test_datagram_rtt(self, benchmark: BenchmarkFixture, client_config: ClientConfig) -> None:
        """Benchmark the round-trip time (RTT) of a single datagram."""

        async def run_rtt_cycle() -> None:
            async with WebTransportClient(config=client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{ECHO_ENDPOINT}")
                payload = uuid.uuid4().bytes

                async def send_and_wait_for_echo() -> None:
                    expected_response = b"ECHO: " + payload
                    await session.send_datagram(data=payload)
                    while True:
                        event: Event = await session.events.wait_for(event_type=EventType.DATAGRAM_RECEIVED)
                        response = None
                        if isinstance(event.data, dict):
                            response = event.data.get("data")

                        if response == expected_response:
                            return

                try:
                    async with asyncio.timeout(delay=RTT_ECHO_TIMEOUT):
                        await send_and_wait_for_echo()
                except asyncio.TimeoutError:
                    pytest.fail(f"Datagram RTT echo not received within {RTT_ECHO_TIMEOUT}s.")

        benchmark(lambda: asyncio.run(run_rtt_cycle()))

        stats = cast(dict[str, Any], benchmark.stats)
        mean_time = stats["mean"]
        benchmark.extra_info["rtt_ms"] = mean_time * 1000

    def test_datagram_send_pps(self, benchmark: BenchmarkFixture, client_config: ClientConfig) -> None:
        """Benchmark the client's maximum datagram send rate (Packets Per Second)."""
        payload = b"p" * DATAGRAM_SIZE

        async def run_pps_cycle() -> None:
            async with WebTransportClient(config=client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{DISCARD_ENDPOINT}")

                tasks = []
                for _ in range(PPS_BURST_COUNT):
                    tasks.append(asyncio.create_task(coro=session.send_datagram(data=payload)))
                    await asyncio.sleep(delay=DATAGRAM_PACING_DELAY)

                await asyncio.gather(*tasks)

        benchmark(lambda: asyncio.run(run_pps_cycle()))

        stats = cast(dict[str, Any], benchmark.stats)
        mean_time_sec = stats["mean"]
        packets_per_second = PPS_BURST_COUNT / mean_time_sec if mean_time_sec > 0 else 0
        benchmark.extra_info["packets_per_second"] = packets_per_second
