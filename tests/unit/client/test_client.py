"""Unit tests for the pywebtransport.client.client module."""

import asyncio
from typing import Any, Type

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ClientError, TimeoutError, WebTransportSession
from pywebtransport.client import ClientStats, WebTransportClient
from pywebtransport.connection import ConnectionManager, WebTransportConnection


class TestClientStats:
    def test_initialization(self) -> None:
        stats = ClientStats(created_at=1000.0)

        assert stats.created_at == 1000.0
        assert stats.connections_attempted == 0
        assert stats.connections_successful == 0
        assert stats.connections_failed == 0
        assert stats.total_connect_time == 0.0
        assert stats.min_connect_time == float("inf")
        assert stats.max_connect_time == 0.0

    def test_avg_connect_time(self) -> None:
        stats = ClientStats(created_at=0)
        assert stats.avg_connect_time == 0.0

        stats.connections_successful = 2
        stats.total_connect_time = 5.0

        assert stats.avg_connect_time == 2.5

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
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        mock = mocker.create_autospec(ClientConfig, instance=True)
        mock.connect_timeout = 10.0
        mock.to_dict.return_value = {"timeout": 10}
        mock.update.return_value = mock
        mock.max_connections = 100
        mock.connection_cleanup_interval = 30.0
        mock.connection_idle_check_interval = 5.0
        mock.connection_idle_timeout = 60.0
        mock.max_streams = 100
        mock.max_incoming_streams = 100
        mock.stream_cleanup_interval = 15.0
        return mock

    @pytest.fixture
    def mock_connection_manager(self, mocker: MockerFixture) -> Any:
        manager = mocker.create_autospec(ConnectionManager, instance=True)
        manager.__aenter__ = mocker.AsyncMock()
        manager.__aexit__ = mocker.AsyncMock()
        return manager

    @pytest.fixture
    def mock_create_client(self, mocker: MockerFixture, mock_webtransport_connection: Any) -> Any:
        return mocker.patch(
            "pywebtransport.client.client.WebTransportConnection.create_client",
            new_callable=mocker.AsyncMock,
            return_value=mock_webtransport_connection,
        )

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_ready = True
        return session

    @pytest.fixture
    def mock_webtransport_connection(self, mocker: MockerFixture) -> Any:
        connection = mocker.create_autospec(WebTransportConnection, instance=True)
        connection.wait_for_ready_session = mocker.AsyncMock(return_value="session-123")
        connection.is_closed = False
        connection.protocol_handler = mocker.MagicMock()
        return connection

    @pytest.fixture(autouse=True)
    def setup_common_mocks(
        self,
        mocker: MockerFixture,
        mock_client_config: Any,
        mock_connection_manager: Any,
        mock_session: Any,
    ) -> None:
        mocker.patch("pywebtransport.client.client.ClientConfig.create", return_value=mock_client_config)
        mocker.patch("pywebtransport.client.client.ConnectionManager.create", return_value=mock_connection_manager)
        mocker.patch("pywebtransport.client.client.WebTransportSession", return_value=mock_session)
        mocker.patch("pywebtransport.client.client.get_logger")
        mocker.patch("pywebtransport.client.client.get_timestamp", return_value=1000.0)
        mocker.patch("pywebtransport.client.client.validate_url")
        mocker.patch("pywebtransport.client.client.parse_webtransport_url", return_value=("example.com", 443, "/"))
        mocker.patch("pywebtransport.client.client.format_duration")
        mock_timer_class = mocker.patch("pywebtransport.client.client.Timer")
        mock_timer_instance = mock_timer_class.return_value.__enter__.return_value
        mock_timer_instance.elapsed = 1.23

    def test_initialization_default(self, mock_client_config: Any, mocker: MockerFixture) -> None:
        mock_cm_create = mocker.patch("pywebtransport.client.client.ConnectionManager.create")

        client = WebTransportClient()

        assert client.config is mock_client_config
        mock_cm_create.assert_called_once_with(
            max_connections=mock_client_config.max_connections,
            connection_cleanup_interval=mock_client_config.connection_cleanup_interval,
            connection_idle_check_interval=mock_client_config.connection_idle_check_interval,
            connection_idle_timeout=mock_client_config.connection_idle_timeout,
        )
        assert not client.is_closed

    def test_initialization_custom_config(self) -> None:
        custom_config = ClientConfig()

        client = WebTransportClient(config=custom_config)

        assert client.config is custom_config

    def test_set_default_headers(self) -> None:
        client = WebTransportClient()
        headers = {"X-Test": "true"}

        client.set_default_headers(headers)

        assert client._default_headers == headers
        headers["X-Another"] = "value"
        assert client._default_headers != headers

    def test_diagnose_issues(self) -> None:
        client = WebTransportClient()
        assert client.diagnose_issues() == []

        client._stats.connections_attempted = 20
        client._stats.connections_successful = 10
        issues = client.diagnose_issues()
        assert len(issues) == 1
        assert "Low connection success rate" in issues[0]

        client._stats.connections_attempted = 1
        client._stats.connections_successful = 1
        client._stats.total_connect_time = 6.0
        issues = client.diagnose_issues()
        assert len(issues) == 1
        assert "Slow average connection time" in issues[0]

    def test_diagnose_issues_when_closed(self) -> None:
        client = WebTransportClient()
        client._closed = True

        issues = client.diagnose_issues()

        assert "Client is closed." in issues

    def test_debug_state(self, mock_client_config: Any) -> None:
        client = WebTransportClient()

        state = client.debug_state()

        assert state["client"]["closed"] is False
        assert state["config"] == {"timeout": 10}
        assert "statistics" in state

    @pytest.mark.asyncio
    async def test_close(self, mock_connection_manager: Any) -> None:
        client = WebTransportClient()
        assert not client.is_closed

        await client.close()
        assert client.is_closed

        await client.close()  # type: ignore[unreachable]
        mock_connection_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_context_manager(self, mock_connection_manager: Any) -> None:
        async with WebTransportClient():
            mock_connection_manager.__aenter__.assert_awaited_once()

        mock_connection_manager.shutdown.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_success(
        self,
        mocker: MockerFixture,
        mock_connection_manager: Any,
        mock_webtransport_connection: Any,
        mock_session: Any,
        mock_create_client: Any,
    ) -> None:
        mock_session_class = mocker.patch("pywebtransport.client.client.WebTransportSession", return_value=mock_session)
        client = WebTransportClient()

        session: Any = await client.connect("https://example.com")

        mock_connection_manager.add_connection.assert_awaited_once_with(mock_webtransport_connection)
        mock_create_client.assert_awaited_once()
        mock_webtransport_connection.wait_for_ready_session.assert_awaited_once()
        assert session is mock_session
        mock_session_class.assert_called_once_with(
            connection=mock_webtransport_connection,
            session_id="session-123",
            max_streams=client.config.max_streams,
            max_incoming_streams=client.config.max_incoming_streams,
            stream_cleanup_interval=client.config.stream_cleanup_interval,
        )
        mock_session.initialize.assert_awaited_once()
        stats = client._stats
        assert stats.connections_attempted == 1
        assert stats.connections_successful == 1
        assert stats.connections_failed == 0
        assert stats.total_connect_time == 1.23
        assert stats.min_connect_time == 1.23
        assert stats.max_connect_time == 1.23

    @pytest.mark.asyncio
    async def test_connect_with_headers(self, mock_client_config: Any, mock_create_client: Any) -> None:
        client = WebTransportClient()
        client.set_default_headers({"default": "header"})

        await client.connect("https://example.com", headers={"extra": "header"})

        expected_headers = {"default": "header", "extra": "header"}
        mock_client_config.update.assert_called_once_with(headers=expected_headers)

    @pytest.mark.asyncio
    async def test_connect_when_closed(self) -> None:
        client = WebTransportClient()
        await client.close()

        with pytest.raises(ClientError, match="Client is closed"):
            await client.connect("https://example.com")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception_to_raise", [asyncio.TimeoutError, ConnectionRefusedError])
    async def test_connect_fails_during_connection(
        self, mock_webtransport_connection: Any, exception_to_raise: Type[Exception], mock_create_client: Any
    ) -> None:
        mock_create_client.side_effect = exception_to_raise
        client = WebTransportClient()
        expected_exception = TimeoutError if exception_to_raise == asyncio.TimeoutError else ClientError

        with pytest.raises(expected_exception):
            await client.connect("https://example.com")

        mock_webtransport_connection.close.assert_not_awaited()
        stats = client._stats
        assert stats.connections_attempted == 1
        assert stats.connections_successful == 0
        assert stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_fails_on_session_ready(
        self, mock_webtransport_connection: Any, mock_create_client: Any
    ) -> None:
        mock_webtransport_connection.wait_for_ready_session.side_effect = asyncio.TimeoutError
        client = WebTransportClient()

        with pytest.raises(ClientError, match="Session ready timeout"):
            await client.connect("https://example.com")

        mock_webtransport_connection.close.assert_awaited_once()
        assert client._stats.connections_failed == 1

    @pytest.mark.asyncio
    async def test_connect_fails_no_protocol_handler(
        self, mock_webtransport_connection: Any, mock_create_client: Any
    ) -> None:
        mock_webtransport_connection.protocol_handler = None
        client = WebTransportClient()

        with pytest.raises(ClientError, match="Protocol handler not initialized"):
            await client.connect("https://example.com")

        mock_webtransport_connection.close.assert_awaited_once()
        assert client._stats.connections_failed == 1
