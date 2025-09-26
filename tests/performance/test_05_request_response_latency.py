"""Performance benchmark for request-response latency."""

import asyncio
import logging
import ssl
from typing import Final, Protocol

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from pywebtransport import ClientConfig, WebTransportClient

PAYLOAD_SIZES: Final[list[int]] = [64, 1024, 8192]
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
REQUEST_RESPONSE_ENDPOINT: Final[str] = "/request_response"

_test_data_cache: dict[int, bytes] = {}

logger = logging.getLogger("test_05_request_response_latency")


class DataFactoryProtocol(Protocol):
    """A protocol for the test data factory function."""

    def __call__(self, *, size: int) -> bytes: ...


@pytest.fixture(scope="module")
def client_config() -> ClientConfig:
    """Provide a client configuration suitable for latency tests."""
    return ClientConfig.create(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=15.0,
        read_timeout=10.0,
        write_timeout=10.0,
        initial_max_data=1024 * 1024,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )


@pytest.fixture(scope="module")
def get_test_data() -> DataFactoryProtocol:
    """Provide a factory function to get cached, pre-generated test data."""

    def _data_factory(*, size: int) -> bytes:
        if size not in _test_data_cache:
            _test_data_cache[size] = b"r" * size
        return _test_data_cache[size]

    return _data_factory


@pytest.mark.parametrize("payload_size", PAYLOAD_SIZES)
class TestRequestResponseLatency:
    """Benchmark tests for request-response latency with varying payload sizes."""

    def test_request_response_latency(
        self,
        benchmark: BenchmarkFixture,
        client_config: ClientConfig,
        get_test_data: DataFactoryProtocol,
        payload_size: int,
    ) -> None:
        """Benchmark the end-to-end latency of a full request-response cycle."""
        request_data = get_test_data(size=payload_size)
        expected_response_len = len(request_data)

        async def run_full_cycle() -> bytes:
            async with WebTransportClient(config=client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{REQUEST_RESPONSE_ENDPOINT}")
                stream = await session.create_bidirectional_stream()
                await stream.write_all(data=request_data)
                response = await stream.read_all()
                return response

        response = benchmark(lambda: asyncio.run(run_full_cycle()))
        assert len(response) == expected_response_len

        mean_time = benchmark.stats["mean"]
        benchmark.extra_info["latency_ms"] = mean_time * 1000
        benchmark.extra_info["payload_size_bytes"] = payload_size
