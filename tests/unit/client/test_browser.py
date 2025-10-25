"""Unit tests for the pywebtransport.client.browser module."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, cast

import pytest
from _pytest.logging import LogCaptureFixture
from pytest_asyncio import fixture as asyncio_fixture
from pytest_mock import MockerFixture

from pywebtransport import ClientError, ConnectionError, WebTransportClient, WebTransportSession
from pywebtransport.client import WebTransportBrowser


class TestWebTransportBrowser:
    @asyncio_fixture
    async def browser(self, browser_unactivated: WebTransportBrowser) -> AsyncGenerator[WebTransportBrowser, None]:
        async with browser_unactivated as activated_browser:
            yield activated_browser

    @pytest.fixture
    def browser_unactivated(self, mock_underlying_client: Any) -> WebTransportBrowser:
        return WebTransportBrowser(client=mock_underlying_client)

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        session.is_closed = False
        session.close = mocker.AsyncMock()
        return session

    @pytest.fixture
    def mock_underlying_client(self, mocker: MockerFixture, mock_session: Any) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.connect = mocker.AsyncMock(return_value=mock_session)
        return client

    @pytest.mark.asyncio
    async def test_aenter_and_aexit(self, browser_unactivated: WebTransportBrowser) -> None:
        assert browser_unactivated._lock is None

        async with browser_unactivated as returned_browser:
            assert returned_browser is browser_unactivated
            assert isinstance(browser_unactivated._lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_aexit_handles_exceptions(
        self, browser_unactivated: WebTransportBrowser, mocker: MockerFixture
    ) -> None:
        close_spy = mocker.spy(browser_unactivated, "close")
        with pytest.raises(ValueError, match="Test exception"):
            async with browser_unactivated:
                raise ValueError("Test exception")

        close_spy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_back_and_forward(
        self,
        browser: WebTransportBrowser,
        mock_underlying_client: Any,
        mock_session: Any,
    ) -> None:
        browser._history = ["https://a.com", "https://b.com"]
        browser._history_index = 1
        browser._current_session = mock_session

        session_a = await browser.back()

        assert session_a is mock_session
        assert browser._history_index == 0
        cast(Any, mock_underlying_client.connect).assert_awaited_with(url="https://a.com")

        session_b = await browser.forward()

        assert session_b is mock_session
        assert browser._history_index == 1
        cast(Any, mock_underlying_client.connect).assert_awaited_with(url="https://b.com")

    @pytest.mark.asyncio
    async def test_back_and_forward_boundaries(self, browser: WebTransportBrowser, mock_underlying_client: Any) -> None:
        browser._history = ["https://a.com"]
        browser._history_index = 0

        assert await browser.back() is None
        assert await browser.forward() is None
        cast(Any, mock_underlying_client.connect).assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("session_is_closed", [True, False])
    async def test_close(
        self,
        browser: WebTransportBrowser,
        mock_underlying_client: Any,
        mock_session: Any,
        session_is_closed: bool,
    ) -> None:
        mock_session.is_closed = session_is_closed
        browser._current_session = mock_session
        browser._history = ["http://a.com"]
        browser._history_index = 0

        await browser.close()

        if session_is_closed:
            mock_session.close.assert_not_awaited()
        else:
            mock_session.close.assert_awaited_once()

        assert browser._current_session is None
        assert not browser._history
        assert browser._history_index == -1
        cast(Any, mock_underlying_client.close).assert_not_awaited()

    def test_current_session_property(self, browser_unactivated: WebTransportBrowser, mock_session: Any) -> None:
        assert browser_unactivated.current_session is None
        browser_unactivated._current_session = mock_session
        assert browser_unactivated.current_session is mock_session

    @pytest.mark.asyncio
    async def test_get_history(self, browser: WebTransportBrowser) -> None:
        browser._history = ["a", "b"]

        history_copy = await browser.get_history()

        assert history_copy == ["a", "b"]
        assert history_copy is not browser._history

    def test_init(self, mock_underlying_client: Any) -> None:
        browser = WebTransportBrowser(client=mock_underlying_client)
        assert browser._client is mock_underlying_client
        assert browser.current_session is None
        assert browser._lock is None

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
    async def test_methods_raise_if_not_activated(
        self,
        browser_unactivated: WebTransportBrowser,
        method_name: str,
        kwargs: dict[str, Any],
    ) -> None:
        method_to_test = getattr(browser_unactivated, method_name)

        with pytest.raises(ClientError, match="WebTransportBrowser has not been activated"):
            await method_to_test(**kwargs)

    @pytest.mark.asyncio
    async def test_navigate_failure_restores_session(
        self,
        browser: WebTransportBrowser,
        mock_underlying_client: Any,
        mock_session: Any,
        mocker: MockerFixture,
        caplog: LogCaptureFixture,
    ) -> None:
        background_tasks: list[asyncio.Task[Any]] = []
        original_create_task = asyncio.create_task

        def capture_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
            task = original_create_task(coro)
            background_tasks.append(task)
            return task

        mocker.patch("asyncio.create_task", side_effect=capture_task)

        cast(Any, mock_underlying_client.connect).side_effect = ConnectionError(message="Failed")
        browser._current_session = mock_session
        url = "https://b.com"

        with pytest.raises(ConnectionError):
            await browser.navigate(url=url)

        assert browser.current_session is mock_session
        assert f"Failed to navigate to {url}" in caplog.text
        assert "Failed" in caplog.text

        if background_tasks:
            await asyncio.gather(*background_tasks)

    @pytest.mark.asyncio
    async def test_navigate_first_time(
        self,
        browser: WebTransportBrowser,
        mock_underlying_client: Any,
        mock_session: Any,
    ) -> None:
        url = "https://a.com"

        session = await browser.navigate(url=url)

        assert session is mock_session
        assert browser.current_session is mock_session
        assert await browser.get_history() == [url]
        assert browser._history_index == 0
        cast(Any, mock_underlying_client.connect).assert_awaited_once_with(url=url)

    @pytest.mark.asyncio
    async def test_navigate_forward_history_truncation(
        self,
        browser: WebTransportBrowser,
        mock_underlying_client: Any,
        mock_session: Any,
    ) -> None:
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
        self, browser: WebTransportBrowser, mocker: MockerFixture
    ) -> None:
        background_tasks: list[asyncio.Task[Any]] = []
        original_create_task = asyncio.create_task

        def capture_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
            task = original_create_task(coro)
            background_tasks.append(task)
            return task

        mocker.patch("asyncio.create_task", side_effect=capture_task)
        old_session = mocker.create_autospec(WebTransportSession, instance=True)
        old_session.is_closed = False
        old_session.close = mocker.AsyncMock()

        browser._current_session = old_session

        await browser._navigate_internal(url="https://a.com")

        assert len(background_tasks) == 1
        await asyncio.gather(*background_tasks)
        old_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_navigate_to_same_url(
        self,
        browser: WebTransportBrowser,
        mock_underlying_client: Any,
        mock_session: Any,
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
    async def test_refresh(
        self,
        browser: WebTransportBrowser,
        mock_underlying_client: Any,
        mock_session: Any,
    ) -> None:
        url = "https://a.com"
        browser._history = [url]
        browser._history_index = 0

        session = await browser.refresh()

        assert session is mock_session
        cast(Any, mock_underlying_client.connect).assert_awaited_once_with(url=url)

    @pytest.mark.asyncio
    async def test_refresh_with_no_history(self, browser: WebTransportBrowser, mock_underlying_client: Any) -> None:
        result = await browser.refresh()

        assert result is None
        cast(Any, mock_underlying_client.connect).assert_not_awaited()
