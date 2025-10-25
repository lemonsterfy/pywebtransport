"""Performance benchmark for WebTransport connection establishment."""

import asyncio
import logging
import ssl
from typing import Final

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from pywebtransport import ClientConfig, ConnectionError, WebTransportClient

CONCURRENCY_LEVEL: Final[int] = 100
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
CONNECTION_TEST_ENDPOINT: Final[str] = "/connection_test"

logger = logging.getLogger("test_01_connection")


@pytest.fixture(scope="module")
def default_client_config() -> ClientConfig:
    """Provide a default client configuration for latency tests."""
    return ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=15.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )


@pytest.fixture(scope="module")
def concurrency_client_config() -> ClientConfig:
    """Provide a client configuration suitable for high-concurrency tests."""
    return ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=30.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )


class TestConnectionPerformance:
    """Performance tests for connection establishment."""

    def test_connection_establishment_latency(
        self, benchmark: BenchmarkFixture, default_client_config: ClientConfig
    ) -> None:
        """Benchmark the latency of a single client connect-and-close operation."""

        async def connect_and_close() -> None:
            async with WebTransportClient(config=default_client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{CONNECTION_TEST_ENDPOINT}")
                await session.close()

        benchmark(lambda: asyncio.run(connect_and_close()))

    def test_high_concurrency_throughput(
        self, benchmark: BenchmarkFixture, concurrency_client_config: ClientConfig
    ) -> None:
        """Benchmark the server's ability to handle a high volume of concurrent connections."""

        async def single_client_task(*, config: ClientConfig) -> bool:
            try:
                async with WebTransportClient(config=config) as client:
                    session = await client.connect(url=f"{SERVER_URL}{CONNECTION_TEST_ENDPOINT}")
                    await asyncio.sleep(0.01)
                    await session.close()
                return True
            except (ConnectionError, asyncio.TimeoutError) as e:
                logger.warning("A concurrent connection task failed: %s", e)
                return False
            except Exception as e:
                logger.error("Unexpected error in concurrent task: %s", e, exc_info=True)
                return False

        async def connect_all_concurrently() -> int:
            tasks = [
                asyncio.create_task(single_client_task(config=concurrency_client_config))
                for _ in range(CONCURRENCY_LEVEL)
            ]
            results = await asyncio.gather(*tasks)
            return sum(1 for r in results if r)

        successful_connections = benchmark(lambda: asyncio.run(connect_all_concurrently()))

        logger.info(
            "Concurrency Test Iteration: %s/%s connections succeeded.",
            successful_connections,
            CONCURRENCY_LEVEL,
        )
        assert (
            successful_connections >= CONCURRENCY_LEVEL * 0.95
        ), f"High failure rate: Only {successful_connections}/{CONCURRENCY_LEVEL} succeeded."

        mean_time = benchmark.stats["mean"]
        connections_per_second = CONCURRENCY_LEVEL / mean_time if mean_time > 0 else 0
        benchmark.extra_info["connections_per_second"] = f"{connections_per_second:.2f}"
        logger.info("Connection Throughput: %.2f connections/sec", connections_per_second)
