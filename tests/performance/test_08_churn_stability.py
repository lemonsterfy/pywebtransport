"""
Server stability and memory leak tests under high connection churn.
"""

import asyncio
import json
import logging
import ssl
from collections.abc import AsyncGenerator
from typing import Any, Final, cast

import pytest

from pywebtransport import ClientConfig, WebTransportClient

CHURN_CLIENT_COUNT: Final[int] = 50
CHURN_CLIENT_CONCURRENCY: Final[int] = 5
STABILITY_TEST_ROUNDS: Final[int] = 3
INITIAL_STABILIZATION_SECONDS: Final[int] = 15
COOLDOWN_SECONDS: Final[int] = 90
BASELINE_SAMPLING_COUNT: Final[int] = 5
BASELINE_SAMPLING_INTERVAL: Final[float] = 2.0
MEMORY_LEAK_THRESHOLD_ABSOLUTE_KB: Final[float] = 8192.0
MEMORY_LEAK_THRESHOLD_RELATIVE: Final[float] = 0.15
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
CHURN_ECHO_ENDPOINT: Final[str] = "/echo"
RESOURCE_USAGE_ENDPOINT: Final[str] = "/resource_usage"

logger = logging.getLogger("test_08_connection_churn_stability")


async def get_server_resources(*, client: WebTransportClient) -> dict[str, Any]:
    """Retrieve resource usage statistics from the test server using a persistent client."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            session = await client.connect(url=f"{SERVER_URL}{RESOURCE_USAGE_ENDPOINT}")
            async with session:
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


class MemoryMonitor:
    """Monitor and analyze the memory usage of a process over multiple rounds."""

    def __init__(self, measurement_client: WebTransportClient):
        """Initialize the memory monitor with a dedicated measurement client."""
        self._measurement_client = measurement_client
        self._baselines_kb: list[float] = []

    async def get_current_memory_kb(self) -> float:
        """Get the current RSS memory of the server in kilobytes via remote query."""
        try:
            resources = await get_server_resources(client=self._measurement_client)
            rss_bytes = resources["memory_rss_bytes"]
            return cast(float, rss_bytes / 1024)
        except Exception:
            pytest.fail("Failed to query server memory.")

    async def record_baseline(self, *, round_num: int) -> None:
        """Record a stable memory baseline by averaging multiple samples."""
        samples = []
        logger.info("Sampling for baseline after Round %s (%s samples)...", round_num, BASELINE_SAMPLING_COUNT)
        for i in range(BASELINE_SAMPLING_COUNT):
            samples.append(await self.get_current_memory_kb())
            if i < BASELINE_SAMPLING_COUNT - 1:
                await asyncio.sleep(BASELINE_SAMPLING_INTERVAL)

        baseline_kb = sum(samples) / len(samples)
        self._baselines_kb.append(baseline_kb)
        logger.info(
            "End of Round %s stable memory baseline: %,.2f KB (avg of %s samples)",
            round_num,
            baseline_kb,
            len(samples),
        )

    def analyze(self) -> None:
        """Analyze memory growth between rounds to detect potential leaks."""
        logger.info("\n--- [Final Connection Churn Memory Leak Analysis] ---")
        if len(self._baselines_kb) <= 1:
            logger.warning("Not enough rounds to perform leak analysis (at least 2 rounds required).")
            return

        for i in range(1, len(self._baselines_kb)):
            prev_baseline = self._baselines_kb[i - 1]
            current_baseline = self._baselines_kb[i]
            growth_abs = current_baseline - prev_baseline
            growth_rel = growth_abs / prev_baseline if prev_baseline > 0 else 0

            logger.info("Analyzing growth from Round %s to Round %s:", i, i + 1)
            logger.info("  - Baseline after Round %s:   %,.2f KB", i, prev_baseline)
            logger.info("  - Baseline after Round %s: %,.2f KB", i + 1, current_baseline)
            logger.info("  - Irreversible Growth: %,.2f KB (%.2f%%)", growth_abs, growth_rel * 100)

            assert growth_abs < MEMORY_LEAK_THRESHOLD_ABSOLUTE_KB, (
                f"Absolute memory leak detected! Growth of {growth_abs:,.2f} KB "
                f"in Round {i+1} exceeds threshold of {MEMORY_LEAK_THRESHOLD_ABSOLUTE_KB:,.2f} KB."
            )
            assert growth_rel < MEMORY_LEAK_THRESHOLD_RELATIVE, (
                f"Relative memory leak detected! Growth of {growth_rel:.2%} "
                f"in Round {i+1} exceeds threshold of {MEMORY_LEAK_THRESHOLD_RELATIVE:.2%}."
            )

        logger.info("SUCCESS: No trend of irreversible memory growth detected across all rounds.")


@pytest.mark.asyncio
class TestConnectionChurnStability:
    """Test server stability under high connection churn."""

    @pytest.fixture(scope="class")
    def client_config(self) -> ClientConfig:
        """Provide a client configuration suitable for churn tests."""
        return ClientConfig.create(
            verify_mode=ssl.CERT_NONE,
            connect_timeout=20.0,
            read_timeout=10.0,
            write_timeout=10.0,
        )

    @pytest.fixture(scope="class")
    async def measurement_client(self, client_config: ClientConfig) -> AsyncGenerator[WebTransportClient, None]:
        """Provide a single, long-lived client for all measurement tasks."""
        client = WebTransportClient(config=client_config)
        async with client:
            yield client

    async def test_connection_churn_memory_leaks(
        self, client_config: ClientConfig, measurement_client: WebTransportClient
    ) -> None:
        """Execute a multi-round churn test to detect memory leaks."""
        logger.info("\n--- [Connection Churn Stability Test using Phased Repetition] ---")
        monitor = MemoryMonitor(measurement_client)

        await asyncio.sleep(INITIAL_STABILIZATION_SECONDS)

        for i in range(STABILITY_TEST_ROUNDS):
            round_num = i + 1
            if round_num == 1:
                logger.info("\n--- Starting Definitive Warmup Round (Round %s) ---", round_num)
            else:
                logger.info("\n--- Starting Churn Test Round %s/%s ---", round_num, STABILITY_TEST_ROUNDS)

            logger.info("[%s] Starting %s churn connections...", round_num, CHURN_CLIENT_COUNT)
            churn_semaphore = asyncio.Semaphore(CHURN_CLIENT_CONCURRENCY)

            async def churn_task_wrapper() -> None:
                async with churn_semaphore:
                    await self._churn_worker(config=client_config)

            churn_tasks = [asyncio.create_task(churn_task_wrapper()) for _ in range(CHURN_CLIENT_COUNT)]
            await asyncio.gather(*churn_tasks)
            logger.info("[%s] All churn connections completed.", round_num)

            logger.info("[%s] Starting cooldown and GC period (%ss)...", round_num, COOLDOWN_SECONDS)
            await asyncio.sleep(COOLDOWN_SECONDS)
            await monitor.record_baseline(round_num=round_num)

        monitor.analyze()

    async def _churn_worker(self, *, config: ClientConfig) -> None:
        """A short-lived worker that connects, echoes, and disconnects."""
        try:
            async with WebTransportClient(config=config) as client:
                async with await client.connect(url=f"{SERVER_URL}{CHURN_ECHO_ENDPOINT}") as session:
                    stream = await session.create_bidirectional_stream()
                    await stream.write_all(data=b"churn_test")
                    await stream.read_all()
        except Exception:
            pass
