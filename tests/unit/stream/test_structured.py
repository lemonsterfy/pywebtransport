"""Unit tests for the pywebtransport.stream.structured module."""

import asyncio
import struct
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import SerializationError, Serializer, StreamError
from pywebtransport.stream import StructuredStream
from pywebtransport.stream.stream import WebTransportStream


class MockMsgA:
    pass


class MockMsgB:
    pass


@pytest.fixture
def mock_stream(mocker: MockerFixture) -> AsyncMock:
    mock = mocker.create_autospec(WebTransportStream, spec_set=True, instance=True)
    mock.readexactly = AsyncMock()
    mock.write = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_serializer(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(Serializer, spec_set=True, instance=True)


@pytest.fixture
def registry() -> dict[int, type[Any]]:
    return {1: MockMsgA, 2: MockMsgB}


@pytest.fixture
def structured_stream(
    mock_stream: AsyncMock,
    mock_serializer: MagicMock,
    registry: dict[int, type[Any]],
) -> StructuredStream:
    return StructuredStream(
        stream=mock_stream,
        serializer=mock_serializer,
        registry=registry,
    )


class TestStructuredStream:
    def test_init(
        self,
        structured_stream: StructuredStream,
        mock_stream: AsyncMock,
        mock_serializer: MagicMock,
        registry: dict[int, type[Any]],
    ) -> None:
        expected_class_to_id = {MockMsgA: 1, MockMsgB: 2}

        assert structured_stream._stream is mock_stream
        assert structured_stream._serializer is mock_serializer
        assert structured_stream._registry is registry
        assert structured_stream._class_to_id == expected_class_to_id

    def test_stream_id_property(self, structured_stream: StructuredStream, mock_stream: AsyncMock) -> None:
        expected_id = 123
        type(mock_stream).stream_id = expected_id

        assert structured_stream.stream_id == expected_id

    @pytest.mark.asyncio
    async def test_close_method(self, structured_stream: StructuredStream, mock_stream: AsyncMock) -> None:
        await structured_stream.close()

        mock_stream.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_obj_successful(
        self,
        structured_stream: StructuredStream,
        mock_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        obj_to_send = MockMsgB()
        type_id = 2
        serialized_payload = b"some_serialized_data"
        mock_serializer.serialize.return_value = serialized_payload

        await structured_stream.send_obj(obj=obj_to_send)

        mock_serializer.serialize.assert_called_once_with(obj=obj_to_send)
        header = struct.pack("!HI", type_id, len(serialized_payload))
        mock_stream.write.assert_awaited_once_with(data=header + serialized_payload)

    @pytest.mark.asyncio
    async def test_receive_obj_successful(
        self,
        structured_stream: StructuredStream,
        mock_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        type_id = 1
        message_class = MockMsgA
        payload = b"payload_data"
        header = struct.pack("!HI", type_id, len(payload))
        mock_stream.readexactly.side_effect = [header, payload]
        deserialized_obj = MockMsgA()
        mock_serializer.deserialize.return_value = deserialized_obj

        result = await structured_stream.receive_obj()

        assert mock_stream.readexactly.await_count == 2
        mock_stream.readexactly.assert_any_await(n=struct.calcsize("!HI"))
        mock_stream.readexactly.assert_any_await(n=len(payload))
        mock_serializer.deserialize.assert_called_once_with(data=payload, obj_type=message_class)
        assert result is deserialized_obj

    @pytest.mark.asyncio
    async def test_async_iteration(
        self,
        structured_stream: StructuredStream,
        mocker: MockerFixture,
    ) -> None:
        obj1, obj2 = MockMsgA(), MockMsgB()
        receive_obj_mock = AsyncMock(side_effect=[obj1, obj2, StreamError(message="Stream closed")])
        mocker.patch.object(structured_stream, "receive_obj", new=receive_obj_mock)
        received_objs = []

        async for obj in structured_stream:
            received_objs.append(obj)

        assert received_objs == [obj1, obj2]
        assert receive_obj_mock.await_count == 3

    @pytest.mark.parametrize("closed_status", [True, False])
    def test_is_closed_property(
        self,
        structured_stream: StructuredStream,
        mock_stream: AsyncMock,
        closed_status: bool,
    ) -> None:
        type(mock_stream).is_closed = closed_status

        assert structured_stream.is_closed is closed_status

    @pytest.mark.asyncio
    async def test_anext_stops_on_stream_error(
        self, structured_stream: StructuredStream, mocker: MockerFixture
    ) -> None:
        mocker.patch.object(
            structured_stream,
            "receive_obj",
            side_effect=StreamError(message="Done"),
        )

        with pytest.raises(StopAsyncIteration):
            await structured_stream.__anext__()

    @pytest.mark.asyncio
    async def test_send_obj_unregistered_raises_error(
        self,
        structured_stream: StructuredStream,
        mock_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        class UnregisteredMsg:
            pass

        with pytest.raises(SerializationError):
            await structured_stream.send_obj(obj=UnregisteredMsg())

        mock_serializer.serialize.assert_not_called()
        mock_stream.write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_receive_obj_incomplete_header_raises_stream_error(
        self, structured_stream: StructuredStream, mock_stream: AsyncMock
    ) -> None:
        mock_stream.readexactly.side_effect = asyncio.IncompleteReadError(b"partial", 8)

        with pytest.raises(StreamError, match="Stream closed while waiting for message header."):
            await structured_stream.receive_obj()

    @pytest.mark.asyncio
    async def test_receive_obj_incomplete_payload_raises_stream_error(
        self, structured_stream: StructuredStream, mock_stream: AsyncMock
    ) -> None:
        type_id = 1
        payload_len = 100
        header = struct.pack("!HI", type_id, payload_len)
        mock_stream.readexactly.side_effect = [
            header,
            asyncio.IncompleteReadError(b"partial", payload_len),
        ]

        with pytest.raises(StreamError, match=f"Stream closed prematurely while reading payload of size {payload_len}"):
            await structured_stream.receive_obj()

    @pytest.mark.asyncio
    async def test_receive_obj_unknown_type_id_raises_error(
        self,
        structured_stream: StructuredStream,
        mock_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        unknown_type_id = 99
        header = struct.pack("!HI", unknown_type_id, 10)
        mock_stream.readexactly.return_value = header

        with pytest.raises(SerializationError, match=f"Received unknown message type ID: {unknown_type_id}"):
            await structured_stream.receive_obj()

        mock_stream.readexactly.assert_awaited_once()
        mock_serializer.deserialize.assert_not_called()
