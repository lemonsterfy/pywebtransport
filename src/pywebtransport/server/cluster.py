"""Utility for managing a cluster of server instances."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, Self

from pywebtransport.config import ServerConfig
from pywebtransport.exceptions import ServerError
from pywebtransport.server.server import WebTransportServer
from pywebtransport.types import ConnectionState, SessionState
from pywebtransport.utils import get_logger

__all__: list[str] = ["ServerCluster"]

logger = get_logger(name=__name__)


class ServerCluster:
    """Manages the lifecycle of multiple WebTransport server instances."""

    def __init__(self, *, configs: list[ServerConfig]) -> None:
        """Initialize the server cluster."""
        self._configs = configs
        self._servers: list[WebTransportServer] = []
        self._running = False
        self._lock: asyncio.Lock | None = None

    @property
    def is_running(self) -> bool:
        """Check if the cluster is currently running."""
        return self._running

    async def __aenter__(self) -> Self:
        """Enter the async context and start all servers."""
        self._lock = asyncio.Lock()
        await self.start_all()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context and stop all servers."""
        await self.stop_all()

    async def start_all(self) -> None:
        """Start all servers in the cluster concurrently."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "ServerCluster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        async with self._lock:
            if self._running:
                return
            initial_configs = self._configs

        started_servers: list[WebTransportServer] = []
        tasks: list[asyncio.Task[WebTransportServer]] = []
        try:
            async with asyncio.TaskGroup() as tg:
                for config in initial_configs:
                    tasks.append(tg.create_task(coro=self._create_and_start_server(config=config)))
            started_servers = [task.result() for task in tasks]
        except* Exception as eg:
            logger.error("Failed to start server cluster: %s", eg.exceptions, exc_info=True)
            successful_servers = [task.result() for task in tasks if task.done() and not task.exception()]
            if successful_servers:
                logger.info("Cleaning up %d successfully started servers...", len(successful_servers))
                try:
                    async with asyncio.TaskGroup() as cleanup_tg:
                        for server in successful_servers:
                            cleanup_tg.create_task(coro=server.close())
                except* Exception as cleanup_eg:
                    logger.error("Errors during cluster startup cleanup: %s", cleanup_eg.exceptions, exc_info=True)
            raise eg.exceptions[0]

        async with self._lock:
            self._servers = started_servers
            self._running = True
            logger.info("Started cluster with %d servers", len(self._servers))

    async def stop_all(self) -> None:
        """Stop all servers in the cluster concurrently."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "ServerCluster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        servers_to_stop: list[WebTransportServer] = []
        async with self._lock:
            if not self._running:
                return
            servers_to_stop = self._servers
            self._servers = []
            self._running = False

        if servers_to_stop:
            try:
                async with asyncio.TaskGroup() as tg:
                    for server in servers_to_stop:
                        tg.create_task(coro=server.close())
            except* Exception as eg:
                logger.error("Errors occurred while stopping server cluster: %s", eg.exceptions, exc_info=True)
                raise eg
            logger.info("Stopped server cluster")

    async def add_server(self, *, config: ServerConfig) -> WebTransportServer | None:
        """Add and start a new server in the running cluster."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "ServerCluster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        is_running: bool
        async with self._lock:
            is_running = self._running
            if not is_running:
                self._configs.append(config)
                logger.info("Cluster not running. Server config added for next start.")
                return None

        try:
            server = await self._create_and_start_server(config=config)
            async with self._lock:
                if not self._running:
                    await server.close()
                    logger.warning("Cluster was stopped while new server was starting. New server has been shut down.")
                    return None
                self._servers.append(server)
                logger.info("Added server to cluster: %s", server.local_address)
            return server
        except Exception as e:
            logger.error("Failed to add server to cluster: %s", e, exc_info=True)
            return None

    async def remove_server(self, *, host: str, port: int) -> bool:
        """Remove and stop a specific server from the cluster by its address."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "ServerCluster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        server_to_remove: WebTransportServer | None = None
        async with self._lock:
            for server in self._servers:
                if server.local_address == (host, port):
                    server_to_remove = server
                    break

            if server_to_remove:
                self._servers.remove(server_to_remove)
            else:
                logger.warning("Server at %s:%s not found in cluster.", host, port)
                return False

        await server_to_remove.close()
        logger.info("Removed server from cluster: %s:%s", host, port)
        return True

    async def get_cluster_stats(self) -> dict[str, Any]:
        """Get deeply aggregated statistics for the entire cluster."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "ServerCluster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )

        servers_snapshot: list[WebTransportServer]
        async with self._lock:
            if not self._servers:
                return {}
            servers_snapshot = self._servers.copy()

        tasks = []
        try:
            async with asyncio.TaskGroup() as tg:
                for s in servers_snapshot:
                    tasks.append(tg.create_task(coro=s.diagnostics()))
        except* Exception as eg:
            logger.error("Failed to fetch stats from some servers: %s", eg.exceptions, exc_info=True)
            raise eg

        diagnostics_list = [task.result() for task in tasks if task.done() and not task.exception()]

        agg_stats: dict[str, Any] = {
            "server_count": len(servers_snapshot),
            "total_connections_accepted": 0,
            "total_connections_rejected": 0,
            "total_connections_active": 0,
            "total_sessions_active": 0,
        }
        for diag in diagnostics_list:
            agg_stats["total_connections_accepted"] += diag.stats.connections_accepted
            agg_stats["total_connections_rejected"] += diag.stats.connections_rejected
            agg_stats["total_connections_active"] += diag.connection_states.get(ConnectionState.CONNECTED, 0)
            agg_stats["total_sessions_active"] += diag.session_states.get(SessionState.CONNECTED, 0)

        return agg_stats

    async def get_server_count(self) -> int:
        """Get the number of running servers in the cluster."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "ServerCluster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            return len(self._servers)

    async def get_servers(self) -> list[WebTransportServer]:
        """Get a thread-safe copy of all active servers in the cluster."""
        if self._lock is None:
            raise ServerError(
                message=(
                    "ServerCluster has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
        async with self._lock:
            return self._servers.copy()

    async def _create_and_start_server(self, *, config: ServerConfig) -> WebTransportServer:
        """Create, activate, and start a single server instance."""
        server = WebTransportServer(config=config)
        await server.__aenter__()

        try:
            await server.listen()
        except Exception:
            await server.close()
            raise
        return server
