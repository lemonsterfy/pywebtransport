"""Unit tests for the pywebtransport.client.browser module."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, cast

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import ClientConfig, ClientError, ConnectionError, WebTransportClient, WebTransportSession
from pywebtransport.client import WebTransportBrowser


class TestWebTransportBrowser:
    @asyncio_fixture
    async def browser(self) -> AsyncGenerator[WebTransportBrowser, None]:
        browser_instance = WebTransportBrowser()
        async with browser_instance as activated_browser:
            yield activated_browser

    @pytest.fixture
    def mock_client_config(self, mocker: MockerFixture) -> Any:
        return mocker.MagicMock(spec=ClientConfig)

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_closed = False
        return session

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.__aenter__.return_value = client
        client.close = mocker.AsyncMock()
        client.connect = mocker.AsyncMock()
        return client

    @pytest.fixture(autouse=True)
    def setup_common_mocks(self, mocker: MockerFixture, mock_underlying_client: Any) -> None:
        mocker.patch(
            "pywebtransport.client.browser.WebTransportClient",
            return_value=mock_underlying_client,
        )

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
    async def test_close(self, browser: WebTransportBrowser, mock_underlying_client: Any, mock_session: Any) -> None:
        browser._current_session = mock_session
        browser._history = ["http://a.com"]
        browser._history_index = 0

        await browser.close()

        cast(Any, mock_session.close).assert_awaited_once()
        mock_underlying_client.close.assert_awaited_once()
        assert browser._current_session is None
        assert not browser._history
        assert browser._history_index == -1

    @pytest.mark.asyncio
    async def test_close_with_no_session(self, browser: WebTransportBrowser, mock_underlying_client: Any) -> None:
        await browser.close()

        mock_underlying_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_navigate_first_time(
        self, browser: WebTransportBrowser, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        cast(Any, mock_underlying_client.connect).return_value = mock_session
        url = "https://a.com"

        session = await browser.navigate(url=url)

        assert session is mock_session
        assert browser.current_session is mock_session
        assert await browser.get_history() == [url]
        assert browser._history_index == 0
        cast(Any, mock_underlying_client.connect).assert_awaited_once_with(url=url)

    @pytest.mark.asyncio
    async def test_navigate_to_same_url(
        self, browser: WebTransportBrowser, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        url = "https://a.com"
        browser._current_session = mock_session
        browser._history = [url]
        browser._history_index = 0

        session = await browser.navigate(url=url)

        assert session is mock_session
        assert await browser.get_history() == [url]
        assert browser._history_index == 0
        cast(Any, mock_underlying_client.connect).assert_not_called()

    @pytest.mark.asyncio
    async def test_navigate_forward_history_truncation(
        self, browser: WebTransportBrowser, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        cast(Any, mock_underlying_client.connect).return_value = mock_session
        browser._history = ["https://a.com", "https://b.com", "https://c.com"]
        browser._history_index = 0

        await browser.navigate(url="https://d.com")

        assert await browser.get_history() == ["https://a.com", "https://d.com"]
        assert browser._history_index == 1

        await browser.navigate(url="https://d.com")
        assert await browser.get_history() == ["https://a.com", "https://d.com"]
        assert browser._history_index == 1

    @pytest.mark.asyncio
    async def test_navigate_internal_closes_old_session(
        self,
        browser: WebTransportBrowser,
        mocker: MockerFixture,
        mock_underlying_client: Any,
        mock_session: Any,
    ) -> None:
        background_tasks = []

        def capture_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
            background_tasks.append(coro)
            return cast(asyncio.Task[Any], mocker.MagicMock(spec=asyncio.Task))

        mocker.patch("asyncio.create_task", side_effect=capture_task)
        old_session = mocker.create_autospec(WebTransportSession, instance=True)
        old_session.is_closed = False
        cast(Any, mock_underlying_client.connect).return_value = mock_session
        browser._current_session = old_session

        await browser._navigate_internal(url="https://a.com")

        cast(Any, old_session.close).assert_called_once()
        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)

    @pytest.mark.asyncio
    async def test_back_and_forward(
        self, browser: WebTransportBrowser, mock_underlying_client: Any, mock_session: Any
    ) -> None:
        cast(Any, mock_underlying_client.connect).return_value = mock_session
        browser._history = ["https://a.com", "https://b.com"]
        browser._history_index = 1

        session_a = await browser.back()

        assert session_a is mock_session
        assert browser._history_index == 0
        cast(Any, mock_underlying_client.connect).assert_awaited_with(url="https://a.com")

        session_b = await browser.forward()

        assert session_b is mock_session
        assert browser._history_index == 1
        cast(Any, mock_underlying_client.connect).assert_awaited_with(url="https://b.com")

    @pytest.mark.asyncio
    async def test_refresh(self, browser: WebTransportBrowser, mock_underlying_client: Any, mock_session: Any) -> None:
        cast(Any, mock_underlying_client.connect).return_value = mock_session
        url = "https://a.com"
        browser._history = [url]
        browser._history_index = 0

        session = await browser.refresh()

        assert session is mock_session
        cast(Any, mock_underlying_client.connect).assert_awaited_once_with(url=url)

    @pytest.mark.asyncio
    async def test_get_history(self, browser: WebTransportBrowser) -> None:
        browser._history = ["a", "b"]

        history_copy = await browser.get_history()

        assert history_copy == ["a", "b"]
        assert history_copy is not browser._history

    @pytest.mark.asyncio
    async def test_aexit_handles_exceptions(self, mock_underlying_client: Any) -> None:
        browser = WebTransportBrowser()

        with pytest.raises(ValueError, match="Test exception"):
            async with browser:
                raise ValueError("Test exception")

        cast(Any, mock_underlying_client.close).assert_awaited_once()

    @pytest.mark.asyncio
    async def test_navigate_failure_restores_session(
        self, browser: WebTransportBrowser, mock_underlying_client: Any, mock_session: Any, caplog: LogCaptureFixture
    ) -> None:
        cast(Any, mock_underlying_client.connect).side_effect = ConnectionError(message="Failed")
        browser._current_session = mock_session
        url = "https://b.com"

        with pytest.raises(ConnectionError):
            await browser.navigate(url=url)

        assert browser.current_session is mock_session
        assert f"Failed to navigate to {url}" in caplog.text
        assert "Failed" in caplog.text

    @pytest.mark.asyncio
    async def test_back_and_forward_boundaries(self, browser: WebTransportBrowser, mock_underlying_client: Any) -> None:
        browser._history = ["https://a.com"]
        browser._history_index = 0

        assert await browser.back() is None
        assert await browser.forward() is None
        cast(Any, mock_underlying_client.connect).assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refresh_with_no_history(self, browser: WebTransportBrowser, mock_underlying_client: Any) -> None:
        result = await browser.refresh()

        assert result is None
        cast(Any, mock_underlying_client.connect).assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name, kwargs",
        [
            ("close", {}),
            ("back", {}),
            ("forward", {}),
            ("navigate", {"url": "https://example.com"}),
            ("refresh", {}),
            ("get_history", {}),
        ],
    )
    async def test_methods_raise_if_not_activated(self, method_name: str, kwargs: dict[str, Any]) -> None:
        browser = WebTransportBrowser()
        method_to_test = getattr(browser, method_name)

        with pytest.raises(ClientError, match="WebTransportBrowser has not been activated"):
            await method_to_test(**kwargs)
