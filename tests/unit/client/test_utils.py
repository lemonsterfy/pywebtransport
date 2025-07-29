"""Unit tests for the pywebtransport.client.utils module."""

from typing import Any, Awaitable, NoReturn, Union, cast

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConnectionError, WebTransportClient, WebTransportSession, WebTransportStream
from pywebtransport.client import utils as client_utils


@pytest.mark.asyncio
class TestClientUtils:
    URL = "https://example.com"

    @pytest.fixture
    def mock_client(self, mocker: MockerFixture) -> Any:
        client = mocker.create_autospec(WebTransportClient, instance=True)
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.stats = {"connections": 1}
        return client

    @pytest.fixture
    def mock_session(self, mocker: MockerFixture) -> Any:
        session = mocker.create_autospec(WebTransportSession, instance=True)
        return session

    @pytest.fixture
    def mock_stream(self, mocker: MockerFixture) -> Any:
        stream = mocker.create_autospec(WebTransportStream, instance=True)
        return stream

    @pytest.fixture(autouse=True)
    def setup_mocks(self, mocker: MockerFixture, mock_client: Any) -> None:
        mocker.patch(
            "pywebtransport.client.utils.WebTransportClient.create",
            return_value=mock_client,
        )

    async def test_benchmark_all_success(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock, return_value=[0.1, 0.2, 0.3])

        results = await client_utils.benchmark_client_performance(self.URL, num_requests=3)

        assert results["total_requests"] == 3
        assert results["successful_requests"] == 3
        assert results["failed_requests"] == 0
        assert results["avg_latency"] == pytest.approx(0.2)
        assert results["min_latency"] == 0.1
        assert results["max_latency"] == 0.3

    async def test_benchmark_partial_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock, return_value=[0.2, None, 0.4])

        results = await client_utils.benchmark_client_performance(self.URL, num_requests=3)

        assert results["successful_requests"] == 2
        assert results["failed_requests"] == 1
        assert results["avg_latency"] == pytest.approx(0.3)
        assert results["min_latency"] == pytest.approx(0.2)
        assert results["max_latency"] == pytest.approx(0.4)

    async def test_benchmark_all_fail(self, mocker: MockerFixture) -> None:
        mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock, return_value=[None, None])

        results = await client_utils.benchmark_client_performance(self.URL, num_requests=2)

        assert results["successful_requests"] == 0
        assert results["failed_requests"] == 2
        assert "avg_latency" not in results

    async def test_benchmark_zero_requests(self, mocker: MockerFixture) -> None:
        mock_gather = mocker.patch("asyncio.gather", new_callable=mocker.AsyncMock)

        results = await client_utils.benchmark_client_performance(self.URL, num_requests=0)

        mock_gather.assert_awaited_once_with()
        assert results["total_requests"] == 0
        assert results["successful_requests"] == 0
        assert results["failed_requests"] == 0
        assert not results["latencies"]

    async def test_benchmark_inner_logic_success(
        self, mocker: MockerFixture, mock_client: Any, mock_session: Any, mock_stream: Any
    ) -> None:
        mocker.patch("pywebtransport.client.utils.get_timestamp", side_effect=[100.0, 101.5])
        mock_client.connect.return_value = mock_session
        mock_session.create_bidirectional_stream.return_value = mock_stream

        results = await client_utils.benchmark_client_performance(self.URL, num_requests=1)

        mock_client.connect.assert_awaited_once_with(self.URL)
        mock_session.create_bidirectional_stream.assert_awaited_once()
        mock_stream.write.assert_awaited_once_with(b"benchmark_ping")
        mock_stream.read.assert_awaited_once_with(size=1024)
        mock_session.close.assert_awaited_once()
        assert results["successful_requests"] == 1
        assert results["failed_requests"] == 0
        assert results["latencies"] == [pytest.approx(1.5)]

    async def test_benchmark_inner_logic_failure(self, mocker: MockerFixture, mock_client: Any) -> None:
        mock_client.connect.side_effect = IOError("Connection failed")
        mock_logger = mocker.patch("pywebtransport.client.utils.logger.warning")

        results = await client_utils.benchmark_client_performance(self.URL, num_requests=1)

        assert results["successful_requests"] == 0
        assert results["failed_requests"] == 1
        assert not results["latencies"]
        mock_logger.assert_called_once_with("Benchmark request failed: Connection failed")

    async def test_connectivity_success(self, mocker: MockerFixture, mock_client: Any, mock_session: Any) -> None:
        mocker.patch("pywebtransport.client.utils.get_timestamp", side_effect=[1000.0, 1001.5])

        async def wait_for_side_effect(coro: Awaitable[Any], timeout: Union[float, None]) -> WebTransportSession:
            await coro
            return cast(WebTransportSession, mock_session)

        mocker.patch("asyncio.wait_for", side_effect=wait_for_side_effect)

        results = await client_utils.test_client_connectivity(self.URL)

        assert results["success"] is True
        assert results["connect_time"] == pytest.approx(1.5)
        assert results["client_stats"] == mock_client.stats
        mock_session.close.assert_awaited_once()

    async def test_connectivity_failure(self, mocker: MockerFixture, mock_client: Any) -> None:
        mocker.patch("pywebtransport.client.utils.get_timestamp")

        async def wait_for_side_effect(coro: Awaitable[Any], timeout: Union[float, None]) -> NoReturn:
            await coro
            raise ConnectionError("Failed to connect")

        mocker.patch("asyncio.wait_for", side_effect=wait_for_side_effect)

        results = await client_utils.test_client_connectivity(self.URL)

        assert results["success"] is False
        assert "Failed to connect" in results["error"]
        assert results["connect_time"] is None
        assert results["client_stats"] == mock_client.stats
