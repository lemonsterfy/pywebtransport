"""
Tests for server resource usage under various connection loads.
"""

import asyncio
import json
import logging
import ssl
import sys
from typing import Any, Final, cast

import pytest

from pywebtransport import ClientConfig, ConnectionError, StreamError, WebTransportClient, WebTransportSession

IDLE_CONNECTION_COUNT: Final[int] = 20
LOADED_CONNECTION_COUNT: Final[int] = 20
LOAD_TEST_DURATION: Final[int] = 15
MAX_MEMORY_PER_IDLE_CONNECTION_KB: Final[float] = 2048.0
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
STABILIZATION_DELAY: Final[int] = 5
RESOURCE_USAGE_ENDPOINT: Final[str] = "/resource_usage"
PERSISTENT_ECHO_ENDPOINT: Final[str] = "/persistent_echo"

logger = logging.getLogger("test_06_resource_usage")
perf_logger = logging.getLogger("performance_results")
perf_logger.propagate = False
if not perf_logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    perf_logger.addHandler(handler)
perf_logger.setLevel(logging.INFO)


async def get_server_resources(*, config: ClientConfig) -> dict[str, Any]:
    """Retrieve resource usage statistics from the test server with retries."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with WebTransportClient(config=config) as client:
                session = await client.connect(url=f"{SERVER_URL}{RESOURCE_USAGE_ENDPOINT}")
                stream = await session.create_bidirectional_stream()
                await stream.write_all(data=b"GET")
                response_bytes = await stream.read_all()
                return cast(dict[str, Any], json.loads(response_bytes))
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(
                    "Failed to get server resources on attempt %s/%s: %s. Retrying...",
                    attempt + 1,
                    max_retries,
                    e,
                )
                await asyncio.sleep(2.0)
            else:
                logger.error("Failed to get server resources after %s attempts: %s", max_retries, e)
                pytest.fail("Could not retrieve server resource statistics.")
    return {}


@pytest.mark.asyncio
class TestResourceUsage:
    """A test suite for measuring server resource consumption."""

    @pytest.fixture(scope="class")
    def client_config(self) -> ClientConfig:
        """Provide a client configuration for resource tests."""
        return ClientConfig.create(verify_mode=ssl.CERT_NONE, connect_timeout=15.0, read_timeout=15.0)

    async def test_idle_connections_memory(self, client_config: ClientConfig) -> None:
        """Measure the memory increase caused by establishing idle connections."""
        perf_logger.info("\n--- [Idle Connection Memory Test] (%s connections) ---", IDLE_CONNECTION_COUNT)
        baseline = await get_server_resources(config=client_config)
        perf_logger.info(
            "Baseline: %.2f MB RAM | %s connections",
            baseline["memory_rss_bytes"] / 1024**2,
            baseline["active_connections"],
        )

        idle_sessions: list[WebTransportSession] = []
        try:
            async with WebTransportClient(config=client_config) as client:
                connect_tasks = [
                    client.connect(url=f"{SERVER_URL}{PERSISTENT_ECHO_ENDPOINT}") for _ in range(IDLE_CONNECTION_COUNT)
                ]
                results = await asyncio.gather(*connect_tasks, return_exceptions=True)
                idle_sessions = [s for s in results if isinstance(s, WebTransportSession)]
                assert (
                    len(idle_sessions) >= IDLE_CONNECTION_COUNT * 0.95
                ), "Failed to establish enough idle connections."

                perf_logger.info(
                    "Established %s idle connections. Waiting %ss...", len(idle_sessions), STABILIZATION_DELAY
                )
                await asyncio.sleep(STABILIZATION_DELAY)

                idle_load = await get_server_resources(config=client_config)
                perf_logger.info(
                    "Idle Load: %.2f MB RAM | %s connections",
                    idle_load["memory_rss_bytes"] / 1024**2,
                    idle_load["active_connections"],
                )

                memory_increase = idle_load["memory_rss_bytes"] - baseline["memory_rss_bytes"]
                memory_per_connection_kb = (memory_increase / len(idle_sessions)) / 1024

                perf_logger.info("Result: Memory increase per idle connection: %.2f KB", memory_per_connection_kb)
                assert memory_per_connection_kb < MAX_MEMORY_PER_IDLE_CONNECTION_KB, (
                    f"Memory per idle connection ({memory_per_connection_kb:.2f} KB) "
                    f"exceeds threshold ({MAX_MEMORY_PER_IDLE_CONNECTION_KB:.2f} KB)"
                )
        finally:
            cleanup_tasks = [s.close() for s in idle_sessions if not s.is_closed]
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            perf_logger.info("Cleaned up idle connections.")

    async def test_loaded_connections_cpu(self, client_config: ClientConfig) -> None:
        """Measure the CPU increase caused by connections under a constant load."""
        perf_logger.info("\n--- [Loaded Connection CPU Test] (%s connections) ---", LOADED_CONNECTION_COUNT)
        baseline_resources = await get_server_resources(config=client_config)
        perf_logger.info("Baseline: %.2f%% CPU", baseline_resources["cpu_percent"])

        load_sessions: list[WebTransportSession] = []
        load_tasks: list[asyncio.Task] = []
        try:
            async with WebTransportClient(config=client_config) as client:
                connect_tasks = [
                    client.connect(url=f"{SERVER_URL}{PERSISTENT_ECHO_ENDPOINT}")
                    for _ in range(LOADED_CONNECTION_COUNT)
                ]
                results = await asyncio.gather(*connect_tasks, return_exceptions=True)
                load_sessions = [s for s in results if isinstance(s, WebTransportSession)]
                assert (
                    len(load_sessions) >= LOADED_CONNECTION_COUNT * 0.95
                ), "Failed to establish enough load connections."

                load_tasks = [asyncio.create_task(self._run_load_task(session=s)) for s in load_sessions]
                perf_logger.info("Started %s load tasks. Running for %ss...", len(load_tasks), LOAD_TEST_DURATION)

                cpu_samples = []
                end_time = asyncio.get_running_loop().time() + LOAD_TEST_DURATION
                while asyncio.get_running_loop().time() < end_time:
                    resources = await get_server_resources(config=client_config)
                    cpu_samples.append(resources["cpu_percent"])
                    await asyncio.sleep(2)

                avg_cpu_under_load = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
                cpu_increase = avg_cpu_under_load - baseline_resources["cpu_percent"]
                cpu_per_connection = cpu_increase / len(load_sessions) if load_sessions else 0
                perf_logger.info("Average CPU under load: %.2f%%", avg_cpu_under_load)
                perf_logger.info("Result: CPU increase per loaded connection: %.2f%%", cpu_per_connection)
                assert cpu_per_connection < 5.0, f"CPU per loaded connection ({cpu_per_connection:.2f}%) seems high."
        finally:
            for task in load_tasks:
                task.cancel()
            if load_tasks:
                await asyncio.gather(*load_tasks, return_exceptions=True)

            cleanup_tasks = [s.close() for s in load_sessions if not s.is_closed]
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            perf_logger.info("Cleaned up loaded connections.")

    async def _run_load_task(self, *, session: WebTransportSession) -> None:
        """Run a continuous echo load on a single session."""
        payload = b"l" * 1024
        try:
            stream = await session.create_bidirectional_stream()
            while True:
                await stream.write(data=payload)
                await stream.read(size=2048)
                await asyncio.sleep(0.01)
        except (asyncio.CancelledError, ConnectionError, StreamError):
            pass
        except Exception as e:
            logger.error("Error during load generation for session %s: %s", session.session_id, e)
