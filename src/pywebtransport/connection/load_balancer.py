"""
Load balancer for WebTransport connections.
"""

from __future__ import annotations

import asyncio
import random
import time
from types import TracebackType
from typing import Any, Self, Type

from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.connection.utils import test_tcp_connection
from pywebtransport.exceptions import ConnectionError
from pywebtransport.utils import get_logger

__all__ = ["ConnectionLoadBalancer"]

logger = get_logger("connection.load_balancer")


class ConnectionLoadBalancer:
    """Distributes WebTransport connections across multiple targets."""

    def __init__(
        self,
        *,
        targets: list[tuple[str, int]],
        health_check_interval: float = 30.0,
        health_check_timeout: float = 5.0,
    ):
        """Initialize the connection load balancer."""
        if not targets:
            raise ValueError("Targets list cannot be empty")

        self._targets = list(dict.fromkeys(targets))
        self._health_check_interval = health_check_interval
        self._health_check_timeout = health_check_timeout
        self._lock: asyncio.Lock | None = None
        self._current_index = 0
        self._connections: dict[str, WebTransportConnection] = {}
        self._failed_targets: set[str] = set()
        self._target_weights: dict[str, float] = {self._get_target_key(h, p): 1.0 for h, p in self._targets}
        self._target_latencies: dict[str, float] = {self._get_target_key(h, p): 0.0 for h, p in self._targets}
        self._health_check_task: asyncio.Task[None] | None = None

    @classmethod
    def create(cls, *, targets: list[tuple[str, int]]) -> Self:
        """Factory method to create a new connection load balancer instance."""
        return cls(targets=targets)

    async def __aenter__(self) -> Self:
        """Enter async context, initializing resources and starting background tasks."""
        self._lock = asyncio.Lock()
        self._start_health_check_task()
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context, shutting down the load balancer."""
        await self.shutdown()

    async def shutdown(self) -> None:
        """Shut down the load balancer and close all connections."""
        logger.info("Shutting down load balancer")
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        await self.close_all_connections()
        logger.info("Load balancer shutdown complete")

    async def get_connection(
        self,
        config: ClientConfig,
        *,
        path: str = "/",
        strategy: str = "round_robin",
    ) -> WebTransportConnection:
        """Get a connection using the specified load balancing strategy."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionLoadBalancer has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )

        host, port = await self._get_next_target(strategy)
        target_key = self._get_target_key(host, port)

        async with self._lock:
            if target_key in self._connections:
                connection = self._connections[target_key]
                if connection.is_connected:
                    logger.debug(f"Reusing connection to {host}:{port}")
                    return connection
                else:
                    del self._connections[target_key]

        logger.debug(f"Creating new connection to {host}:{port}")
        try:
            start_time = time.time()
            connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
            latency = time.time() - start_time
            async with self._lock:
                self._target_latencies[target_key] = latency
                self._failed_targets.discard(target_key)
                self._connections[target_key] = connection
            logger.info(f"Connected to {host}:{port} (latency: {latency * 1000:.1f}ms)")
            return connection
        except Exception as e:
            async with self._lock:
                self._failed_targets.add(target_key)
            logger.error(f"Failed to connect to {host}:{port}: {e}")
            raise

    async def close_all_connections(self) -> None:
        """Close all currently managed connections."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionLoadBalancer has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            connections_to_close = list(self._connections.values())
            self._connections.clear()

        logger.info(f"Closing {len(connections_to_close)} connections")
        close_tasks = [asyncio.create_task(connection.close()) for connection in connections_to_close]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        logger.info("All connections closed")

    async def update_target_weight(self, *, host: str, port: int, weight: float) -> None:
        """Update the weight for a specific target."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionLoadBalancer has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        target_key = self._get_target_key(host, port)
        async with self._lock:
            if target_key in self._target_weights:
                self._target_weights[target_key] = max(0.0, weight)
                logger.debug(f"Updated weight for {target_key}: {weight}")

    async def get_target_stats(self) -> dict[str, Any]:
        """Get health and performance statistics for all targets."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionLoadBalancer has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            stats = {}
            for host, port in self._targets:
                target_key = self._get_target_key(host, port)
                conn = self._connections.get(target_key)
                stats[target_key] = {
                    "host": host,
                    "port": port,
                    "weight": self._target_weights[target_key],
                    "latency": self._target_latencies[target_key],
                    "failed": target_key in self._failed_targets,
                    "connected": bool(conn and conn.is_connected),
                }
            return stats

    async def get_load_balancer_stats(self) -> dict[str, Any]:
        """Get high-level statistics about the load balancer."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionLoadBalancer has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            return {
                "total_targets": len(self._targets),
                "failed_targets": len(self._failed_targets),
                "active_connections": len(self._connections),
                "available_targets": len(self._targets) - len(self._failed_targets),
            }

    def _get_target_key(self, host: str, port: int) -> str:
        """Generate a unique key for a given host and port."""
        return f"{host}:{port}"

    async def _get_next_target(self, strategy: str) -> tuple[str, int]:
        """Get the next target based on the chosen load balancing strategy."""
        if self._lock is None:
            raise ConnectionError(
                "ConnectionLoadBalancer has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        async with self._lock:
            available_targets = [
                target for target in self._targets if self._get_target_key(*target) not in self._failed_targets
            ]
            if not available_targets:
                raise ConnectionError("No available targets in the load balancer.")

            if strategy == "round_robin":
                target = available_targets[self._current_index % len(available_targets)]
                self._current_index += 1
                return target
            elif strategy == "weighted":
                weights = [self._target_weights[self._get_target_key(*t)] for t in available_targets]
                total_weight = sum(weights)
                if total_weight == 0:
                    return random.choice(available_targets)
                return random.choices(available_targets, weights=weights, k=1)[0]
            elif strategy == "least_latency":
                latencies = [self._target_latencies[self._get_target_key(*t)] for t in available_targets]
                min_latency_idx = latencies.index(min(latencies))
                return available_targets[min_latency_idx]
            else:
                raise ValueError(f"Unknown load balancing strategy: {strategy}")

    def _start_health_check_task(self) -> None:
        """Start the periodic health check task if not already running."""
        if self._health_check_task is None:
            try:
                self._health_check_task = asyncio.create_task(self._health_check_loop())
            except RuntimeError:
                self._health_check_task = None
                logger.warning("Could not start health check task: no running event loop.")

    async def _health_check_loop(self) -> None:
        """Periodically check the health of failed targets."""
        if self._lock is None:
            return
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                async with self._lock:
                    failed_targets_copy = self._failed_targets.copy()

                for target_key in failed_targets_copy:
                    try:
                        host, port_str = target_key.split(":", 1)
                        port = int(port_str)
                        if await test_tcp_connection(host=host, port=port, timeout=self._health_check_timeout):
                            logger.info(f"Target {target_key} is back online")
                            async with self._lock:
                                self._failed_targets.discard(target_key)
                                self._target_latencies[target_key] = 0.0
                    except Exception:
                        pass
            except asyncio.CancelledError:
                logger.info("Health check loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Health check loop critical error: {e}", exc_info=e)

    def __len__(self) -> int:
        """Return the total number of configured targets."""
        return len(self._targets)
