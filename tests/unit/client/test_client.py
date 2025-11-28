"""Unit tests for the pywebtransport.client.client module."""

import asyncio
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import (
    ClientConfig,
    ClientError,
    ConnectionError,
    TimeoutError,
    WebTransportClient,
    WebTransportSession,
)
from pywebtransport.client import ClientDiagnostics, ClientStats
from pywebtransport.connection import WebTransportConnection
from pywebtransport.manager import ConnectionManager
from pywebtransport.types import ConnectionState, EventType


class TestClientDiagnostics:
    @pytest.mark.parametrize(
        "stats_data, expected_issue_part",
        [
            ({}, None),
            ({"connections_attempted": 20, "success_rate": 0.5}, "Low connection success rate"),
            ({"avg_connect_time": 6.5}, "Slow average connection time"),
        ],
    )
    def test_issues_property(
        self, mocker: MockerFixture, stats_data: dict[str, Any], expected_issue_part: str | None
    ) -> None:
        mock_stats = mocker.create_autospec(ClientStats, instance=True)
        mock_stats.to_dict.return_value = stats_data
        diagnostics = ClientDiagnostics(stats=mock_stats, connection_states={})

        issues = diagnostics.issues

        if expected_issue_part:
            assert any(expected_issue_part in issue for issue in issues)
        else:
            assert not issues


