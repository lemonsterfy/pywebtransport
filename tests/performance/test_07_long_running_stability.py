"""
Long-running stability and memory leak tests for the server.
"""

import asyncio
import logging
import os
import ssl
from typing import Any, Final, cast

import psutil
import pytest

from pywebtransport import ClientConfig, ConnectionError, WebTransportClient, WebTransportSession

PERSISTENT_CLIENT_COUNT: Final[int] = 2
STABILITY_TEST_ROUNDS: Final[int] = 3
ROUND_DURATION_SECONDS: Final[int] = int(os.getenv("STABILITY_TEST_DURATION", "45"))
INITIAL_STABILIZATION_SECONDS: Final[int] = 15
COOLDOWN_SECONDS: Final[int] = 60
BASELINE_SAMPLING_COUNT: Final[int] = 5
BASELINE_SAMPLING_INTERVAL: Final[float] = 2.0
MEMORY_LEAK_THRESHOLD_ABSOLUTE_KB: Final[float] = 2048.0
MEMORY_LEAK_THRESHOLD_RELATIVE: Final[float] = 0.05
SERVER_URL: Final[str] = "https://127.0.0.1:4433"
SERVER_PORT: Final[int] = 4433
PERSISTENT_ECHO_ENDPOINT: Final[str] = "/persistent_echo"

logger = logging.getLogger("test_07_long_running_stability")


def _get_server_pid(port: int) -> int | None:
    """Find the PID of the server process listening on the specified UDP port."""
    try:
        for conn in psutil.net_connections(kind="udp"):
            if conn.laddr and conn.laddr.port == port and conn.pid:
                logger.info(f"Found server process with PID {conn.pid} on UDP port {port}.")
                return conn.pid
    except Exception as e:
        logger.error(f"Could not get server PID: {e}")
    return None


