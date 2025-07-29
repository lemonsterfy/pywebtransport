"""End-to-end tests for the pywebtransport client."""

import asyncio
import ssl
import subprocess
import sys
from typing import AsyncGenerator

import pytest

from pywebtransport import ClientConfig, ClientError, WebTransportClient

from .test_01_basic_connection import test_basic_connection as run_01_basic_connection
from .test_02_simple_stream import (
    test_multiple_messages as run_02_multiple_messages,
    test_simple_echo as run_02_simple_echo,
    test_stream_creation as run_02_stream_creation,
)
from .test_03_concurrent_streams import (
    test_concurrent_streams as run_03_concurrent_streams,
    test_sequential_streams as run_03_sequential_streams,
    test_stream_lifecycle as run_03_stream_lifecycle,
    test_stream_stress as run_03_stream_stress,
)
from .test_04_data_transfer import (
    test_binary_data as run_04_binary_data,
    test_chunked_transfer as run_04_chunked_transfer,
    test_medium_data as run_04_medium_data,
    test_performance_benchmark as run_04_performance_benchmark,
    test_small_data as run_04_small_data,
)
from .test_05_datagrams import (
    test_basic_datagram as run_05_basic_datagram,
    test_datagram_burst as run_05_datagram_burst,
    test_datagram_priority as run_05_datagram_priority,
    test_datagram_queue_behavior as run_05_datagram_queue_behavior,
    test_datagram_sizes as run_05_datagram_sizes,
    test_datagram_ttl as run_05_datagram_ttl,
    test_json_datagrams as run_05_json_datagrams,
    test_multiple_datagrams as run_05_multiple_datagrams,
)
from .test_06_error_handling import (
    test_connection_timeout as run_06_connection_timeout,
    test_datagram_errors as run_06_datagram_errors,
    test_invalid_server_address as run_06_invalid_address,
    test_malformed_operations as run_06_malformed_operations,
    test_read_timeout as run_06_read_timeout,
    test_resource_exhaustion as run_06_resource_exhaustion,
    test_session_closure_handling as run_06_session_closure,
    test_stream_errors as run_06_stream_errors,
)
from .test_07_advanced_features import (
    test_client_statistics as run_07_client_statistics,
    test_connection_info as run_07_connection_info,
    test_datagram_statistics as run_07_datagram_statistics,
    test_performance_monitoring as run_07_performance_monitoring,
    test_session_lifecycle_events as run_07_session_lifecycle_events,
    test_session_statistics as run_07_session_statistics,
    test_stream_management as run_07_stream_management,
)


async def _is_server_ready() -> bool:
    config = ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=1.0)
    for _ in range(20):
        try:
            async with WebTransportClient.create(config=config) as client:
                session = await client.connect("https://127.0.0.1:4433/health")
                await session.close()
                return True
        except (ClientError, asyncio.TimeoutError):
            await asyncio.sleep(1)
    return False


