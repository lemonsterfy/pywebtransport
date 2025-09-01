"""
WebTransport Client Pool.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Self, Type

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.exceptions import ClientError
from pywebtransport.session import WebTransportSession
from pywebtransport.utils import get_logger

__all__ = ["ClientPool"]

logger = get_logger("client.pool")


class ClientPool:
    """Manages a pool of WebTransportClient instances."""

    def __init__(self, configs: list[ClientConfig | None]):
        """Initialize the client pool."""
        if not configs:
            raise ValueError("ClientPool requires at least one client configuration.")

        self._configs = configs
        self._clients: list[WebTransportClient] = []
        self._current_index = 0
        self._lock: asyncio.Lock | None = None

    @classmethod
    def create(cls, *, num_clients: int = 10, base_config: ClientConfig | None = None) -> Self:
        """Create a client pool with a specified number of clients."""
        configs = [base_config for _ in range(num_clients)]
        return cls(configs=configs)

    async def __aenter__(self) -> Self:
        """Enter the async context and activate all clients in the pool."""
        if self._clients:
            return self

        self._lock = asyncio.Lock()
        created_clients = [WebTransportClient.create(config=config) for config in self._configs]

        try:
            async with asyncio.TaskGroup() as tg:
                for client in created_clients:
                    tg.create_task(client.__aenter__())
            self._clients = created_clients
        except* Exception as eg:
            logger.error(f"Failed to activate clients in pool: {eg.exceptions}", exc_info=eg)
            try:
                async with asyncio.TaskGroup() as cleanup_tg:
                    for client in created_clients:
                        cleanup_tg.create_task(client.close())
            except* Exception as cleanup_eg:
                logger.error(f"Errors during client pool startup cleanup: {cleanup_eg.exceptions}")
            raise eg

        logger.info(f"Client pool started with {len(self._clients)} clients.")
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and close all clients in the pool."""
        await self.close_all()

    async def close_all(self) -> None:
        """Close all clients in the pool concurrently."""
        if self._lock is None:
            raise ClientError(
                "ClientPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        if not self._clients:
            return

        logger.info(f"Closing all {len(self._clients)} clients in the pool.")
        try:
            async with asyncio.TaskGroup() as tg:
                for client in self._clients:
                    tg.create_task(client.close())
        except* Exception as eg:
            logger.error(f"Errors occurred while closing client pool: {eg.exceptions}")

        self._clients.clear()
        logger.info("Client pool closed.")

    async def connect_all(self, url: str) -> list[WebTransportSession]:
        """Connect all clients in the pool to a URL concurrently."""
        if self._lock is None:
            raise ClientError(
                "ClientPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        if not self._clients:
            return []

        tasks: list[asyncio.Task[WebTransportSession]] = []
        try:
            async with asyncio.TaskGroup() as tg:
                for client in self._clients:
                    tasks.append(tg.create_task(client.connect(url)))
        except* Exception as eg:
            logger.warning(f"Some clients in the pool failed to connect: {eg.exceptions}")

        sessions = []
        for i, task in enumerate(tasks):
            if task.done() and not task.exception():
                sessions.append(task.result())
            else:
                logger.warning(f"Client {i} in the pool failed to connect: {task.exception()}")
        return sessions

    async def get_client(self) -> WebTransportClient:
        """Get an active client from the pool using a round-robin strategy."""
        if self._lock is None:
            raise ClientError(
                "ClientPool has not been activated. It must be used as an "
                "asynchronous context manager (`async with ...`)."
            )
        if not self._clients:
            raise ClientError("No clients available. The pool might not have been started or is empty.")

        async with self._lock:
            client = self._clients[self._current_index]
            self._current_index = (self._current_index + 1) % len(self._clients)
            return client

    def get_client_count(self) -> int:
        """Get the number of clients currently in the pool."""
        return len(self._clients)
