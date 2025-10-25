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
from pywebtransport.types import ConnectionState


class TestClientDiagnostics:
    @pytest.mark.parametrize(
        "stats_data, expected_issue_part",
        [
            ({}, None),
            (
                {"connections": {"attempted": 20, "success_rate": 0.5}},
                "Low connection success rate",
            ),
            (
                {"performance": {"avg_connect_time": 6.5}},
                "Slow average connection time",
            ),
        ],
    )
    def test_issues_property(
        self,
        mocker: MockerFixture,
        stats_data: dict[str, Any],
        expected_issue_part: str | None,
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
        assert stats_dict["performance"]["min_connect_time"] == 1.2
        assert stats_dict["performance"]["max_connect_time"] == 0.0

        stats.min_connect_time = float("inf")
        stats_dict = stats.to_dict()
        assert stats_dict["performance"]["min_connect_time"] == 0.0


class TestWebTransportClient:
    @pytest.fixture
    def client(
        self,
        mock_client_config: Any,
        mock_connection_factory: Any,
        mock_session_factory: Any,
        mock_connection_manager: Any,
    ) -> WebTransportClient:
        return WebTransportClient(
            config=mock_client_config,
            connection_factory=mock_connection_factory,
            session_factory=mock_session_factory,
        )

    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        mock = mocker.create_autospec(ClientConfig, instance=True)
        mock.connect_timeout = 10.0
        mock.update.return_value = mock
        return mock

    @pytest.fixture
    def mock_connection_factory(self, mocker: MockerFixture, mock_webtransport_connection: Any) -> Any:
        return mocker.AsyncMock(return_value=mock_webtransport_connection)

    @pytest.fixture
    def mock_connection_manager(self, mocker: MockerFixture) -> Any:
        manager = mocker.create_autospec(ConnectionManager, instance=True)
        manager.__aenter__ = mocker.AsyncMock()
        manager.__aexit__ = mocker.AsyncMock()
        mocker.patch("pywebtransport.client.client.ConnectionManager", return_value=manager)
        return manager

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_ready = True
        return session

    @pytest.fixture
    def mock_session_factory(self, mocker: MockerFixture, mock_session: Any) -> Any:
        return mocker.AsyncMock(return_value=mock_session)

    @pytest.fixture
    def mock_webtransport_connection(self, mocker: MockerFixture, mock_client_config: Any) -> Any:
        connection = mocker.create_autospec(WebTransportConnection, instance=True)
        connection.wait_for_ready_session = mocker.AsyncMock(return_value="session-123")
        connection.is_closed = False
        connection.protocol_handler = mocker.MagicMock()
        connection.config = mock_client_config
        return connection

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture) -> None:
        mocker.patch("pywebtransport.client.client.validate_url")
        mocker.patch(
            "pywebtransport.client.client.parse_webtransport_url",
            return_value=("example.com", 443, "/"),
        )
        mocker.patch("pywebtransport.client.client.format_duration")
        mocker.patch(
            "pywebtransport.client.client.perform_proxy_handshake",
            new_callable=mocker.AsyncMock,
        )
        mock_timer_class = mocker.patch("pywebtransport.client.client.Timer")
        mock_timer_instance = mock_timer_class.return_value.__enter__.return_value
        mock_timer_instance.elapsed = 1.23

    @pytest.mark.asyncio
    async def test_close(self, client: WebTransportClient, mock_connection_manager: Any) -> None:
        assert not client.is_closed
        await client.close()
        assert client.is_closed
        await client.close()  # type: ignore[unreachable]
        mock_connection_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_failure_after_session_creation(
        self,
        client: WebTransportClient,
        mock_session: Any,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        """
        Test that session and connection are closed if an error occurs after
        the session has been successfully created.
        """
        mocker.patch.object(client, "_update_success_stats", side_effect=RuntimeError("stats error"))
        mock_session.is_closed = False

        with pytest.raises(ClientError, match="stats error"):
            await client.connect(url="https://example.com")

        assert client._stats.connections_failed == 1
        mock_session.close.assert_awaited_once()
        mock_webtransport_connection.close.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exception_to_raise, expected_exception, match_pattern",
        [
            (asyncio.TimeoutError(), TimeoutError, r"Connection timeout to .* after 10.0s"),
            (
                ConnectionRefusedError("Connection refused"),
                ClientError,
                r"Failed to connect to .*: Connection refused",
            ),
            (
                RuntimeError("generic error"),
                ClientError,
                r"Failed to connect to .*: generic error",
            ),
        ],
    )
    async def test_connect_fails_during_connection(
        self,
        client: WebTransportClient,
        mock_connection_factory: Any,
        mock_webtransport_connection: Any,
        exception_to_raise: Exception,
        expected_exception: type[Exception],
        match_pattern: str,
    ) -> None:
        mock_connection_factory.side_effect = exception_to_raise

        with pytest.raises(expected_exception, match=match_pattern):
            await client.connect(url="https://example.com")

        mock_webtransport_connection.close.assert_not_awaited()
        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_fails_no_protocol_handler(
        self, client: WebTransportClient, mock_webtransport_connection: Any
    ) -> None:
        mock_webtransport_connection.protocol_handler = None

        with pytest.raises(ConnectionError, match="Protocol handler not initialized after connection"):
            await client.connect(url="https://example.com")

        mock_webtransport_connection.close.assert_awaited_once()
        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_fails_on_session_ready(
        self, client: WebTransportClient, mock_webtransport_connection: Any
    ) -> None:
        mock_webtransport_connection.wait_for_ready_session.side_effect = asyncio.TimeoutError

        with pytest.raises(TimeoutError, match="Session ready timeout"):
            await client.connect(url="https://example.com")

        mock_webtransport_connection.close.assert_awaited_once()
        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_fails_with_invalid_connection_config(
        self,
        client: WebTransportClient,
        mock_webtransport_connection: Any,
        mocker: MockerFixture,
    ) -> None:
        mock_webtransport_connection.config = mocker.MagicMock()

        with pytest.raises(
            ClientError,
            match="A connection managed by WebTransportClient has a non-ClientConfig",
        ):
            await client.connect(url="https://example.com")

        mock_webtransport_connection.close.assert_awaited_once()
        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_success(
        self,
        client: WebTransportClient,
        mock_connection_factory: Any,
        mock_session_factory: Any,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mock_session: Any,
    ) -> None:
        session = await client.connect(url="https://example.com")

        mock_connection_factory.assert_awaited_once()
        mock_connection_manager.add_connection.assert_awaited_once_with(connection=mock_webtransport_connection)
        mock_webtransport_connection.wait_for_ready_session.assert_awaited_once()
        mock_session_factory.assert_awaited_once_with(
            connection=mock_webtransport_connection,
            session_id="session-123",
            max_streams=client.config.max_streams,
            max_incoming_streams=client.config.max_incoming_streams,
            stream_cleanup_interval=client.config.stream_cleanup_interval,
        )
        assert session is mock_session
        stats = client._stats
        assert stats.connections_successful == 1
        assert stats.total_connect_time == 1.23

    @pytest.mark.asyncio
    async def test_connect_when_closed(self, client: WebTransportClient) -> None:
        await client.close()
        with pytest.raises(ClientError, match="Client is closed"):
            await client.connect(url="https://example.com")

    @pytest.mark.asyncio
    async def test_connect_with_headers_and_proxy(
        self, client: WebTransportClient, mock_client_config: Any, mocker: MockerFixture
    ) -> None:
        mock_proxy_handshake = mocker.patch(
            "pywebtransport.client.client.perform_proxy_handshake",
            new_callable=mocker.AsyncMock,
        )
        client.set_default_headers(headers={"default": "header"})
        mock_client_config.proxy = True

        await client.connect(url="https://example.com", headers={"extra": "header"})

        expected_headers = {"default": "header", "extra": "header"}
        mock_client_config.update.assert_called_once_with(headers=expected_headers)
        mock_proxy_handshake.assert_awaited_once()

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

    def test_initialization_custom_config(self, mock_client_config: Any) -> None:
        client = WebTransportClient(config=mock_client_config)
        assert client.config is mock_client_config

    def test_initialization_default(self, mocker: MockerFixture) -> None:
        mock_cm_constructor = mocker.patch("pywebtransport.client.client.ConnectionManager", autospec=True)
        mock_config = mocker.patch("pywebtransport.client.client.ClientConfig", autospec=True).return_value

        WebTransportClient()

        mock_cm_constructor.assert_called_once_with(
            max_connections=mock_config.max_connections,
            connection_cleanup_interval=mock_config.connection_cleanup_interval,
            connection_idle_check_interval=mock_config.connection_idle_check_interval,
            connection_idle_timeout=mock_config.connection_idle_timeout,
        )


