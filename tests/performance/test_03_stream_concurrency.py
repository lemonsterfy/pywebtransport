"""Performance benchmark for concurrent WebTransport stream creation and usage."""

import asyncio
import logging
import ssl
from typing import Final

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from pywebtransport import ClientConfig, WebTransportClient, WebTransportSession

DATA_PER_STREAM: Final[int] = 1024
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
ECHO_ENDPOINT: Final[str] = "/echo"
MAX_CONCURRENT_STREAMS: Final[int] = 10
TOTAL_STREAM_COUNTS: Final[list[int]] = [10, 50, 100]

logger = logging.getLogger("test_03_stream_concurrency")


@pytest.fixture(scope="module")
def client_config() -> ClientConfig:
    """Provide a client configuration with generous timeouts for high concurrency."""
    return ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=30.0,
        read_timeout=90.0,
        write_timeout=90.0,
        stream_creation_timeout=30.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=200,
        initial_max_streams_uni=200,
    )


@pytest.mark.parametrize("stream_count", TOTAL_STREAM_COUNTS)
class TestStreamConcurrency:
    """Benchmark tests for handling multiple concurrent streams."""

    def test_concurrent_stream_throughput(
        self,
        benchmark: BenchmarkFixture,
        client_config: ClientConfig,
        stream_count: int,
    ) -> None:
        """Benchmark the throughput of many concurrent bidirectional streams."""
        payload = b"d" * DATA_PER_STREAM
        expected_response = b"ECHO: " + payload

        async def stream_worker(*, session: WebTransportSession, semaphore: asyncio.Semaphore) -> None:
            async with semaphore:
                stream = await session.create_bidirectional_stream()
                await stream.write_all(data=payload)
                response = await stream.read_all()
                assert response == expected_response

        async def run_concurrency_cycle() -> None:
            async with WebTransportClient(config=client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{ECHO_ENDPOINT}")
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_STREAMS)

                tasks = [
                    asyncio.create_task(stream_worker(session=session, semaphore=semaphore))
                    for _ in range(stream_count)
                ]
                await asyncio.gather(*tasks)

        benchmark(lambda: asyncio.run(run_concurrency_cycle()))

        mean_time = benchmark.stats["mean"]
        total_data_mb = (stream_count * (len(payload) + len(expected_response))) / (1024 * 1024)
        aggregate_throughput_mbps = total_data_mb / mean_time if mean_time > 0 else 0

        benchmark.extra_info["total_streams"] = stream_count
        benchmark.extra_info["concurrency_limit"] = MAX_CONCURRENT_STREAMS
        benchmark.extra_info["aggregate_throughput_mbps"] = f"{aggregate_throughput_mbps:.2f}"

        logger.info(
            "Workload: %s streams (limit %s) | Throughput: %.2f MB/s",
            stream_count,
            MAX_CONCURRENT_STREAMS,
            aggregate_throughput_mbps,
        )
