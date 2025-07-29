"""Unit tests for the pywebtransport.datagram.utils module."""

import pytest
from pytest_mock import MockerFixture

from pywebtransport import WebTransportDatagramDuplexStream
from pywebtransport.datagram.utils import create_heartbeat_datagram, datagram_throughput_test, is_heartbeat_datagram


class TestDatagramUtils:
    def test_create_heartbeat_datagram(self, mocker: MockerFixture) -> None:
        mock_timestamp = 1678886400
        mocker.patch("pywebtransport.datagram.utils.get_timestamp", return_value=mock_timestamp)

        heartbeat = create_heartbeat_datagram()
        expected = f"HEARTBEAT:{mock_timestamp}".encode("utf-8")

        assert heartbeat == expected

    @pytest.mark.parametrize(
        "data, expected",
        [
            (b"HEARTBEAT:123456", True),
            (b"HEARTBEAT:", True),
            (b"NOT_HEARTBEAT:123456", False),
            (b"some other data", False),
            (b"", False),
        ],
    )
    def test_is_heartbeat_datagram(self, data: bytes, expected: bool) -> None:
        assert is_heartbeat_datagram(data) is expected

    @pytest.mark.asyncio
    async def test_datagram_throughput_test_successful_run(self, mocker: MockerFixture) -> None:
        mock_stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        mock_stream.max_datagram_size = 1200
        mock_stream.try_send = mocker.AsyncMock(return_value=True)
        mocker.patch("pywebtransport.datagram.utils.asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_time = mocker.patch("pywebtransport.datagram.utils.get_timestamp")
        start_time = 1000.0
        duration = 0.05
        mock_time.side_effect = [
            start_time,
            start_time + 0.01,
            start_time + 0.02,
            start_time + 0.03,
            start_time + 0.04,
            start_time + 0.049,
            start_time + 0.06,
            start_time + 0.06,
        ]
        expected_duration = 0.06

        results = await datagram_throughput_test(mock_stream, duration=duration, datagram_size=1000)

        assert mock_stream.try_send.call_count == 5
        assert results["datagrams_sent"] == 5
        assert results["errors"] == 0
        assert results["error_rate"] == 0.0
        assert results["duration"] == pytest.approx(expected_duration)
        expected_dps = 5 / max(1, expected_duration)
        assert results["throughput_dps"] == pytest.approx(expected_dps)
        assert results["throughput_bps"] == pytest.approx(expected_dps * 1000 * 8)

    @pytest.mark.asyncio
    async def test_datagram_throughput_test_size_exceeds_max(self, mocker: MockerFixture) -> None:
        mock_stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        mock_stream.max_datagram_size = 500

        with pytest.raises(ValueError, match="datagram_size 1000 exceeds max size 500"):
            await datagram_throughput_test(mock_stream, datagram_size=1000)

    @pytest.mark.asyncio
    async def test_datagram_throughput_test_with_backpressure(self, mocker: MockerFixture) -> None:
        mock_stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        mock_stream.max_datagram_size = 1200
        mock_stream.try_send = mocker.AsyncMock(side_effect=[True, False, True, False, True])
        mock_sleep = mocker.patch("pywebtransport.datagram.utils.asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_time = mocker.patch("pywebtransport.datagram.utils.get_timestamp")
        start_time = 1000.0
        duration = 0.05
        mock_time.side_effect = [
            start_time,
            start_time + 0.01,
            start_time + 0.02,
            start_time + 0.03,
            start_time + 0.04,
            start_time + 0.049,
            start_time + 0.06,
            start_time + 0.06,
        ]

        results = await datagram_throughput_test(mock_stream, duration=duration)

        assert mock_stream.try_send.call_count == 5
        assert results["datagrams_sent"] == 5
        assert results["errors"] == 0
        assert mock_sleep.call_args_list.count(mocker.call(0.01)) == 2
        assert mock_sleep.call_args_list.count(mocker.call(0.001)) == 5

    @pytest.mark.asyncio
    async def test_datagram_throughput_test_with_send_errors(self, mocker: MockerFixture) -> None:
        mock_stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        mock_stream.max_datagram_size = 1200
        mock_stream.try_send = mocker.AsyncMock(side_effect=[True, True, Exception("Send failed"), True, True])
        mocker.patch("pywebtransport.datagram.utils.asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_time = mocker.patch("pywebtransport.datagram.utils.get_timestamp")
        start_time = 1000.0
        duration = 0.05
        mock_time.side_effect = [
            start_time,
            start_time + 0.01,
            start_time + 0.02,
            start_time + 0.03,
            start_time + 0.04,
            start_time + 0.049,
            start_time + 0.06,
            start_time + 0.06,
        ]

        results = await datagram_throughput_test(mock_stream, duration=duration)

        assert mock_stream.try_send.call_count == 5
        assert results["datagrams_sent"] == 4
        assert results["errors"] == 1
        assert results["error_rate"] == 1 / 5

    @pytest.mark.asyncio
    async def test_datagram_throughput_test_zero_duration(self, mocker: MockerFixture) -> None:
        mock_stream = mocker.create_autospec(WebTransportDatagramDuplexStream, instance=True)
        mock_stream.max_datagram_size = 1200
        mock_stream.try_send = mocker.AsyncMock(return_value=True)
        mocker.patch("pywebtransport.datagram.utils.asyncio.sleep", new_callable=mocker.AsyncMock)
        mock_time = mocker.patch("pywebtransport.datagram.utils.get_timestamp")
        start_time = 1000.0
        mock_time.side_effect = [start_time, start_time + 0.1, start_time + 0.1]

        results = await datagram_throughput_test(mock_stream, duration=0)

        assert results["datagrams_sent"] == 0
        assert results["errors"] == 0
        assert results["duration"] == pytest.approx(0.1)
        assert results["throughput_dps"] == 0
        assert results["throughput_bps"] == 0
