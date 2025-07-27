"""Unit tests for the pywebtransport.stream.utils module."""

from typing import Any, List, Optional

import pytest
from pytest_mock import MockerFixture

from pywebtransport import StreamError, WebTransportReceiveStream, WebTransportSendStream, WebTransportStream
from pywebtransport.stream.utils import copy_stream_data, echo_stream


class AsyncIterator:
    def __init__(self, items: List[bytes], exception: Optional[Exception] = None):
        self._items = iter(items)
        self._exception = exception

    def __aiter__(self) -> "AsyncIterator":
        return self

    async def __anext__(self) -> bytes:
        if self._exception:
            raise self._exception
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def mock_bidirectional_stream(mocker: MockerFixture) -> Any:
    stream = mocker.create_autospec(WebTransportStream, instance=True)
    stream.read_iter = mocker.MagicMock(return_value=AsyncIterator([]))
    stream.write = mocker.AsyncMock()
    stream.close = mocker.AsyncMock()
    stream.abort = mocker.AsyncMock()
    return stream


@pytest.fixture
def mock_destination_stream(mocker: MockerFixture) -> Any:
    stream = mocker.create_autospec(WebTransportSendStream, instance=True)
    stream.write = mocker.AsyncMock()
    stream.close = mocker.AsyncMock()
    stream.abort = mocker.AsyncMock()
    return stream


@pytest.fixture
def mock_source_stream(mocker: MockerFixture) -> Any:
    stream = mocker.create_autospec(WebTransportReceiveStream, instance=True)
    stream.read_iter = mocker.MagicMock(return_value=AsyncIterator([]))
    return stream


class TestCopyStreamData:
    @pytest.mark.parametrize(
        "chunks",
        [
            [],
            [b"hello"],
            [b"chunk1", b"chunk2", b"another chunk"],
        ],
        ids=["empty_stream", "single_chunk", "multiple_chunks"],
    )
    async def test_copy_success(
        self,
        mock_source_stream: Any,
        mock_destination_stream: Any,
        chunks: List[bytes],
    ) -> None:
        mock_source_stream.read_iter.return_value = AsyncIterator(chunks)
        expected_bytes = sum(len(c) for c in chunks)

        total_bytes = await copy_stream_data(source=mock_source_stream, destination=mock_destination_stream)

        assert total_bytes == expected_bytes
        assert mock_destination_stream.write.await_count == len(chunks)
        for i, chunk in enumerate(chunks):
            assert mock_destination_stream.write.await_args_list[i].args == (chunk,)
        mock_destination_stream.close.assert_awaited_once()
        mock_destination_stream.abort.assert_not_awaited()

    async def test_copy_source_error(
        self,
        mocker: MockerFixture,
        mock_source_stream: Any,
        mock_destination_stream: Any,
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.utils.logger")
        read_error = StreamError("Read failed")
        mock_source_stream.read_iter.return_value = AsyncIterator([], exception=read_error)

        with pytest.raises(StreamError, match="Read failed"):
            await copy_stream_data(source=mock_source_stream, destination=mock_destination_stream)

        mock_logger.error.assert_called_once_with(f"Error copying stream data: {read_error}")
        mock_destination_stream.abort.assert_awaited_once_with(code=1)
        mock_destination_stream.close.assert_not_awaited()

    async def test_copy_destination_error(
        self,
        mocker: MockerFixture,
        mock_source_stream: Any,
        mock_destination_stream: Any,
    ) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.utils.logger")
        mock_source_stream.read_iter.return_value = AsyncIterator([b"data"])
        write_error = StreamError("Write failed")
        mock_destination_stream.write.side_effect = write_error

        with pytest.raises(StreamError, match="Write failed"):
            await copy_stream_data(source=mock_source_stream, destination=mock_destination_stream)

        mock_logger.error.assert_called_once_with(f"Error copying stream data: {write_error}")
        mock_destination_stream.abort.assert_awaited_once_with(code=1)
        mock_destination_stream.close.assert_not_awaited()


class TestEchoStream:
    @pytest.mark.parametrize(
        "chunks",
        [
            [],
            [b"data"],
            [b"echo1", b"echo2"],
        ],
        ids=["empty_stream", "single_chunk", "multiple_chunks"],
    )
    async def test_echo_success(self, mock_bidirectional_stream: Any, chunks: List[bytes]) -> None:
        mock_bidirectional_stream.read_iter.return_value = AsyncIterator(chunks)

        await echo_stream(stream=mock_bidirectional_stream)

        assert mock_bidirectional_stream.write.await_count == len(chunks)
        for i, chunk in enumerate(chunks):
            assert mock_bidirectional_stream.write.await_args_list[i].args == (chunk,)
        mock_bidirectional_stream.close.assert_awaited_once()
        mock_bidirectional_stream.abort.assert_not_awaited()

    async def test_echo_read_error(self, mocker: MockerFixture, mock_bidirectional_stream: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.utils.logger")
        read_error = StreamError("Read failed")
        mock_bidirectional_stream.read_iter.return_value = AsyncIterator([], exception=read_error)

        await echo_stream(stream=mock_bidirectional_stream)

        mock_logger.error.assert_called_once_with(f"Error in echo stream: {read_error}")
        mock_bidirectional_stream.abort.assert_awaited_once_with(code=1)
        mock_bidirectional_stream.close.assert_not_awaited()

    async def test_echo_write_error(self, mocker: MockerFixture, mock_bidirectional_stream: Any) -> None:
        mock_logger = mocker.patch("pywebtransport.stream.utils.logger")
        mock_bidirectional_stream.read_iter.return_value = AsyncIterator([b"data"])
        write_error = StreamError("Write failed")
        mock_bidirectional_stream.write.side_effect = write_error

        await echo_stream(stream=mock_bidirectional_stream)

        mock_logger.error.assert_called_once_with(f"Error in echo stream: {write_error}")
        mock_bidirectional_stream.abort.assert_awaited_once_with(code=1)
        mock_bidirectional_stream.close.assert_not_awaited()
