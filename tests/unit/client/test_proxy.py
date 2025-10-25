"""Unit tests for the pywebtransport.client._proxy module."""

import asyncio
import ssl
from collections.abc import Coroutine
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConfigurationError
from pywebtransport.client._proxy import _ProxyHandshakeProtocol, perform_proxy_handshake
from pywebtransport.config import ProxyConfig
from pywebtransport.exceptions import HandshakeError
from pywebtransport.protocol.events import HeadersReceived


@pytest.mark.filterwarnings("ignore:There is no current event loop:DeprecationWarning")
class TestPerformProxyHandshake:
    TARGET_HOST = "example.com"
    TARGET_PORT = 443
    PROXY_URL = "https://proxy.internal:8443"

    @pytest.fixture
    def mock_config(self) -> MagicMock:
        config = MagicMock(spec=ClientConfig)
        config.proxy = MagicMock(spec=ProxyConfig)
        config.proxy.url = self.PROXY_URL
        config.proxy.headers = {"x-proxy-header": "value"}
        config.proxy.connect_timeout = 5.0
        config.user_agent = "test-agent/1.0"
        config.alpn_protocols = ["h3"]
        config.congestion_control_algorithm = "reno"
        config.max_datagram_size = 1200
        config.verify_mode = None
        return config

    @pytest.fixture(autouse=True)
    def mock_loop(self, mocker: MockerFixture) -> MagicMock:
        loop = MagicMock(spec=asyncio.AbstractEventLoop)
        transport_mock = MagicMock()
        transport_mock.close = MagicMock()
        loop.create_datagram_endpoint.return_value = (transport_mock, mocker.AsyncMock())
        loop.getaddrinfo = mocker.AsyncMock(return_value=[(None, None, None, None, ("127.0.0.1", 8443))])
        loop.time.return_value = 0.0
        mocker.patch("asyncio.get_running_loop", return_value=loop)
        return loop

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture) -> dict[str, MagicMock]:
        mock_quic_connection_class = mocker.patch("pywebtransport.client._proxy.QuicConnection", autospec=True)
        mock_quic_connection_class.return_value.get_next_available_stream_id.return_value = 0

        mock_h3_engine = mocker.patch("pywebtransport.client._proxy.WebTransportH3Engine", autospec=True).return_value
        mock_h3_engine.handle_event = mocker.AsyncMock(return_value=[])

        mock_protocol = mocker.patch("pywebtransport.client._proxy._ProxyHandshakeProtocol", autospec=True).return_value
        mock_protocol.get_event = mocker.AsyncMock()

        mock_create_quic_config = mocker.patch("pywebtransport.client._proxy.create_quic_configuration", autospec=True)

        return {
            "quic_class": mock_quic_connection_class,
            "h3": mock_h3_engine,
            "protocol": mock_protocol,
            "create_quic_config": mock_create_quic_config,
        }

    @pytest.mark.asyncio
    async def test_endpoint_creation_failure(self, mock_config: MagicMock, mock_loop: MagicMock) -> None:
        error = OSError("Failed to create endpoint")
        mock_loop.create_datagram_endpoint.side_effect = error

        with pytest.raises(OSError) as exc_info:
            await perform_proxy_handshake(
                config=mock_config,
                target_host=self.TARGET_HOST,
                target_port=self.TARGET_PORT,
            )
        assert exc_info.value is error

    @pytest.mark.asyncio
    async def test_event_processor_handles_empty_events(
        self, mock_config: MagicMock, setup_common_mocks: dict[str, MagicMock]
    ) -> None:
        mock_h3_engine = setup_common_mocks["h3"]
        mock_protocol = setup_common_mocks["protocol"]

        dummy_event = MagicMock()
        final_event = MagicMock()
        headers_event = HeadersReceived(stream_id=0, headers={":status": "200"}, stream_ended=False)
        mock_protocol.get_event.side_effect = [dummy_event, final_event]
        mock_h3_engine.handle_event.side_effect = [[], [headers_event]]

        await perform_proxy_handshake(
            config=mock_config,
            target_host=self.TARGET_HOST,
            target_port=self.TARGET_PORT,
        )

        assert mock_h3_engine.handle_event.call_count == 2
        mock_h3_engine.handle_event.assert_any_call(event=dummy_event)
        mock_h3_engine.handle_event.assert_any_call(event=final_event)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", ["403", "500"])
    async def test_handshake_failure_bad_status(
        self,
        setup_common_mocks: dict[str, MagicMock],
        mock_config: MagicMock,
        mock_loop: MagicMock,
        status_code: str,
    ) -> None:
        mock_h3_engine = setup_common_mocks["h3"]
        mock_protocol = setup_common_mocks["protocol"]
        headers_event = HeadersReceived(stream_id=0, headers={":status": status_code}, stream_ended=False)
        mock_h3_engine.handle_event.return_value = [headers_event]
        mock_protocol.get_event.return_value = MagicMock()

        with pytest.raises(HandshakeError, match=f"Proxy returned status {status_code}"):
            await perform_proxy_handshake(
                config=mock_config,
                target_host=self.TARGET_HOST,
                target_port=self.TARGET_PORT,
            )

    @pytest.mark.asyncio
    async def test_handshake_failure_no_status(
        self,
        setup_common_mocks: dict[str, MagicMock],
        mock_config: MagicMock,
        mock_loop: MagicMock,
    ) -> None:
        mock_h3_engine = setup_common_mocks["h3"]
        mock_protocol = setup_common_mocks["protocol"]
        headers_event = HeadersReceived(stream_id=0, headers={"other-header": "value"}, stream_ended=False)
        mock_h3_engine.handle_event.return_value = [headers_event]
        mock_protocol.get_event.return_value = MagicMock()

        with pytest.raises(HandshakeError, match="Proxy returned status No status code received"):
            await perform_proxy_handshake(
                config=mock_config,
                target_host=self.TARGET_HOST,
                target_port=self.TARGET_PORT,
            )

    @pytest.mark.asyncio
    async def test_handshake_timeout(self, mocker: MockerFixture, mock_config: MagicMock, mock_loop: MagicMock) -> None:
        mocker.patch("asyncio.wait_for", side_effect=asyncio.TimeoutError)
        created_task: asyncio.Task[None] | None = None
        original_create_task = asyncio.create_task

        def capture_task(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
            nonlocal created_task
            task = original_create_task(coro)
            created_task = task
            return task

        mocker.patch("asyncio.create_task", side_effect=capture_task)

        with pytest.raises(asyncio.TimeoutError):
            await perform_proxy_handshake(
                config=mock_config,
                target_host=self.TARGET_HOST,
                target_port=self.TARGET_PORT,
            )

        assert created_task is not None
        assert created_task.cancelled()
        transport, _ = mock_loop.create_datagram_endpoint.return_value
        transport.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_not_configured(self, mock_config: MagicMock, mock_loop: MagicMock) -> None:
        mock_config.proxy = None

        with pytest.raises(ConfigurationError, match="Proxy is not configured"):
            await perform_proxy_handshake(
                config=mock_config,
                target_host=self.TARGET_HOST,
                target_port=self.TARGET_PORT,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_url", ["https://no-port", "https://:8080"])
    async def test_proxy_url_invalid(self, mock_config: MagicMock, mock_loop: MagicMock, invalid_url: str) -> None:
        mock_config.proxy.url = invalid_url

        with pytest.raises(ConfigurationError, match="Invalid proxy URL"):
            await perform_proxy_handshake(
                config=mock_config,
                target_host=self.TARGET_HOST,
                target_port=self.TARGET_PORT,
            )

    @pytest.mark.asyncio
    async def test_success(
        self,
        mock_config: MagicMock,
        mock_loop: MagicMock,
        setup_common_mocks: dict[str, MagicMock],
    ) -> None:
        mock_h3_engine = setup_common_mocks["h3"]
        mock_quic_class = setup_common_mocks["quic_class"]
        mock_protocol = setup_common_mocks["protocol"]
        headers_event = HeadersReceived(stream_id=0, headers={":status": "200"}, stream_ended=False)
        mock_h3_engine.handle_event.return_value = [headers_event]
        mock_protocol.get_event.return_value = MagicMock()

        proxy_addr = await perform_proxy_handshake(
            config=mock_config,
            target_host=self.TARGET_HOST,
            target_port=self.TARGET_PORT,
        )

        assert proxy_addr == ("proxy.internal", 8443)
        mock_quic_class.return_value.connect.assert_called_once()
        mock_h3_engine.send_headers.assert_called_once()
        mock_protocol.transmit.assert_called_once()
        transport, _ = mock_loop.create_datagram_endpoint.return_value
        transport.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_with_verify_mode(
        self, mock_config: MagicMock, setup_common_mocks: dict[str, MagicMock]
    ) -> None:
        mock_config.verify_mode = ssl.CERT_REQUIRED
        mock_quic_class = setup_common_mocks["quic_class"]
        mock_create_quic_config = setup_common_mocks["create_quic_config"]
        quic_config_instance = MagicMock()
        mock_create_quic_config.return_value = quic_config_instance

        headers_event = HeadersReceived(stream_id=0, headers={":status": "200"}, stream_ended=False)
        setup_common_mocks["h3"].handle_event.return_value = [headers_event]
        setup_common_mocks["protocol"].get_event.return_value = MagicMock()

        await perform_proxy_handshake(
            config=mock_config,
            target_host=self.TARGET_HOST,
            target_port=self.TARGET_PORT,
        )

        assert quic_config_instance.verify_mode == ssl.CERT_REQUIRED
        mock_quic_class.assert_called_once_with(configuration=quic_config_instance)


class TestProxyHandshakeProtocol:
    @pytest_asyncio.fixture
    async def protocol(self) -> _ProxyHandshakeProtocol:
        return _ProxyHandshakeProtocol(MagicMock())

    @pytest.mark.asyncio
    async def test_get_event_not_initialized(self, protocol: _ProxyHandshakeProtocol) -> None:
        with pytest.raises(HandshakeError, match="Event queue not initialized"):
            await protocol.get_event()

    @pytest.mark.asyncio
    async def test_quic_event_received_ignores_event_if_no_waiter(self, protocol: _ProxyHandshakeProtocol) -> None:
        protocol.connection_made(MagicMock())
        event = MagicMock()

        protocol.quic_event_received(event)

        assert protocol._event_queue is not None
        assert protocol._event_queue.empty()

    @pytest.mark.asyncio
    async def test_quic_event_received_ignores_event_if_waiter_done(self, protocol: _ProxyHandshakeProtocol) -> None:
        waiter: asyncio.Future[None] = asyncio.Future()
        waiter.set_result(None)
        protocol.connection_made(MagicMock())
        protocol.set_waiter(waiter)
        event = MagicMock()

        protocol.quic_event_received(event)

        assert protocol._event_queue is not None
        assert protocol._event_queue.empty()

    @pytest.mark.asyncio
    async def test_quic_event_received_queues_event(self, protocol: _ProxyHandshakeProtocol) -> None:
        waiter: asyncio.Future[None] = asyncio.Future()
        protocol.connection_made(MagicMock())
        protocol.set_waiter(waiter)
        event = MagicMock()

        protocol.quic_event_received(event)

        assert protocol._event_queue is not None
        assert protocol._event_queue.get_nowait() is event
