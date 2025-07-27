"""
WebTransport Client Utilities.

This module provides a collection of utility functions for creating,
testing, and debugging WebTransportClient instances and its variants.
"""

import asyncio
from typing import Any, Dict, Optional

from ..config import ClientConfig
from ..utils import get_logger, get_timestamp
from .client import WebTransportClient

logger = get_logger("client.utils")

__all__ = [
    "benchmark_client_performance",
    "test_client_connectivity",
]


async def benchmark_client_performance(
    url: str,
    *,
    config: Optional[ClientConfig] = None,
    num_requests: int = 100,
    concurrent_requests: int = 10,
) -> Dict[str, Any]:
    """Benchmark client performance by measuring request-response latency."""
    results: Dict[str, Any] = {
        "total_requests": num_requests,
        "successful_requests": 0,
        "failed_requests": 0,
        "latencies": [],
    }
    semaphore = asyncio.Semaphore(concurrent_requests)

    async def benchmark_single_request(client: WebTransportClient) -> Optional[float]:
        async with semaphore:
            try:
                start_time = get_timestamp()
                session = await client.connect(url)
                stream = await session.create_bidirectional_stream()
                await stream.write(b"benchmark_ping")
                _ = await stream.read(size=1024)
                latency = get_timestamp() - start_time
                await session.close()
                return latency
            except Exception as e:
                logger.warning(f"Benchmark request failed: {e}")
                return None

    async with WebTransportClient.create(config=config) as client:
        tasks = [asyncio.create_task(benchmark_single_request(client)) for _ in range(num_requests)]
        latency_results = await asyncio.gather(*tasks)

    for latency in latency_results:
        if latency is not None:
            results["successful_requests"] += 1
            results["latencies"].append(latency)
        else:
            results["failed_requests"] += 1

    if results["latencies"]:
        latencies = results["latencies"]
        results["avg_latency"] = sum(latencies) / len(latencies)
        results["min_latency"] = min(latencies)
        results["max_latency"] = max(latencies)

    return results


async def test_client_connectivity(
    url: str, *, config: Optional[ClientConfig] = None, timeout: float = 10.0
) -> Dict[str, Any]:
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
