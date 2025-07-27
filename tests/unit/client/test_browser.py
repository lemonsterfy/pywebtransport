"""Unit tests for the pywebtransport.client.browser module."""

import asyncio
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ConnectionError, WebTransportClient, WebTransportSession
from pywebtransport.client import WebTransportBrowser


class TestWebTransportBrowser:
    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        return mocker.MagicMock(spec=ClientConfig)

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.__aenter__.return_value = client
        return client

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_closed = False
        return session

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mocker.patch(
            "pywebtransport.client.browser.WebTransportClient.create",
            return_value=mock_underlying_client,
        )
        mocker.patch("asyncio.Lock", return_value=mocker.AsyncMock())

    def test_create_factory(self, mocker: MockerFixture) -> None:
        mock_init = mocker.patch("pywebtransport.client.browser.WebTransportBrowser.__init__", return_value=None)
        mock_config = mocker.MagicMock(spec=ClientConfig)

        WebTransportBrowser.create(config=mock_config)

        mock_init.assert_called_once_with(config=mock_config)

    def test_current_session_property(self, mock_session: Any) -> None:
        browser = WebTransportBrowser()
        assert browser.current_session is None

        browser._current_session = mock_session
        assert browser.current_session is mock_session

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, mock_underlying_client: Any) -> None:
        browser = WebTransportBrowser()

        async with browser as returned_browser:
            assert returned_browser is browser
            mock_underlying_client.__aenter__.assert_awaited_once()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close(self, mock_underlying_client: Any, mock_session: Any) -> None:
        browser = WebTransportBrowser()
        browser._current_session = mock_session
        browser._history = ["http://a.com"]
        browser._history_index = 0

        await browser.close()

        mock_session.close.assert_awaited_once()
        mock_underlying_client.close.assert_awaited_once()
        assert browser._current_session is None
        assert not browser._history
        assert browser._history_index == -1

    @pytest.mark.asyncio
    async def test_close_with_no_session(self, mock_underlying_client: Any) -> None:
        browser = WebTransportBrowser()

        await browser.close()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_navigate_first_time(self, mock_underlying_client: Any, mock_session: Any) -> None:
        mock_underlying_client.connect.return_value = mock_session
        browser = WebTransportBrowser()

        session = await browser.navigate("https://a.com")

        assert session is mock_session
        assert browser.current_session is mock_session
        assert await browser.get_history() == ["https://a.com"]
        assert browser._history_index == 0
        mock_underlying_client.connect.assert_awaited_once_with("https://a.com")

    @pytest.mark.asyncio
    async def test_navigate_to_same_url(self, mock_underlying_client: Any, mock_session: Any) -> None:
        mock_underlying_client.connect.return_value = mock_session
        browser = WebTransportBrowser()
        browser._history = ["https://a.com"]
        browser._history_index = 0

        await browser.navigate("https://a.com")

        assert await browser.get_history() == ["https://a.com"]
        assert browser._history_index == 0

    @pytest.mark.asyncio
    async def test_navigate_forward_history_truncation(self, mock_underlying_client: Any, mock_session: Any) -> None:
        mock_underlying_client.connect.return_value = mock_session
        browser = WebTransportBrowser()
        browser._history = ["https://a.com", "https://b.com", "https://c.com"]
        browser._history_index = 0

        await browser.navigate("https://d.com")

        assert await browser.get_history() == ["https://a.com", "https://d.com"]
        assert browser._history_index == 1

    @pytest.mark.asyncio
    async def test_navigate_failure_restores_session(self, mock_underlying_client: Any, mock_session: Any) -> None:
        mock_underlying_client.connect.side_effect = ConnectionError("Failed")
        browser = WebTransportBrowser()
        browser._current_session = mock_session

        with pytest.raises(ConnectionError):
            await browser.navigate("https://b.com")

        assert browser.current_session is mock_session

    @pytest.mark.asyncio
    async def test_navigate_internal_closes_old_session(
        self, mocker: MockerFixture, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        background_tasks = []

        def capture_task(coro):
            background_tasks.append(coro)
            return mocker.MagicMock(spec=asyncio.Task)

        mocker.patch("asyncio.create_task", side_effect=capture_task)
        old_session = mocker.create_autospec(WebTransportSession, instance=True)
        old_session.is_closed = False
        mock_underlying_client.connect.return_value = mock_session
        browser = WebTransportBrowser()
        browser._current_session = old_session

        await browser._navigate_internal("https://a.com")

        old_session.close.assert_called_once()
        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)

    @pytest.mark.asyncio
    async def test_back_and_forward(self, mock_underlying_client: Any, mock_session: Any) -> None:
        mock_underlying_client.connect.return_value = mock_session
        browser = WebTransportBrowser()
        browser._history = ["https://a.com", "https://b.com"]
        browser._history_index = 1

        session_a = await browser.back()
        assert session_a is mock_session
        assert browser._history_index == 0
        mock_underlying_client.connect.assert_awaited_with("https://a.com")

        session_b = await browser.forward()
        assert session_b is mock_session
        assert browser._history_index == 1
        mock_underlying_client.connect.assert_awaited_with("https://b.com")

    @pytest.mark.asyncio
    async def test_back_and_forward_boundaries(self, mock_underlying_client: Any) -> None:
        browser = WebTransportBrowser()
        browser._history = ["https://a.com"]
        browser._history_index = 0

        assert await browser.back() is None
        assert await browser.forward() is None
        mock_underlying_client.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refresh(self, mock_underlying_client: Any, mock_session: Any) -> None:
        mock_underlying_client.connect.return_value = mock_session
        browser = WebTransportBrowser()
        browser._history = ["https://a.com"]
        browser._history_index = 0

        session = await browser.refresh()

        assert session is mock_session
        mock_underlying_client.connect.assert_awaited_once_with("https://a.com")

    @pytest.mark.asyncio
    async def test_refresh_with_no_history(self, mock_underlying_client: Any) -> None:
        browser = WebTransportBrowser()

        assert await browser.refresh() is None
        mock_underlying_client.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_history(self) -> None:
        browser = WebTransportBrowser()
        browser._history = ["a", "b"]

        history_copy = await browser.get_history()

        assert history_copy == ["a", "b"]
        assert history_copy is not browser._history