@pytest.mark.asyncio
async def test_connect_uses_default_factories(mocker: MockerFixture) -> None:
    """Verify that connect uses the default factories when none are provided."""
    mocker.patch("pywebtransport.client.client.validate_url")
    mocker.patch(
        "pywebtransport.client.client.parse_webtransport_url",
        return_value=("example.com", 443, "/"),
    )
    mock_timer_class = mocker.patch("pywebtransport.client.client.Timer")
    mock_timer_instance = mock_timer_class.return_value.__enter__.return_value
    mock_timer_instance.elapsed = 1.23
    mocker.patch(
        "pywebtransport.client.client.perform_proxy_handshake",
        new_callable=mocker.AsyncMock,
    )

    mock_conn = mocker.create_autospec(WebTransportConnection, instance=True)
    mock_conn.wait_for_ready_session = mocker.AsyncMock(return_value="session-123")
    mock_conn.config = ClientConfig()
    mock_conn.is_closed = False
    mock_conn_creator = mocker.patch(
        "pywebtransport.connection.connection.WebTransportConnection.create_client",
        new_callable=mocker.AsyncMock,
        return_value=mock_conn,
    )

    mock_session = mocker.create_autospec(WebTransportSession, instance=True)
    mock_session.initialize = mocker.AsyncMock()
    mock_session_constructor = mocker.patch(
        "pywebtransport.client.client.WebTransportSession",
        autospec=True,
        return_value=mock_session,
    )

    async with WebTransportClient() as client:
        await client.connect(url="https://example.com")

    mock_conn_creator.assert_awaited_once()
    mock_session_constructor.assert_called_once()
    mock_session.initialize.assert_awaited_once()
