"""Unit tests for the pywebtransport._adapter.client module."""

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig
from pywebtransport._adapter.client import WebTransportClientProtocol, create_connection


class TestCreateConnection:

    @pytest.fixture
    def client_config(self) -> ClientConfig:
        return ClientConfig()

    @pytest.fixture
    def mock_create_quic_config(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("pywebtransport._adapter.client.create_quic_configuration")

    @pytest.fixture
    def mock_loop(self, mocker: MockerFixture) -> MagicMock:
        loop = mocker.Mock(spec=asyncio.AbstractEventLoop)
        loop.time.return_value = 1000.0

        async def side_effect(*args: Any, **kwargs: Any) -> tuple[MagicMock, WebTransportClientProtocol]:
            factory = kwargs.get("protocol_factory")
            if not factory and args:
                factory = args[0]
            if not factory:
                raise ValueError("protocol_factory not found in arguments")

            protocol = factory()
            transport = mocker.Mock(spec=asyncio.DatagramTransport)
            return transport, protocol

        loop.create_datagram_endpoint = mocker.AsyncMock(side_effect=side_effect)
        return cast(MagicMock, loop)

    @pytest.fixture
    def mock_quic_connection_class(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("pywebtransport._adapter.client.QuicConnection", autospec=True)

    @pytest.fixture
    def mock_web_transport_connection(self, mocker: MockerFixture) -> MagicMock:
        return mocker.patch("pywebtransport._adapter.client.WebTransportConnection", autospec=True)

    @pytest.mark.asyncio
    async def test_create_connection_no_certs(
        self,
        client_config: ClientConfig,
        mock_loop: MagicMock,
        mock_create_quic_config: MagicMock,
        mock_web_transport_connection: MagicMock,
        mock_quic_connection_class: MagicMock,
    ) -> None:
        client_config.certfile = None
        client_config.keyfile = None

        await create_connection(host="example.com", port=4433, config=client_config, loop=mock_loop)

        assert mock_create_quic_config.call_args.kwargs.get("certfile") is None
        assert mock_create_quic_config.call_args.kwargs.get("keyfile") is None

    @pytest.mark.asyncio
    async def test_create_connection_partial_certs(
        self,
        client_config: ClientConfig,
        mock_loop: MagicMock,
        mock_create_quic_config: MagicMock,
        mock_web_transport_connection: MagicMock,
        mock_quic_connection_class: MagicMock,
    ) -> None:
        client_config.certfile = "/path/to/cert.pem"
        client_config.keyfile = None

        await create_connection(host="example.com", port=4433, config=client_config, loop=mock_loop)

        assert mock_create_quic_config.call_args.kwargs.get("certfile") == "/path/to/cert.pem"
        assert mock_create_quic_config.call_args.kwargs.get("keyfile") is None

    @pytest.mark.asyncio
    async def test_create_connection_success(
        self,
        client_config: ClientConfig,
        mock_loop: MagicMock,
        mock_create_quic_config: MagicMock,
        mock_web_transport_connection: MagicMock,
        mock_quic_connection_class: MagicMock,
    ) -> None:
        quic_config_instance = mock_create_quic_config.return_value
        quic_config_instance.server_name = "example.com"
        mock_quic_instance = mock_quic_connection_class.return_value

        connection = await create_connection(host="example.com", port=4433, config=client_config, loop=mock_loop)

        mock_create_quic_config.assert_called_once_with(
            alpn_protocols=client_config.alpn_protocols,
            congestion_control_algorithm=client_config.congestion_control_algorithm,
            idle_timeout=client_config.connection_idle_timeout,
            is_client=True,
            max_datagram_size=client_config.max_datagram_size,
            ca_certs=None,
            certfile=None,
            keyfile=None,
            verify_mode=client_config.verify_mode,
            server_name="example.com",
        )
        assert quic_config_instance.server_name == "example.com"

        mock_loop.create_datagram_endpoint.assert_awaited_once()
        mock_quic_instance.connect.assert_called_once_with(addr=("example.com", 4433), now=1000.0)
        mock_web_transport_connection.assert_called_once()
        connection_instance = mock_web_transport_connection.return_value
        connection_instance.initialize.assert_awaited_once()

        assert connection == connection_instance

    @pytest.mark.asyncio
    async def test_create_connection_verify_mode(
        self,
        client_config: ClientConfig,
        mock_loop: MagicMock,
        mock_create_quic_config: MagicMock,
        mock_web_transport_connection: MagicMock,
        mock_quic_connection_class: MagicMock,
    ) -> None:
        client_config.verify_mode = False  # type: ignore

        await create_connection(host="example.com", port=4433, config=client_config, loop=mock_loop)

        assert mock_create_quic_config.call_args.kwargs.get("verify_mode") is False

    @pytest.mark.asyncio
    async def test_create_connection_with_ca_certs(
        self,
        client_config: ClientConfig,
        mock_loop: MagicMock,
        mock_create_quic_config: MagicMock,
        mock_web_transport_connection: MagicMock,
        mock_quic_connection_class: MagicMock,
    ) -> None:
        client_config.ca_certs = "/path/to/ca.pem"

        await create_connection(host="example.com", port=4433, config=client_config, loop=mock_loop)

        assert mock_create_quic_config.call_args.kwargs.get("ca_certs") == "/path/to/ca.pem"

    @pytest.mark.asyncio
    async def test_create_connection_with_client_cert(
        self,
        client_config: ClientConfig,
        mock_loop: MagicMock,
        mock_create_quic_config: MagicMock,
        mock_web_transport_connection: MagicMock,
        mock_quic_connection_class: MagicMock,
    ) -> None:
        client_config.certfile = "/path/to/cert.pem"
        client_config.keyfile = "/path/to/key.pem"

        await create_connection(host="example.com", port=4433, config=client_config, loop=mock_loop)

        assert mock_create_quic_config.call_args.kwargs.get("certfile") == "/path/to/cert.pem"
        assert mock_create_quic_config.call_args.kwargs.get("keyfile") == "/path/to/key.pem"
