"""Load balancer for WebTransport connections."""

from __future__ import annotations

import asyncio
import random
import time
from types import TracebackType
from typing import Any, Self

from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.connection.utils import test_tcp_connection
from pywebtransport.exceptions import ConnectionError
from pywebtransport.utils import get_logger

__all__ = ["ConnectionLoadBalancer"]

logger = get_logger(name="connection.load_balancer")


class ConnectionLoadBalancer:
    """Distributes WebTransport connections across multiple targets."""

    def __init__(
        self,
        targets: list[tuple[str, int]],
        *,
        health_check_interval: float = 30.0,
        health_check_timeout: float = 5.0,
    ) -> None:
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
        self._target_weights: dict[str, float] = {self._get_target_key(host=h, port=p): 1.0 for h, p in self._targets}
        self._target_latencies: dict[str, float] = {self._get_target_key(host=h, port=p): 0.0 for h, p in self._targets}
        self._health_check_task: asyncio.Task[None] | None = None
        self._pending_creations: dict[str, asyncio.Event] = {}

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
        exc_type: type[BaseException] | None,
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

    async def close_all_connections(self) -> None:
        """Close all currently managed connections."""
        if self._lock is None:
            raise ConnectionError(
                message=(
                    "ConnectionLoadBalancer has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        connections_to_close: list[WebTransportConnection] = []
        async with self._lock:
            connections_to_close = list(self._connections.values())
            self._connections.clear()

        if not connections_to_close:
            return

        logger.info("Closing %d connections", len(connections_to_close))
        try:
            async with asyncio.TaskGroup() as tg:
                for connection in connections_to_close:
                    tg.create_task(connection.close())
        except* Exception as eg:
            logger.error("Errors occurred while closing connections: %s", eg.exceptions, exc_info=eg)
        logger.info("All connections closed")

    async def get_connection(
        self,
        *,
        config: ClientConfig,
        path: str = "/",
        strategy: str = "round_robin",
    ) -> WebTransportConnection:
        """Get a connection using the specified load balancing strategy."""
        if self._lock is None:
            raise ConnectionError(
                message=(
                    "ConnectionLoadBalancer has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        host, port = await self._get_next_target(strategy=strategy)
        target_key = self._get_target_key(host=host, port=port)

        while True:
            async with self._lock:
                if target_key in self._connections:
                    connection = self._connections[target_key]
                    if connection.is_connected:
                        logger.debug("Reusing connection to %s:%s", host, port)
                        return connection
                    else:
                        del self._connections[target_key]

                if event := self._pending_creations.get(target_key):
                    is_creator = False
                else:
                    is_creator = True
                    event = asyncio.Event()
                    self._pending_creations[target_key] = event

            if not is_creator:
                await event.wait()
                continue

            try:
                logger.debug("Creating new connection to %s:%s", host, port)
                start_time = time.time()
                connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
                latency = time.time() - start_time

                async with self._lock:
                    self._target_latencies[target_key] = latency
                    self._failed_targets.discard(target_key)
                    self._connections[target_key] = connection

                logger.info("Connected to %s:%s (latency: %.1fms)", host, port, latency * 1000)
                return connection
            except Exception as e:
                async with self._lock:
                    self._failed_targets.add(target_key)
                logger.error("Failed to connect to %s:%s: %s", host, port, e, exc_info=True)
                raise
            finally:
                async with self._lock:
                    self._pending_creations.pop(target_key, None)
                    event.set()

    async def get_load_balancer_stats(self) -> dict[str, Any]:
        """Get high-level statistics about the load balancer."""
        if self._lock is None:
            raise ConnectionError(
                message=(
                    "ConnectionLoadBalancer has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            return {
                "total_targets": len(self._targets),
                "failed_targets": len(self._failed_targets),
                "active_connections": len(self._connections),
                "available_targets": len(self._targets) - len(self._failed_targets),
            }

    async def get_target_stats(self) -> dict[str, Any]:
        """Get health and performance statistics for all targets."""
        if self._lock is None:
            raise ConnectionError(
                message=(
                    "ConnectionLoadBalancer has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            stats = {}
            for host, port in self._targets:
                target_key = self._get_target_key(host=host, port=port)
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

    async def update_target_weight(self, *, host: str, port: int, weight: float) -> None:
        """Update the weight for a specific target."""
        if self._lock is None:
            raise ConnectionError(
                message=(
                    "ConnectionLoadBalancer has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        target_key = self._get_target_key(host=host, port=port)
        async with self._lock:
            if target_key in self._target_weights:
                self._target_weights[target_key] = max(0.0, weight)
                logger.debug("Updated weight for %s: %s", target_key, weight)

    async def _get_next_target(self, *, strategy: str) -> tuple[str, int]:
        """Get the next target based on the chosen load balancing strategy."""
        if self._lock is None:
            raise ConnectionError(
                message=(
                    "ConnectionLoadBalancer has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            available_targets = [
                target
                for target in self._targets
                if self._get_target_key(host=target[0], port=target[1]) not in self._failed_targets
            ]
            if not available_targets:
                raise ConnectionError(message="No available targets in the load balancer.")

            match strategy:
                case "round_robin":
                    self._current_index = (self._current_index + 1) % len(available_targets)
                    return available_targets[self._current_index]
                case "weighted":
                    weights = [
                        self._target_weights[self._get_target_key(host=t[0], port=t[1])] for t in available_targets
                    ]
                    total_weight = sum(weights)
                    if total_weight == 0:
                        return random.choice(available_targets)
                    return random.choices(population=available_targets, weights=weights, k=1)[0]
                case "least_latency":
                    latency_targets = [
                        (self._target_latencies[self._get_target_key(host=t[0], port=t[1])], t)
                        for t in available_targets
                    ]
                    return min(latency_targets, key=lambda item: item[0])[1]
                case _:
                    raise ValueError(f"Unknown load balancing strategy: {strategy}")

    def _get_target_key(self, *, host: str, port: int) -> str:
        """Generate a unique key for a given host and port."""
        return f"{host}:{port}"

    async def _health_check_loop(self) -> None:
        """Periodically check the health of failed targets."""
        lock = self._lock
        if lock is None:
            return

        failed_targets_copy: list[str] = []
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                async with lock:
                    failed_targets_copy = list(self._failed_targets)

                if not failed_targets_copy:
                    continue

                async def check_target(*, target_key: str) -> None:
                    try:
                        host, port_str = target_key.split(":", 1)
                        port = int(port_str)
                        if await test_tcp_connection(
                            host=host,
                            port=port,
                            timeout=self._health_check_timeout,
                        ):
                            logger.info("Target %s is back online", target_key)
                            async with lock:
                                self._failed_targets.discard(target_key)
                                self._target_latencies[target_key] = 0.0
                    except Exception as e:
                        logger.debug("Health check for %s failed: %s", target_key, e)

                try:
                    async with asyncio.TaskGroup() as tg:
                        for target_key in failed_targets_copy:
                            tg.create_task(check_target(target_key=target_key))
                except* Exception:
                    pass

            except asyncio.CancelledError:
                logger.info("Health check loop cancelled.")
                break
            except Exception as e:
                logger.error("Health check loop critical error: %s", e, exc_info=e)

    def _start_health_check_task(self) -> None:
        """Start the periodic health check task if not already running."""
        if self._health_check_task is None or self._health_check_task.done():
            try:
                self._health_check_task = asyncio.create_task(self._health_check_loop())
            except RuntimeError:
                self._health_check_task = None
                logger.warning("Could not start health check task: no running event loop.")

    def __len__(self) -> int:
        """Return the total number of configured targets."""
        return len(self._targets)
