"""Unit tests for the pywebtransport.client.proxy module."""

import asyncio
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    ClientError,
    ConnectionError,
    SessionError,
    TimeoutError,
    WebTransportClient,
    WebTransportSession,
    WebTransportStream,
)
from pywebtransport.client import WebTransportProxy


class TestWebTransportProxy:
    PROXY_URL = "https://proxy.example.com"
    TARGET_URL = "https://target.example.com"

    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        return mocker.MagicMock(spec=ClientConfig)

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.__aenter__.return_value = client
        return client

    @pytest.fixture
    def mock_proxy_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_ready = True
        return session

    @pytest.fixture
    def mock_tunnel_stream(self, mocker: MockerFixture) -> Any:
        stream = mocker.create_autospec(WebTransportStream, instance=True)
        stream.is_closed = False
        return stream

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mocker.patch(
            "pywebtransport.client.proxy.WebTransportClient.create",
            return_value=mock_underlying_client,
        )
        mocker.patch("asyncio.Lock", return_value=mocker.AsyncMock())

    def test_create_factory(self, mocker: MockerFixture, mock_client_config: Any) -> None:
        mock_init = mocker.patch("pywebtransport.client.proxy.WebTransportProxy.__init__", return_value=None)

        WebTransportProxy.create(proxy_url=self.PROXY_URL, config=mock_client_config)

        mock_init.assert_called_once_with(proxy_url=self.PROXY_URL, config=mock_client_config)

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mock_underlying_client: Any) -> None:
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)

        async with proxy as returned_proxy:
            assert returned_proxy is proxy
            mock_underlying_client.__aenter__.assert_awaited_once()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_through_proxy_success(
        self,
        mock_underlying_client: Any,
        mock_proxy_session: Any,
        mock_tunnel_stream: Any,
    ) -> None:
        mock_underlying_client.connect.return_value = mock_proxy_session
        mock_proxy_session.create_bidirectional_stream.return_value = mock_tunnel_stream
        mock_tunnel_stream.read.return_value = b"HTTP/1.1 200 OK\r\n\r\n"
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)

        tunnel = await proxy.connect_through_proxy(self.TARGET_URL)

        assert tunnel is mock_tunnel_stream
        mock_underlying_client.connect.assert_awaited_once_with(self.PROXY_URL, headers=None, timeout=10.0)
        mock_proxy_session.create_bidirectional_stream.assert_awaited_once()
        mock_tunnel_stream.write.assert_awaited_once()
        mock_tunnel_stream.read.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_reuses_proxy_session(
        self,
        mock_underlying_client: Any,
        mock_proxy_session: Any,
        mock_tunnel_stream: Any,
    ) -> None:
        mock_proxy_session.create_bidirectional_stream.return_value = mock_tunnel_stream
        mock_tunnel_stream.read.return_value = b"HTTP/1.1 200 OK\r\n\r\n"
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)
        proxy._proxy_session = mock_proxy_session

        await proxy.connect_through_proxy(self.TARGET_URL)

        mock_underlying_client.connect.assert_not_awaited()
        mock_proxy_session.create_bidirectional_stream.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_proxy_connection_fails(self, mock_underlying_client: Any) -> None:
        mock_underlying_client.connect.side_effect = TimeoutError("Proxy timeout")
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)

        with pytest.raises(ConnectionError, match="Failed to establish proxy session"):
            await proxy.connect_through_proxy(self.TARGET_URL)

    @pytest.mark.asyncio
    async def test_connect_proxy_returns_bad_response(
        self,
        mock_underlying_client: Any,
        mock_proxy_session: Any,
        mock_tunnel_stream: Any,
    ) -> None:
        mock_underlying_client.connect.return_value = mock_proxy_session
        mock_proxy_session.create_bidirectional_stream.return_value = mock_tunnel_stream
        mock_tunnel_stream.read.return_value = b"HTTP/1.1 500 Internal Server Error\r\n\r\n"
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)

        with pytest.raises(ClientError, match="Proxy error"):
            await proxy.connect_through_proxy(self.TARGET_URL)

        mock_tunnel_stream.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_tunnel_timeout(
        self,
        mock_underlying_client: Any,
        mock_proxy_session: Any,
        mock_tunnel_stream: Any,
    ) -> None:
        mock_underlying_client.connect.return_value = mock_proxy_session
        mock_proxy_session.create_bidirectional_stream.return_value = mock_tunnel_stream
        mock_tunnel_stream.read.side_effect = asyncio.TimeoutError
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)

        with pytest.raises(TimeoutError, match="Timeout while establishing tunnel"):
            await proxy.connect_through_proxy(self.TARGET_URL)

        mock_tunnel_stream.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_raises_session_error_if_proxy_fails_silently(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "pywebtransport.client.proxy.WebTransportProxy._ensure_proxy_session",
            new_callable=mocker.AsyncMock,
        )
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)
        proxy._proxy_session = None

        with pytest.raises(SessionError):
            await proxy.connect_through_proxy(self.TARGET_URL)

    @pytest.mark.asyncio
    async def test_connect_failure_with_already_closed_stream(
        self,
        mock_underlying_client: Any,
        mock_proxy_session: Any,
        mock_tunnel_stream: Any,
    ) -> None:
        mock_underlying_client.connect.return_value = mock_proxy_session
        mock_proxy_session.create_bidirectional_stream.return_value = mock_tunnel_stream
        mock_tunnel_stream.write.side_effect = ValueError("Write failed")
        mock_tunnel_stream.is_closed = True
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)

        with pytest.raises(ValueError, match="Write failed"):
            await proxy.connect_through_proxy(self.TARGET_URL)

        mock_tunnel_stream.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ensure_proxy_session_is_locked(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        proxy = WebTransportProxy(proxy_url=self.PROXY_URL)
        mock_proxy_session = mocker.MagicMock(spec=WebTransportSession, is_ready=True)
        first_call_done = asyncio.Event()

        async def first_call() -> None:
            await proxy._ensure_proxy_session(headers=None, timeout=10.0)
            first_call_done.set()

        async def second_call() -> None:
            await first_call_done.wait()
            await proxy._ensure_proxy_session(headers=None, timeout=10.0)

        mock_underlying_client.connect.return_value = mock_proxy_session
        await asyncio.gather(first_call(), second_call())

        mock_underlying_client.connect.assert_awaited_once()
