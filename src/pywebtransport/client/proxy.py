"""
WebTransport Proxy Client.
"""

import asyncio
from types import TracebackType
from typing import Optional, Type

from pywebtransport.client.client import WebTransportClient
from pywebtransport.config import ClientConfig
from pywebtransport.exceptions import ClientError, ConnectionError, SessionError, TimeoutError
from pywebtransport.session import WebTransportSession
from pywebtransport.stream import WebTransportStream
from pywebtransport.types import URL, Headers
from pywebtransport.utils import get_logger

__all__ = ["WebTransportProxy"]

logger = get_logger("client.proxy")


class WebTransportProxy:
    """Tunnels WebTransport connections through an HTTP CONNECT proxy."""

    def __init__(self, *, proxy_url: URL, config: Optional[ClientConfig] = None):
        """Initialize the WebTransport proxy client."""
        self._proxy_url = proxy_url
        self._client = WebTransportClient.create(config=config)
        self._proxy_session: Optional[WebTransportSession] = None
        self._proxy_connect_lock = asyncio.Lock()

    @classmethod
    def create(cls, *, proxy_url: URL, config: Optional[ClientConfig] = None) -> "WebTransportProxy":
        """Factory method to create a new proxy client instance."""
        return cls(proxy_url=proxy_url, config=config)

    async def __aenter__(self) -> "WebTransportProxy":
        """Enter the async context for the proxy client."""
        await self._client.__aenter__()
        logger.info("WebTransportProxy started and is active.")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the async context and close the proxy client."""
        await self.close()
        logger.info("WebTransportProxy has been closed.")

    async def connect_through_proxy(
        self,
        target_url: URL,
        *,
        proxy_headers: Optional[Headers] = None,
        timeout: float = 10.0,
    ) -> WebTransportStream:
        """Establish a tunnel to a target URL through the proxy."""
        await self._ensure_proxy_session(headers=proxy_headers, timeout=timeout)

        if self._proxy_session is None:
            raise SessionError("Proxy session is not available after connection attempt.")

        logger.info(f"Creating tunnel to {target_url} via proxy at {self._proxy_url}")
        tunnel_stream = await self._proxy_session.create_bidirectional_stream()

        try:
            connect_request = f"CONNECT {target_url} HTTP/1.1\r\nHost: {target_url.split('//')[1]}\r\n\r\n".encode()
            await tunnel_stream.write(connect_request)

            response_bytes = await asyncio.wait_for(tunnel_stream.read(size=4096), timeout=timeout)
            response_str = response_bytes.decode(errors="ignore")

            if "200 OK" not in response_str and "200 Connection established" not in response_str:
                raise ClientError(f"Proxy error for target {target_url}: {response_str}", target_url=target_url)

            logger.info(f"Tunnel to {target_url} established successfully.")
            return tunnel_stream
        except Exception as e:
            logger.error(f"Failed to establish tunnel to {target_url}: {e}")
            if not tunnel_stream.is_closed:
                await tunnel_stream.close()

            if isinstance(e, asyncio.TimeoutError):
                raise TimeoutError("Timeout while establishing tunnel via proxy.") from e
            raise

    async def close(self) -> None:
        """Close the proxy client and the main session to the proxy server."""
        logger.info("Closing proxy connection.")
        await self._client.close()
        self._proxy_session = None

    async def _ensure_proxy_session(self, headers: Optional[Headers], timeout: float) -> None:
        """Ensure the connection to the proxy server is established, using a lock."""
        if self._proxy_session and self._proxy_session.is_ready:
            return

        async with self._proxy_connect_lock:
            if self._proxy_session and self._proxy_session.is_ready:
                return

            logger.info(f"Establishing connection to proxy server at {self._proxy_url}")
            try:
                self._proxy_session = await self._client.connect(self._proxy_url, headers=headers, timeout=timeout)
            except Exception as e:
                logger.error(f"Failed to connect to the proxy server: {e}", exc_info=True)
                raise ConnectionError("Failed to establish proxy session") from e
