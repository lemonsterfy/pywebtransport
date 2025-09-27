"""WebTransport connection utility functions."""

from __future__ import annotations

import asyncio

from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.exceptions import ConnectionError, HandshakeError
from pywebtransport.utils import get_logger

__all__ = [
    "connect_with_retry",
    "create_multiple_connections",
    "ensure_connection",
    "test_multiple_connections",
    "test_tcp_connection",
]

logger = get_logger(name="connection.utils")


async def connect_with_retry(
    *,
    config: ClientConfig,
    host: str,
    port: int,
    path: str = "/",
    max_retries: int = 3,
    retry_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> WebTransportConnection:
    """Establish a connection with an exponential backoff retry mechanism."""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
            if attempt > 0:
                logger.info("Connected to %s:%s after %d retries", host, port, attempt)
            return connection
        except (ConnectionError, HandshakeError) as e:
            last_error = e
            if attempt < max_retries:
                delay = retry_delay * (backoff_factor**attempt)
                logger.warning(
                    "Connection attempt %d failed, retrying in %.1fs: %s",
                    attempt + 1,
                    delay,
                    e,
                    exc_info=True,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("All %d connection attempts failed", max_retries + 1)
    raise ConnectionError(message=f"Failed to connect after {max_retries + 1} attempts: {last_error}")


async def create_multiple_connections(
    *,
    config: ClientConfig,
    targets: list[tuple[str, int]],
    path: str = "/",
    max_concurrent: int = 10,
) -> dict[str, WebTransportConnection]:
    """Create multiple connections to a list of targets with a concurrency limit."""
    semaphore = asyncio.Semaphore(value=max_concurrent)
    connections: dict[str, WebTransportConnection] = {}

    async def create_single_connection(*, host: str, port: int) -> None:
        target_key = f"{host}:{port}"
        async with semaphore:
            try:
                connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
                connections[target_key] = connection
            except Exception as e:
                logger.error("Failed to connect to %s:%s: %s", host, port, e, exc_info=True)

    try:
        async with asyncio.TaskGroup() as tg:
            for host, port in targets:
                tg.create_task(create_single_connection(host=host, port=port))
    except* Exception as eg:
        logger.error("Errors occurred while creating multiple connections: %s", eg.exceptions, exc_info=eg)

    return connections


async def ensure_connection(
    *,
    connection: WebTransportConnection,
    config: ClientConfig,
    host: str,
    port: int,
    path: str = "/",
    reconnect: bool = True,
) -> WebTransportConnection:
    """Ensure a connection is active, optionally reconnecting if it is not."""
    if connection.is_connected:
        return connection
    if not reconnect:
        raise ConnectionError(message="Connection not active and reconnect disabled")

    logger.info("Reconnecting to %s:%s", host, port)
    await connection.close()
    new_connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
    return new_connection


async def test_multiple_connections(*, targets: list[tuple[str, int]], timeout: float = 10.0) -> dict[str, bool]:
    """Test TCP connectivity to multiple targets concurrently."""
    connection_results: dict[str, bool] = {}
    tasks: dict[str, asyncio.Task[bool]] = {}

    try:
        async with asyncio.TaskGroup() as tg:
            for host, port in targets:
                target_key = f"{host}:{port}"
                tasks[target_key] = tg.create_task(test_tcp_connection(host=host, port=port, timeout=timeout))
    except* Exception:
        pass

    for target_key, task in tasks.items():
        if task.done() and not task.cancelled():
            try:
                connection_results[target_key] = task.result()
            except Exception:
                connection_results[target_key] = False
        else:
            connection_results[target_key] = False

    return connection_results


async def test_tcp_connection(*, host: str, port: int, timeout: float = 10.0) -> bool:
    """Test if a TCP connection can be established to a host and port."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host=host, port=port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False
