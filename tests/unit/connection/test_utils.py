"""Unit tests for the pywebtransport.connection.utils module."""

import asyncio
import re
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError, HandshakeError
from pywebtransport.connection import WebTransportConnection
from pywebtransport.connection import utils as connection_utils


@pytest.fixture
def mock_client_config(mocker: MockerFixture) -> Any:
    return mocker.MagicMock(spec=ClientConfig)


@pytest.fixture
def mock_connection(mocker: MockerFixture) -> Any:
    connection = mocker.create_autospec(WebTransportConnection, instance=True)
    connection.is_connected = True
    connection.close = mocker.AsyncMock()
    return connection


class TestConnectionUtils:
    async def test_connect_with_retry_success_first_try(
        self, mock_client_config: ClientConfig, mock_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_create = mocker.patch.object(WebTransportConnection, "create_client", return_value=mock_connection)
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

        conn = await connection_utils.connect_with_retry(config=mock_client_config, host="h", port=1)

        assert conn is mock_connection
        mock_create.assert_awaited_once()
        mock_sleep.assert_not_awaited()

    async def test_connect_with_retry_success_after_retries(
        self, mock_client_config: ClientConfig, mock_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_create = mocker.patch.object(
            WebTransportConnection,
            "create_client",
            side_effect=[ConnectionError("fail1"), HandshakeError("fail2"), mock_connection],
        )
        mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

        conn = await connection_utils.connect_with_retry(config=mock_client_config, host="h", port=1, retry_delay=0.1)

        assert conn is mock_connection
        assert mock_create.await_count == 3
        assert mock_sleep.await_count == 2
        mock_sleep.assert_has_awaits([mocker.call(0.1), mocker.call(0.2)])

    async def test_connect_with_retry_all_attempts_fail(
        self, mock_client_config: ClientConfig, mocker: MockerFixture
    ) -> None:
        last_error = ConnectionError("last error")
        mock_create = mocker.patch.object(WebTransportConnection, "create_client", side_effect=last_error)
        mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        part1 = re.escape("Failed to connect after 4 attempts:")
        part2 = re.escape("last error")
        match_pattern = f".*{part1}.*{part2}"

        with pytest.raises(ConnectionError, match=match_pattern):
            await connection_utils.connect_with_retry(config=mock_client_config, host="h", port=1, max_retries=3)

        assert mock_create.await_count == 4

    async def test_ensure_connection_already_connected(
        self, mock_client_config: ClientConfig, mock_connection: WebTransportConnection
    ) -> None:
        conn = await connection_utils.ensure_connection(mock_connection, mock_client_config, host="h", port=1)
        assert conn is mock_connection
        mock_connection.close.assert_not_awaited()

    async def test_ensure_connection_reconnects(
        self, mock_client_config: ClientConfig, mock_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        mock_connection.is_connected = False
        new_mock_connection = mocker.create_autospec(WebTransportConnection, instance=True)
        mock_create = mocker.patch.object(WebTransportConnection, "create_client", return_value=new_mock_connection)

        conn = await connection_utils.ensure_connection(mock_connection, mock_client_config, host="h", port=1)

        assert conn is new_mock_connection
        mock_connection.close.assert_awaited_once()
        mock_create.assert_awaited_once_with(config=mock_client_config, host="h", port=1, path="/")

    async def test_ensure_connection_reconnect_disabled(
        self, mock_client_config: ClientConfig, mock_connection: WebTransportConnection
    ) -> None:
        mock_connection.is_connected = False
        with pytest.raises(ConnectionError, match="Connection not active and reconnect disabled"):
            await connection_utils.ensure_connection(
                mock_connection, mock_client_config, host="h", port=1, reconnect=False
            )

    async def test_create_multiple_connections_all_succeed(
        self, mock_client_config: ClientConfig, mock_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        targets = [("h1", 1), ("h2", 2)]
        mocker.patch.object(WebTransportConnection, "create_client", return_value=mock_connection)

        connections = await connection_utils.create_multiple_connections(config=mock_client_config, targets=targets)

        assert len(connections) == 2
        assert "h1:1" in connections
        assert "h2:2" in connections
        assert connections["h1:1"] is mock_connection

    async def test_create_multiple_connections_some_fail(
        self, mock_client_config: ClientConfig, mock_connection: WebTransportConnection, mocker: MockerFixture
    ) -> None:
        targets = [("h1", 1), ("h2", 2)]
        mocker.patch.object(
            WebTransportConnection, "create_client", side_effect=[mock_connection, ConnectionError("failed")]
        )

        connections = await connection_utils.create_multiple_connections(config=mock_client_config, targets=targets)

        assert len(connections) == 1
        assert "h1:1" in connections
        assert "h2:2" not in connections

    async def test_test_tcp_connection_success(self, mocker: MockerFixture) -> None:
        mock_reader = mocker.create_autospec(asyncio.StreamReader, instance=True)
        mock_writer = mocker.create_autospec(asyncio.StreamWriter, instance=True)
        mock_writer.close = mocker.MagicMock()
        mock_writer.wait_closed = mocker.AsyncMock()
        mock_open = mocker.patch("asyncio.open_connection", return_value=(mock_reader, mock_writer))

        result = await connection_utils.test_tcp_connection(host="h", port=1)

        assert result is True
        mock_open.assert_awaited_once_with("h", 1)
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()

    @pytest.mark.parametrize("error", [asyncio.TimeoutError, OSError])
    async def test_test_tcp_connection_failure(self, mocker: MockerFixture, error: Exception) -> None:
        mocker.patch("asyncio.open_connection", side_effect=error)

        result = await connection_utils.test_tcp_connection(host="h", port=1)

        assert result is False

    async def test_test_multiple_connections(self, mocker: MockerFixture) -> None:
        targets = [("h1", 1), ("h2", 2), ("h3", 3)]
        mock_test_tcp = mocker.patch(
            "pywebtransport.connection.utils.test_tcp_connection", side_effect=[True, False, True]
        )

        results = await connection_utils.test_multiple_connections(targets=targets)

        assert results == {"h1:1": True, "h2:2": False, "h3:3": True}
        assert mock_test_tcp.await_count == 3