@pytest.fixture(scope="function", autouse=True)
async def e2e_server() -> AsyncGenerator[None, None]:
    server_command = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--source=src/pywebtransport",
        "--parallel-mode",
        "-m",
        "tests.e2e.test_00_e2e_server",
    ]

    server_proc = subprocess.Popen(
        server_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    is_ready = await _is_server_ready()

    if not is_ready or server_proc.poll() is not None:
        stdout, stderr = server_proc.communicate()
        pytest.fail(
            f"E2E server failed to start or become ready. Exit code: {server_proc.returncode}\n"
            f"STDOUT:\n{stdout}\n"
            f"STDERR:\n{stderr}",
            pytrace=False,
        )

    yield

    server_proc.terminate()
    try:
        server_proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.communicate()


@pytest.mark.asyncio
class TestE2eSuite:
    async def test_01_basic_connection(self) -> None:
        assert await run_01_basic_connection() is True, "Basic connection failed"

    async def test_02_stream_creation(self) -> None:
        assert await run_02_stream_creation() is True, "Stream creation failed"

    async def test_02_simple_echo(self) -> None:
        assert await run_02_simple_echo() is True, "Simple echo failed"

    async def test_02_multiple_messages(self) -> None:
        assert await run_02_multiple_messages() is True, "Multiple messages on separate streams failed"

    async def test_03_sequential_streams(self) -> None:
        assert await run_03_sequential_streams() is True, "Sequential streams failed"

    async def test_03_concurrent_streams(self) -> None:
        assert await run_03_concurrent_streams() is True, "Concurrent streams failed"

    async def test_03_stream_lifecycle(self) -> None:
        assert await run_03_stream_lifecycle() is True, "Stream lifecycle management failed"

    async def test_03_stream_stress(self) -> None:
        assert await run_03_stream_stress() is True, "Stream stress test failed"

    async def test_04_small_data(self) -> None:
        assert await run_04_small_data() is True, "Small data transfer failed"

    async def test_04_medium_data(self) -> None:
        assert await run_04_medium_data() is True, "Medium data transfer failed"

    async def test_04_chunked_transfer(self) -> None:
        assert await run_04_chunked_transfer() is True, "Chunked data transfer failed"

    async def test_04_binary_data(self) -> None:
        assert await run_04_binary_data() is True, "Binary data transfer failed"

    async def test_04_performance_benchmark(self) -> None:
        assert await run_04_performance_benchmark() is True, "Performance benchmark failed"

    async def test_05_basic_datagram(self) -> None:
        assert await run_05_basic_datagram() is True, "Basic datagram send failed"

    async def test_05_multiple_datagrams(self) -> None:
        assert await run_05_multiple_datagrams() is True, "Multiple datagrams send failed"

    async def test_05_datagram_sizes(self) -> None:
        assert await run_05_datagram_sizes() is True, "Datagram size handling failed"

    async def test_05_datagram_priority(self) -> None:
        assert await run_05_datagram_priority() is True, "Datagram priority handling failed"

    async def test_05_datagram_ttl(self) -> None:
        assert await run_05_datagram_ttl() is True, "Datagram TTL handling failed"

    async def test_05_json_datagrams(self) -> None:
        assert await run_05_json_datagrams() is True, "JSON datagrams failed"

    async def test_05_datagram_burst(self) -> None:
        assert await run_05_datagram_burst() is True, "Datagram burst test failed"

    async def test_05_datagram_queue_behavior(self) -> None:
        assert await run_05_datagram_queue_behavior() is True, "Datagram queue behavior test failed"

    async def test_06_connection_timeout(self) -> None:
        assert await run_06_connection_timeout() is True, "Connection timeout handling failed"

    async def test_06_invalid_address(self) -> None:
        assert await run_06_invalid_address() is True, "Invalid server address handling failed"

    async def test_06_stream_errors(self) -> None:
        assert await run_06_stream_errors() is True, "Stream error handling failed"

    async def test_06_read_timeout(self) -> None:
        assert await run_06_read_timeout() is True, "Read timeout handling failed"

    async def test_06_session_closure(self) -> None:
        assert await run_06_session_closure() is True, "Session closure handling failed"

    async def test_06_datagram_errors(self) -> None:
        assert await run_06_datagram_errors() is True, "Datagram error handling failed"

    async def test_06_resource_exhaustion(self) -> None:
        assert await run_06_resource_exhaustion() is True, "Resource exhaustion handling failed"

    async def test_06_malformed_operations(self) -> None:
        assert await run_06_malformed_operations() is True, "Malformed API operations handling failed"

    async def test_07_session_statistics(self) -> None:
        assert await run_07_session_statistics() is True, "Session statistics retrieval failed"

    async def test_07_connection_info(self) -> None:
        assert await run_07_connection_info() is True, "Connection info retrieval failed"

    async def test_07_client_statistics(self) -> None:
        assert await run_07_client_statistics() is True, "Client statistics retrieval failed"

    async def test_07_stream_management(self) -> None:
        assert await run_07_stream_management() is True, "Stream management test failed"

    async def test_07_datagram_statistics(self) -> None:
        assert await run_07_datagram_statistics() is True, "Datagram statistics retrieval failed"

    async def test_07_performance_monitoring(self) -> None:
        assert await run_07_performance_monitoring() is True, "Performance monitoring test failed"

    async def test_07_session_lifecycle_events(self) -> None:
        assert await run_07_session_lifecycle_events() is True, "Session lifecycle events tracking failed"