class MemoryMonitor:
    """Monitor and analyze the memory usage of a process over multiple rounds."""

    def __init__(self, process: psutil.Process):
        """Initialize the memory monitor with the target process."""
        self._process = process
        self._baselines_kb: list[float] = []

    def get_current_memory_kb(self) -> float:
        """Get the current RSS memory of the process in kilobytes."""
        try:
            rss_bytes = self._process.memory_info().rss
            return cast(float, rss_bytes / 1024)
        except psutil.NoSuchProcess:
            pytest.fail(f"Server process {self._process.pid} disappeared.")

    async def record_baseline(self, round_num: int) -> None:
        """Record a stable memory baseline by averaging multiple samples."""
        samples = []
        logger.info(f"Sampling for baseline after Round {round_num} ({BASELINE_SAMPLING_COUNT} samples)...")
        for i in range(BASELINE_SAMPLING_COUNT):
            samples.append(self.get_current_memory_kb())
            if i < BASELINE_SAMPLING_COUNT - 1:
                await asyncio.sleep(BASELINE_SAMPLING_INTERVAL)

        baseline_kb = sum(samples) / len(samples)
        self._baselines_kb.append(baseline_kb)
        logger.info(
            f"End of Round {round_num} stable memory baseline: {baseline_kb:,.2f} KB (avg of {len(samples)} samples)"
        )

    def analyze(self) -> None:
        """Analyze memory growth between rounds to detect potential leaks."""
        logger.info("\n--- [Final Long-Running Memory Leak Analysis] ---")
        if len(self._baselines_kb) <= 1:
            logger.warning("Not enough rounds to perform leak analysis (at least 2 rounds required).")
            return

        for i in range(1, len(self._baselines_kb)):
            prev_baseline = self._baselines_kb[i - 1]
            current_baseline = self._baselines_kb[i]
            growth_abs = current_baseline - prev_baseline
            growth_rel = growth_abs / prev_baseline if prev_baseline > 0 else 0

            logger.info(f"Analyzing growth from Round {i} to Round {i+1}:")
            logger.info(f"  - Baseline after Round {i}:   {prev_baseline:,.2f} KB")
            logger.info(f"  - Baseline after Round {i+1}: {current_baseline:,.2f} KB")
            logger.info(f"  - Irreversible Growth: {growth_abs:,.2f} KB ({growth_rel:.2%})")

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
class TestLongRunningStability:
    """Test server stability and resource usage under sustained, long-running client load."""

    @pytest.fixture(scope="class")
    def client_config(self) -> ClientConfig:
        """Provide a client configuration for long-running stability tests."""
        return ClientConfig.create(
            verify_mode=ssl.CERT_NONE,
            connect_timeout=20.0,
            read_timeout=40.0,
            write_timeout=40.0,
        )

    async def test_long_running_memory_stability(self, client_config: ClientConfig) -> None:
        """Execute a multi-round stability test to detect memory leaks."""
        logger.info("\n--- [Long-Running Stability Test using Phased Repetition] ---")
        server_pid = _get_server_pid(SERVER_PORT)
        assert server_pid is not None, f"Could not find server process on port {SERVER_PORT}."

        server_process = psutil.Process(server_pid)
        monitor = MemoryMonitor(server_process)

        await asyncio.sleep(INITIAL_STABILIZATION_SECONDS)

        for i in range(STABILITY_TEST_ROUNDS):
            round_num = i + 1
            if round_num == 1:
                logger.info(f"\n--- Starting Definitive Warmup Round (Round {round_num}) ---")
            else:
                logger.info(f"\n--- Starting Stability Test Round {round_num}/{STABILITY_TEST_ROUNDS} ---")

            stop_event = asyncio.Event()
            persistent_tasks: list[asyncio.Task[Any]] = []
            persistent_sessions: list[WebTransportSession] = []

            async with WebTransportClient.create(config=client_config) as client:
                try:
                    logger.info(f"[{round_num}] Ramping up {PERSISTENT_CLIENT_COUNT} persistent clients...")
                    connect_tasks = [
                        client.connect(f"{SERVER_URL}{PERSISTENT_ECHO_ENDPOINT}")
                        for _ in range(PERSISTENT_CLIENT_COUNT)
                    ]
                    sessions = await asyncio.gather(*connect_tasks, return_exceptions=True)
                    persistent_sessions.extend(s for s in sessions if isinstance(s, WebTransportSession))

                    if len(persistent_sessions) < PERSISTENT_CLIENT_COUNT:
                        pytest.fail(f"Failed to establish all persistent connections in Round {round_num}.")

                    for session in persistent_sessions:
                        task = asyncio.create_task(self._persistent_client_worker(session, stop_event))
                        persistent_tasks.append(task)

                    logger.info(f"[{round_num}] Stable load running for {ROUND_DURATION_SECONDS}s...")
                    await asyncio.sleep(ROUND_DURATION_SECONDS)
                finally:
                    logger.info(f"[{round_num}] Tearing down all connections...")
                    stop_event.set()
                    if persistent_tasks:
                        await asyncio.gather(*persistent_tasks, return_exceptions=True)

                    if persistent_sessions:
                        close_tasks = [s.close() for s in persistent_sessions if not s.is_closed]
                        if close_tasks:
                            await asyncio.gather(*close_tasks, return_exceptions=True)
                    logger.info(f"[{round_num}] All client tasks and sessions for this round are closed.")

            logger.info(f"[{round_num}] Starting cooldown and GC period ({COOLDOWN_SECONDS}s)...")
            await asyncio.sleep(COOLDOWN_SECONDS)
            await monitor.record_baseline(round_num)

        monitor.analyze()

    async def _persistent_client_worker(self, session: WebTransportSession, stop_event: asyncio.Event) -> None:
        """A worker that maintains a connection and continuously echoes data."""
        try:
            stream = await session.create_bidirectional_stream()
            payload = b"p" * 1024
            expected_response = b"ECHO: " + payload

            while not stop_event.is_set():
                await stream.write(payload)
                response = await stream.readexactly(len(expected_response))
                assert response == expected_response
                await asyncio.sleep(0.1)
        except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            pytest.fail(f"Persistent client failed unexpectedly: {e}")
