"""
WebTransport connection utility functions.
"""

import asyncio
from typing import Dict, List, Optional, Tuple

from pywebtransport.config import ClientConfig
from pywebtransport.connection.connection import WebTransportConnection
from pywebtransport.exceptions import ConnectionError, HandshakeError
from pywebtransport.utils import get_logger

__all__ = [
    "connect_with_retry",
    "ensure_connection",
    "create_multiple_connections",
    "test_multiple_connections",
    "test_tcp_connection",
]

logger = get_logger("connection.utils")


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
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
            if attempt > 0:
                logger.info(f"Connected to {host}:{port} after {attempt} retries")
            return connection
        except (ConnectionError, HandshakeError) as e:
            last_error = e
            if attempt < max_retries:
                delay = retry_delay * (backoff_factor**attempt)
                logger.warning(f"Connection attempt {attempt + 1} failed, retrying in {delay:.1f}s: {e}")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries + 1} connection attempts failed")
    raise ConnectionError(f"Failed to connect after {max_retries + 1} attempts: {last_error}")


async def ensure_connection(
    connection: WebTransportConnection,
    config: ClientConfig,
    *,
    host: str,
    port: int,
    path: str = "/",
    reconnect: bool = True,
) -> WebTransportConnection:
    """Ensure a connection is active, optionally reconnecting if it is not."""
    if connection.is_connected:
        return connection
    if not reconnect:
        raise ConnectionError("Connection not active and reconnect disabled")

    logger.info(f"Reconnecting to {host}:{port}")
    await connection.close()
    new_connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
    return new_connection


async def create_multiple_connections(
    *,
    config: ClientConfig,
    targets: List[Tuple[str, int]],
    path: str = "/",
    max_concurrent: int = 10,
) -> Dict[str, WebTransportConnection]:
    """Create multiple connections to a list of targets with a concurrency limit."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def create_single_connection(host: str, port: int) -> Tuple[str, Optional[WebTransportConnection]]:
        async with semaphore:
            try:
                connection = await WebTransportConnection.create_client(config=config, host=host, port=port, path=path)
                return f"{host}:{port}", connection
            except Exception as e:
                logger.error(f"Failed to connect to {host}:{port}: {e}")
                return f"{host}:{port}", None

    tasks = [create_single_connection(host, port) for host, port in targets]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    connections = {}
    for result in results:
        if isinstance(result, tuple) and len(result) == 2:
            target_key, connection = result
            if connection:
                connections[target_key] = connection
    return connections


async def test_multiple_connections(*, targets: List[Tuple[str, int]], timeout: float = 10.0) -> Dict[str, bool]:
    """Test TCP connectivity to multiple targets concurrently."""
    tasks = []
    target_keys = []
    for host, port in targets:
        target_key = f"{host}:{port}"
        target_keys.append(target_key)
        tasks.append(test_tcp_connection(host=host, port=port, timeout=timeout))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    connection_results: Dict[str, bool] = {}
    for target_key, result in zip(target_keys, results):
        connection_results[target_key] = isinstance(result, bool) and result
    return connection_results


async def test_tcp_connection(*, host: str, port: int, timeout: float = 10.0) -> bool:
    """Test if a TCP connection can be established to a host and port."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False
