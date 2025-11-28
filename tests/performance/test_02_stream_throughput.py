"""Performance benchmark for WebTransport stream throughput."""

import asyncio
import ssl
from hashlib import md5
from typing import Any, Final, Protocol, cast

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from pywebtransport import ClientConfig, WebTransportClient

DATA_SIZES: Final[list[int]] = [64 * 1024, 256 * 1024, 1024 * 1024]
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
ECHO_ENDPOINT: Final[str] = "/echo"
DISCARD_ENDPOINT: Final[str] = "/discard"
PRODUCE_ENDPOINT: Final[str] = "/produce"

_test_data_cache: dict[int, bytes] = {}


class DataFactoryProtocol(Protocol):
    """A protocol for the test data factory function."""

    def __call__(self, *, size: int) -> bytes: ...


@pytest.fixture(scope="module")
def client_config() -> ClientConfig:
    """Provide a client configuration with generous timeouts for large data transfers."""
    return ClientConfig(
        verify_mode=ssl.CERT_NONE,
        connect_timeout=15.0,
        read_timeout=60.0,
        write_timeout=60.0,
        initial_max_data=1024 * 1024 * 10,
        initial_max_streams_bidi=100,
        initial_max_streams_uni=100,
    )


@pytest.fixture(scope="module")
def get_test_data() -> DataFactoryProtocol:
    """Provide a factory function to generate and cache test data of a given size."""

    def _data_factory(*, size: int) -> bytes:
        if size not in _test_data_cache:
            _test_data_cache[size] = md5(f"pywebtransport_test_data_{size}".encode()).digest() * (size // 16 + 1)
        return _test_data_cache[size][:size]

    return _data_factory


@pytest.mark.parametrize("data_size", DATA_SIZES)
class TestStreamThroughput:
    """Benchmark tests for different stream types and data sizes."""

    def test_bidirectional_throughput(
        self,
        benchmark: BenchmarkFixture,
        client_config: ClientConfig,
        get_test_data: DataFactoryProtocol,
        data_size: int,
    ) -> None:
        """Benchmark bidirectional stream echo performance."""
        test_data = get_test_data(size=data_size)
        expected_response = b"ECHO: " + test_data

        async def run_bidi_transfer() -> bytes:
            async with WebTransportClient(config=client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{ECHO_ENDPOINT}")
                stream = await session.create_bidirectional_stream()
                await stream.write_all(data=test_data)
                response = await stream.read_all()
                return response

        def benchmark_wrapper() -> None:
            response = asyncio.run(run_bidi_transfer())
            assert response == expected_response

        benchmark(benchmark_wrapper)

        stats = cast(dict[str, Any], benchmark.stats)
        mean_time = stats["mean"]
        megabytes_transferred = (len(test_data) + len(expected_response)) / (1024 * 1024)
        benchmark.extra_info["mb_per_second"] = megabytes_transferred / mean_time if mean_time > 0 else 0

    def test_upload_throughput(
        self,
        benchmark: BenchmarkFixture,
        client_config: ClientConfig,
        get_test_data: DataFactoryProtocol,
        data_size: int,
    ) -> None:
        """Benchmark unidirectional stream upload performance."""
        test_data = get_test_data(size=data_size)

        async def run_upload_transfer() -> None:
            async with WebTransportClient(config=client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{DISCARD_ENDPOINT}")
                stream = await session.create_unidirectional_stream()
                await stream.write_all(data=test_data)

        benchmark(lambda: asyncio.run(run_upload_transfer()))

        stats = cast(dict[str, Any], benchmark.stats)
        mean_time = stats["mean"]
        megabytes_transferred = data_size / (1024 * 1024)
        benchmark.extra_info["mb_per_second"] = megabytes_transferred / mean_time if mean_time > 0 else 0

    def test_download_throughput(
        self,
        benchmark: BenchmarkFixture,
        client_config: ClientConfig,
        data_size: int,
    ) -> None:
        """Benchmark stream download performance."""

        async def run_download_transfer() -> bytes:
            async with WebTransportClient(config=client_config) as client:
                session = await client.connect(url=f"{SERVER_URL}{PRODUCE_ENDPOINT}")
                stream = await session.create_bidirectional_stream()
                await stream.write_all(data=f"SEND:{data_size}".encode())
                response = await stream.read_all()
                return response

        def benchmark_wrapper() -> None:
            response = asyncio.run(run_download_transfer())
            assert len(response) == data_size

        benchmark(benchmark_wrapper)

        stats = cast(dict[str, Any], benchmark.stats)
        mean_time = stats["mean"]
        megabytes_transferred = data_size / (1024 * 1024)
        benchmark.extra_info["mb_per_second"] = megabytes_transferred / mean_time if mean_time > 0 else 0