class TestClientStats:
    def test_avg_connect_time(self) -> None:
        stats = ClientStats(created_at=0)
        assert stats.avg_connect_time == 0.0

        stats.connections_successful = 2
        stats.total_connect_time = 5.0

        assert stats.avg_connect_time == 2.5

    def test_initialization(self) -> None:
        stats = ClientStats(created_at=1000.0)

        assert stats.created_at == 1000.0
        assert stats.connections_attempted == 0
        assert stats.connections_successful == 0
        assert stats.connections_failed == 0
        assert stats.total_connect_time == 0.0
        assert stats.min_connect_time == float("inf")
        assert stats.max_connect_time == 0.0

    def test_success_rate(self) -> None:
        stats = ClientStats(created_at=0)
        assert stats.success_rate == 1.0

        stats.connections_attempted = 10
        stats.connections_successful = 8
        assert stats.success_rate == 0.8

        stats.connections_attempted = 10
        stats.connections_successful = 0
        assert stats.success_rate == 0.0

    def test_to_dict(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.client.client.get_timestamp", return_value=1010.0)
        stats = ClientStats(created_at=1000.0)
        stats.min_connect_time = 1.2

        stats_dict = stats.to_dict()

        assert stats_dict["uptime"] == 10.0
        assert stats_dict["min_connect_time"] == 1.2
        assert stats_dict["max_connect_time"] == 0.0

        stats.min_connect_time = float("inf")
        stats_dict = stats.to_dict()
        assert stats_dict["min_connect_time"] == 0.0


class TestWebTransportClient:
    @pytest.fixture
    def client(self, mock_client_config: Any, mock_connection_manager: Any) -> WebTransportClient:
        return WebTransportClient(config=mock_client_config)

    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        mock = mocker.create_autospec(ClientConfig, instance=True)
        mock.connect_timeout = 10.0
        mock.update.return_value = mock
        mock.max_connections = 100
        mock.connection_idle_timeout = 60.0
        return mock

    @pytest.fixture
    def mock_create_connection(self, mocker: MockerFixture, mock_webtransport_connection: Any) -> Any:
        return mocker.patch("pywebtransport.client.client.create_connection", return_value=mock_webtransport_connection)

    @pytest.fixture
    def mock_connection_manager(self, mocker: MockerFixture) -> Any:
        manager = mocker.create_autospec(ConnectionManager, instance=True)
        manager.__aenter__ = mocker.AsyncMock()
        manager.__aexit__ = mocker.AsyncMock()
        manager.__len__.return_value = 0
        mocker.patch("pywebtransport.client.client.ConnectionManager", return_value=manager)
        return manager

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.session_id = "session-123"
        session.is_closed = False
        return session

    @pytest.fixture
    def mock_webtransport_connection(self, mocker: MockerFixture, mock_session: Any) -> Any:
        connection = mocker.create_autospec(WebTransportConnection, instance=True)
        connection.is_closed = False
        connection.is_connected = False
        connection.events = mocker.MagicMock()
        connection.events.wait_for = mocker.AsyncMock()
        connection.create_session = mocker.AsyncMock(return_value=mock_session)
        return connection

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.client.client.validate_url")
        mocker.patch("pywebtransport.client.client.parse_webtransport_url", return_value=("example.com", 443, "/"))
        mocker.patch("pywebtransport.client.client.format_duration")

        mock_timer_class = mocker.patch("pywebtransport.client.client.Timer")
        mock_timer_instance = mock_timer_class.return_value.__enter__.return_value
        mock_timer_instance.elapsed = 1.23

    @pytest.mark.asyncio
    async def test_close(self, client: WebTransportClient, mock_connection_manager: Any) -> None:
        await client.close()
        await client.close()
        assert client.is_closed
        mock_connection_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_failure_generic(
        self, client: WebTransportClient, mock_create_connection: Any, mock_webtransport_connection: Any
    ) -> None:
        mock_create_connection.side_effect = RuntimeError("Generic failure")

        with pytest.raises(ClientError, match="Failed to connect to .*: Generic failure"):
            await client.connect(url="https://example.com")

        mock_webtransport_connection.close.assert_not_awaited()
        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_failure_timeout(
        self, client: WebTransportClient, mock_create_connection: Any, mock_webtransport_connection: Any
    ) -> None:
        mock_create_connection.side_effect = asyncio.TimeoutError()

        with pytest.raises(TimeoutError, match="Connection timeout to .* during .*"):
            await client.connect(url="https://example.com")

        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_failure_connection_refused(
        self, client: WebTransportClient, mock_create_connection: Any
    ) -> None:
        mock_create_connection.side_effect = ConnectionRefusedError()

        with pytest.raises(ConnectionError, match="Connection refused"):
            await client.connect(url="https://example.com")

        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_failure_certificate(self, client: WebTransportClient, mock_create_connection: Any) -> None:
        mock_create_connection.side_effect = Exception("certificate verify failed")

        with pytest.raises(ConnectionError, match="Certificate verification failed"):
            await client.connect(url="https://example.com")

        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_fails_during_session_creation(
        self,
        client: WebTransportClient,
        mock_create_connection: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_webtransport_connection.create_session.side_effect = RuntimeError("Session init failed")
        type(mock_webtransport_connection).is_connected = mocker.PropertyMock(return_value=True)

        with pytest.raises(ClientError, match="Session init failed"):
            await client.connect(url="https://example.com")

        mock_webtransport_connection.close.assert_awaited_once()
        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_success(
        self,
        client: WebTransportClient,
        mock_create_connection: Any,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mock_session: Any,
    ) -> None:
        session = await client.connect(url="https://example.com")

        mock_create_connection.assert_awaited_once()
        mock_webtransport_connection.events.wait_for.assert_awaited_with(event_type=EventType.CONNECTION_ESTABLISHED)
        mock_connection_manager.add_connection.assert_awaited_once_with(connection=mock_webtransport_connection)
        mock_webtransport_connection.create_session.assert_awaited_once_with(path="/", headers={})

        assert session is mock_session
        stats = client._stats
        assert stats.connections_successful == 1
        assert stats.total_connect_time == 1.23

    @pytest.mark.asyncio
    async def test_connect_timeout_checks_after_connection_creation(
        self,
        client: WebTransportClient,
        mock_create_connection: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_timer_instance = mocker.Mock()
        type(mock_timer_instance).elapsed = mocker.PropertyMock(return_value=11.0)
        mock_timer_cls = mocker.patch("pywebtransport.client.client.Timer")
        mock_timer_cls.return_value.__enter__.return_value = mock_timer_instance

        with pytest.raises(TimeoutError, match="Connection timeout .* during QUIC connection establishment"):
            await client.connect(url="https://example.com", timeout=10.0)

        mock_webtransport_connection.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_timeout_checks_after_connection_established(
        self,
        client: WebTransportClient,
        mock_create_connection: Any,
        mock_webtransport_connection: Any,
        mock_connection_manager: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_timer_instance = mocker.Mock()
        type(mock_timer_instance).elapsed = mocker.PropertyMock(side_effect=[0.1, 11.0])
        mock_timer_cls = mocker.patch("pywebtransport.client.client.Timer")
        mock_timer_cls.return_value.__enter__.return_value = mock_timer_instance

        type(mock_webtransport_connection).is_connected = mocker.PropertyMock(return_value=True)

        with pytest.raises(TimeoutError, match="Connection timeout .* during session negotiation"):
            await client.connect(url="https://example.com", timeout=10.0)

        mock_webtransport_connection.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_when_closed(self, client: WebTransportClient) -> None:
        await client.close()
        with pytest.raises(ClientError, match="Client is closed"):
            await client.connect(url="https://example.com")

    @pytest.mark.asyncio
    async def test_connect_with_headers(
        self, client: WebTransportClient, mock_create_connection: Any, mock_client_config: Any
    ) -> None:
        client.set_default_headers(headers={"default": "header"})

        await client.connect(url="https://example.com", headers={"extra": "header"})

        expected_headers = {"default": "header", "extra": "header"}
        mock_client_config.update.assert_called_once_with(headers=expected_headers)
        mock_create_connection.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, client: WebTransportClient, mock_connection_manager: Any) -> None:
        async with client:
            mock_connection_manager.__aenter__.assert_awaited_once()
        mock_connection_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_diagnostics(
        self, client: WebTransportClient, mock_connection_manager: Any, mocker: MockerFixture
    ) -> None:
        mock_conn = mocker.MagicMock()
        mock_conn.state = ConnectionState.CONNECTED
        mock_connection_manager.get_all_resources = mocker.AsyncMock(return_value=[mock_conn])

        diagnostics = await client.diagnostics()

        assert isinstance(diagnostics, ClientDiagnostics)
        assert diagnostics.stats is client._stats
        assert diagnostics.connection_states == {ConnectionState.CONNECTED: 1}

    def test_initialization_custom_config(self, mocker: MockerFixture) -> None:
        mock_config = mocker.Mock(spec=ClientConfig)
        mock_config.max_connections = 15
        mock_config.connection_idle_timeout = 30.0

        mock_cm = mocker.patch("pywebtransport.client.client.ConnectionManager", autospec=True)

        client = WebTransportClient(config=mock_config)

        assert client.config is mock_config
        mock_cm.assert_called_once_with(max_connections=15)

    def test_initialization_default(self, mocker: MockerFixture) -> None:
        mock_cm_constructor = mocker.patch("pywebtransport.client.client.ConnectionManager", autospec=True)
        mock_config_cls = mocker.patch("pywebtransport.client.client.ClientConfig", autospec=True)
        mock_config_instance = mock_config_cls.return_value

        mock_config_instance.max_connections = 100
        mock_config_instance.connection_idle_timeout = 60.0

        WebTransportClient()

        mock_cm_constructor.assert_called_once_with(max_connections=100)

    def test_str_representation(self, client: WebTransportClient, mock_connection_manager: Any) -> None:
        mock_connection_manager.__len__.return_value = 5
        assert str(client) == "WebTransportClient(status=open, connections=5)"

        client._closed = True
        assert str(client) == "WebTransportClient(status=closed, connections=5)"
