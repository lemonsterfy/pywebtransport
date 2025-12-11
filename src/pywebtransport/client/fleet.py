"""High-level client for managing a fleet of client instances."""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Self

from pywebtransport.client.client import WebTransportClient
from pywebtransport.exceptions import ClientError
from pywebtransport.session import WebTransportSession
from pywebtransport.utils import get_logger

__all__: list[str] = ["ClientFleet"]

logger = get_logger(name=__name__)


class ClientFleet:
    """Manages a fleet of WebTransportClient instances to distribute load."""

    def __init__(self, *, clients: list[WebTransportClient]) -> None:
        """Initialize the client fleet."""
        if not clients:
            raise ValueError("ClientFleet requires at least one client instance.")

        self._clients = clients
        self._current_index = 0
        self._active = False

    async def __aenter__(self) -> Self:
        """Enter the async context and activate all clients in the fleet."""
        self._active = True

        try:
            async with asyncio.TaskGroup() as tg:
                for client in self._clients:
                    tg.create_task(coro=client.__aenter__())
        except* Exception as eg:
            logger.error("Failed to activate clients in fleet: %s", eg.exceptions, exc_info=eg)
            self._active = False
            try:
                async with asyncio.TaskGroup() as cleanup_tg:
                    for client in self._clients:
                        cleanup_tg.create_task(coro=client.close())
            except* Exception as cleanup_eg:
                logger.error(
                    "Errors during client fleet startup cleanup: %s", cleanup_eg.exceptions, exc_info=cleanup_eg
                )
            raise eg

        logger.info("Client fleet started with %d clients.", len(self._clients))
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        """Exit the async context and close all clients in the fleet."""
        await self.close_all()

    async def close_all(self) -> None:
        """Close all clients in the fleet concurrently."""
        if not self._active:
            return

        logger.info("Closing all %d clients in the fleet.", len(self._clients))
        try:
            async with asyncio.TaskGroup() as tg:
                for client in self._clients:
                    tg.create_task(coro=client.close())
        except* Exception as eg:
            logger.error("Errors occurred while closing client fleet: %s", eg.exceptions, exc_info=eg)

        self._active = False
        logger.info("Client fleet closed.")

    async def connect_all(self, *, url: str) -> list[WebTransportSession]:
        """Connect all clients in the fleet to a URL concurrently."""
        self._check_active()

        async def safe_connect(client: WebTransportClient) -> WebTransportSession | None:
            try:
                return await client.connect(url=url)
            except Exception as e:
                logger.warning("Client failed to connect: %s", e)
                return None

        tasks: list[asyncio.Task[WebTransportSession | None]] = []
        async with asyncio.TaskGroup() as tg:
            for client in self._clients:
                tasks.append(tg.create_task(coro=safe_connect(client)))

        sessions: list[WebTransportSession] = []
        for task in tasks:
            result = task.result()
            if result is not None:
                sessions.append(result)

        return sessions

    def get_client(self) -> WebTransportClient:
        """Get an active client from the fleet using a round-robin strategy."""
        self._check_active()

        client = self._clients[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._clients)
        return client

    def get_client_count(self) -> int:
        """Get the number of clients currently in the fleet."""
        return len(self._clients)

    def _check_active(self) -> None:
        """Check if the fleet is active."""
        if not self._active:
            raise ClientError(
                message=(
                    "ClientFleet has not been activated. It must be used as an "
                    "asynchronous context manager (`async with ...`)."
                )
            )
