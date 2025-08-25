"""
WebTransport Client Utilities.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.utils import get_logger, get_timestamp

__all__ = [
    "benchmark_client_performance",
    "test_client_connectivity",
]

logger = get_logger("client.utils")


async def benchmark_client_performance(
    url: str,
    *,
    config: ClientConfig | None = None,
    num_requests: int = 100,
    concurrent_requests: int = 10,
) -> dict[str, Any]:
    """Benchmark client performance by measuring request-response latency."""
    results: dict[str, Any] = {
        "total_requests": num_requests,
        "successful_requests": 0,
        "failed_requests": 0,
        "latencies": [],
    }
    semaphore = asyncio.Semaphore(concurrent_requests)

    async def benchmark_single_request(client: WebTransportClient) -> float:
        async with semaphore:
            start_time = get_timestamp()
            session = await client.connect(url)
            try:
                stream = await session.create_bidirectional_stream()
                await stream.write(b"benchmark_ping")
                _ = await stream.read(size=1024)
                latency = get_timestamp() - start_time
                return latency
            finally:
                if session and not session.is_closed:
                    await session.close()

    tasks: list[asyncio.Task[float]] = []
    async with WebTransportClient.create(config=config) as client:
        try:
            async with asyncio.TaskGroup() as tg:
                for _ in range(num_requests):
                    tasks.append(tg.create_task(benchmark_single_request(client)))
        except* Exception as eg:
            logger.warning(f"{len(eg.exceptions)} benchmark requests failed.")

    for task in tasks:
        if task.done() and not task.exception():
            results["successful_requests"] += 1
            results["latencies"].append(task.result())
        else:
            results["failed_requests"] += 1

    if results["latencies"]:
        latencies = results["latencies"]
        results["avg_latency"] = sum(latencies) / len(latencies)
        results["min_latency"] = min(latencies)
        results["max_latency"] = max(latencies)

    return results


async def test_client_connectivity(
    url: str, *, config: ClientConfig | None = None, timeout: float = 10.0
) -> dict[str, Any]:
    """Test client connectivity to a given URL."""
    async with WebTransportClient.create(config=config) as client:
        try:
            start_time = get_timestamp()
            session = await asyncio.wait_for(client.connect(url, timeout=timeout), timeout=timeout)
            connect_time = get_timestamp() - start_time
            await session.close()
            return {"success": True, "connect_time": connect_time, "client_stats": client.stats}
        except Exception as e:
            return {"success": False, "error": str(e), "connect_time": None, "client_stats": client.stats}
