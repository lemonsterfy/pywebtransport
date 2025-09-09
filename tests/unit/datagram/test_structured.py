"""Unit tests for the pywebtransport.datagram.structured module."""

import struct
from typing import Any, Type
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import SerializationError, Serializer
from pywebtransport.datagram import StructuredDatagramStream
from pywebtransport.datagram.transport import WebTransportDatagramDuplexStream


class MockMsgA:
    pass


class MockMsgB:
    pass


@pytest.fixture
def mock_datagram_stream(mocker: MockerFixture) -> AsyncMock:
    mock = mocker.create_autospec(WebTransportDatagramDuplexStream, spec_set=True, instance=True)
    mock.receive = AsyncMock()
    mock.send = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_serializer(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(Serializer, spec_set=True, instance=True)


@pytest.fixture
def registry() -> dict[int, Type[Any]]:
    return {1: MockMsgA, 2: MockMsgB}


@pytest.fixture
def structured_stream(
    mock_datagram_stream: AsyncMock,
    mock_serializer: MagicMock,
    registry: dict[int, Type[Any]],
) -> StructuredDatagramStream:
    return StructuredDatagramStream(
        datagram_stream=mock_datagram_stream,
        serializer=mock_serializer,
        registry=registry,
    )


class TestStructuredDatagramStream:
    def test_init(
        self,
        structured_stream: StructuredDatagramStream,
        mock_datagram_stream: AsyncMock,
        mock_serializer: MagicMock,
        registry: dict[int, Type[Any]],
    ) -> None:
        expected_class_to_id = {MockMsgA: 1, MockMsgB: 2}

        assert structured_stream._datagram_stream is mock_datagram_stream
        assert structured_stream._serializer is mock_serializer
        assert structured_stream._registry is registry
        assert structured_stream._class_to_id == expected_class_to_id

    async def test_close_method(
        self,
        structured_stream: StructuredDatagramStream,
        mock_datagram_stream: AsyncMock,
    ) -> None:
        await structured_stream.close()

        mock_datagram_stream.close.assert_awaited_once()

    async def test_send_obj_successful(
        self,
        structured_stream: StructuredDatagramStream,
        mock_datagram_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        obj_to_send = MockMsgA()
        type_id = 1
        serialized_payload = b"serialized_data"
        mock_serializer.serialize.return_value = serialized_payload

        await structured_stream.send_obj(obj=obj_to_send, priority=5, ttl=10.0)

        mock_serializer.serialize.assert_called_once_with(obj=obj_to_send)
        header = struct.pack("!H", type_id)
        mock_datagram_stream.send.assert_awaited_once_with(data=header + serialized_payload, priority=5, ttl=10.0)

    async def test_receive_obj_successful(
        self,
        structured_stream: StructuredDatagramStream,
        mock_datagram_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        type_id = 2
        message_class = MockMsgB
        serialized_payload = b"serialized_data_b"
        header = struct.pack("!H", type_id)
        mock_datagram_stream.receive.return_value = header + serialized_payload
        deserialized_obj = MockMsgB()
        mock_serializer.deserialize.return_value = deserialized_obj

        result = await structured_stream.receive_obj(timeout=5.0)

        mock_datagram_stream.receive.assert_awaited_once_with(timeout=5.0)
        mock_serializer.deserialize.assert_called_once_with(data=serialized_payload, obj_type=message_class)
        assert result is deserialized_obj

    @pytest.mark.parametrize("closed_status", [True, False])
    def test_is_closed_property(
        self,
        structured_stream: StructuredDatagramStream,
        mock_datagram_stream: AsyncMock,
        closed_status: bool,
    ) -> None:
        type(mock_datagram_stream).is_closed = closed_status

        assert structured_stream.is_closed is closed_status

    async def test_send_obj_unregistered_raises_error(
        self,
        structured_stream: StructuredDatagramStream,
        mock_datagram_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        class UnregisteredMsg:
            pass

        obj_to_send = UnregisteredMsg()

        with pytest.raises(SerializationError) as exc_info:
            await structured_stream.send_obj(obj=obj_to_send)

        assert "Object of type 'UnregisteredMsg' is not registered" in str(exc_info.value)
        mock_serializer.serialize.assert_not_called()
        mock_datagram_stream.send.assert_not_awaited()

    async def test_receive_obj_unknown_type_id_raises_error(
        self,
        structured_stream: StructuredDatagramStream,
        mock_datagram_stream: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        unknown_type_id = 99
        header = struct.pack("!H", unknown_type_id)
        payload = b"some_payload"
        mock_datagram_stream.receive.return_value = header + payload

        with pytest.raises(SerializationError) as exc_info:
            await structured_stream.receive_obj()

        assert f"Received unknown message type ID: {unknown_type_id}" in str(exc_info.value)
        mock_serializer.deserialize.assert_not_called()
