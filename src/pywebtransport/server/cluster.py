"""
WebTransport Server Cluster.
"""

import asyncio
from types import TracebackType
from typing import Any, Dict, List, Optional, Type

from pywebtransport.config import ServerConfig
from pywebtransport.server.server import WebTransportServer
from pywebtransport.utils import get_logger

__all__ = ["ServerCluster"]

logger = get_logger("server.cluster")


class ServerCluster:
    """Manages the lifecycle of multiple WebTransport server instances."""

    def __init__(self, configs: List[ServerConfig]):
        """Initialize the server cluster."""
        self._configs = configs
        self._servers: List[WebTransportServer] = []
        self._running = False
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Check if the cluster is currently running."""
        return self._running

    async def __aenter__(self) -> "ServerCluster":
        """Enter the async context and start all servers."""
        await self.start_all()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the async context and stop all servers."""
        await self.stop_all()

    async def start_all(self) -> None:
        """Start all servers in the cluster concurrently."""
        async with self._lock:
            if self._running:
                return

            startup_tasks = [self._create_and_start_server(config) for config in self._configs]
            results = await asyncio.gather(*startup_tasks, return_exceptions=True)

            created_servers: List[WebTransportServer] = []
            first_exception: Optional[BaseException] = None

            for result in results:
                if not isinstance(result, BaseException):
                    created_servers.append(result)
                elif first_exception is None:
                    first_exception = result

            if first_exception:
                logger.error(f"Failed to start server cluster: {first_exception}", exc_info=first_exception)
                if created_servers:
                    cleanup_tasks = [s.close() for s in created_servers]
                    await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                raise first_exception

            self._servers = created_servers
            self._running = True
            logger.info(f"Started cluster with {len(self._servers)} servers")

    async def stop_all(self) -> None:
        """Stop all servers in the cluster concurrently."""
        async with self._lock:
            if not self._running:
                return
            servers_to_stop = self._servers
            self._servers = []
            self._running = False

        close_tasks = [server.close() for server in servers_to_stop]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        logger.info("Stopped server cluster")

    async def add_server(self, config: ServerConfig) -> Optional[WebTransportServer]:
        """Add and start a new server in the running cluster."""
        async with self._lock:
            if not self._running:
                self._configs.append(config)
                logger.info("Cluster not running. Server config added for next start.")
                return None
            try:
                server = await self._create_and_start_server(config)
                self._servers.append(server)
                logger.info(f"Added server to cluster: {server.local_address}")
                return server
            except Exception as e:
                logger.error(f"Failed to add server to cluster: {e}", exc_info=True)
                return None

    async def remove_server(self, *, host: str, port: int) -> bool:
        """Remove and stop a specific server from the cluster by its address."""
        async with self._lock:
            server_to_remove: Optional[WebTransportServer] = None
            for server in self._servers:
                if server.local_address == (host, port):
                    server_to_remove = server
                    break

            if server_to_remove:
                self._servers.remove(server_to_remove)
            else:
                logger.warning(f"Server at {host}:{port} not found in cluster.")
                return False

        await server_to_remove.close()
        logger.info(f"Removed server from cluster: {host}:{port}")
        return True

    async def get_servers(self) -> List[WebTransportServer]:
        """Get a thread-safe copy of all active servers in the cluster."""
        async with self._lock:
            return self._servers.copy()

    async def get_cluster_stats(self) -> Dict[str, Any]:
        """Get deeply aggregated statistics for the entire cluster."""
        async with self._lock:
            if not self._servers:
                return {}
            servers_snapshot = self._servers.copy()

        stats_list = await asyncio.gather(*[s.get_server_stats() for s in servers_snapshot])
        agg_stats: Dict[str, Any] = {
            "server_count": len(servers_snapshot),
            "total_connections_accepted": 0,
            "total_connections_rejected": 0,
            "total_connections_active": 0,
            "total_sessions_active": 0,
        }
        for stats in stats_list:
            agg_stats["total_connections_accepted"] += stats.get("connections_accepted", 0)
            agg_stats["total_connections_rejected"] += stats.get("connections_rejected", 0)
            if "connections" in stats:
                agg_stats["total_connections_active"] += stats["connections"].get("active", 0)
            if "sessions" in stats:
                agg_stats["total_sessions_active"] += stats["sessions"].get("active", 0)

        return agg_stats

    async def get_server_count(self) -> int:
        """Get the number of running servers in the cluster."""
        async with self._lock:
            return len(self._servers)

    async def _create_and_start_server(self, config: ServerConfig) -> WebTransportServer:
        """Create, activate, and start a single server instance."""
        server = WebTransportServer(config=config)
        await server.__aenter__()
        await server.listen()
        return server
