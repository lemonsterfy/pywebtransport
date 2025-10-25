"""Unit tests for the pywebtransport.datagram.structured module."""

import struct
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConfigurationError, Serializer, StructuredDatagramTransport, WebTransportDatagramTransport
from pywebtransport.exceptions import SerializationError


class MockMsgA:
    pass


class MockMsgB:
    pass


@pytest.fixture
def mock_datagram_transport(mocker: MockerFixture) -> AsyncMock:
    mock = mocker.create_autospec(WebTransportDatagramTransport, spec_set=True, instance=True)
    mock.receive = AsyncMock()
    mock.send = AsyncMock()
    mock.close = AsyncMock()
    return mock


@pytest.fixture
def mock_serializer(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(Serializer, spec_set=True, instance=True)


@pytest.fixture
def registry() -> dict[int, type[Any]]:
    return {1: MockMsgA, 2: MockMsgB}


@pytest.fixture
def structured_transport(
    mock_datagram_transport: AsyncMock,
    mock_serializer: MagicMock,
    registry: dict[int, type[Any]],
) -> StructuredDatagramTransport:
    return StructuredDatagramTransport(
        datagram_transport=mock_datagram_transport,
        serializer=mock_serializer,
        registry=registry,
    )


class TestStructuredDatagramTransport:
    @pytest.mark.asyncio
    async def test_close_method(
        self,
        structured_transport: StructuredDatagramTransport,
        mock_datagram_transport: AsyncMock,
    ) -> None:
        await structured_transport.close()

        mock_datagram_transport.close.assert_awaited_once()

    def test_init(
        self,
        structured_transport: StructuredDatagramTransport,
        mock_datagram_transport: AsyncMock,
        mock_serializer: MagicMock,
        registry: dict[int, type[Any]],
    ) -> None:
        expected_class_to_id = {MockMsgA: 1, MockMsgB: 2}

        assert structured_transport._datagram_transport is mock_datagram_transport
        assert structured_transport._serializer is mock_serializer
        assert structured_transport._registry is registry
        assert structured_transport._class_to_id == expected_class_to_id

    def test_init_with_duplicate_registry_types_raises_error(
        self, mock_datagram_transport: AsyncMock, mock_serializer: MagicMock
    ) -> None:
        faulty_registry = {1: MockMsgA, 2: MockMsgA}
        with pytest.raises(
            ConfigurationError,
            match="Types in the structured datagram registry must be unique",
        ):
            StructuredDatagramTransport(
                datagram_transport=mock_datagram_transport,
                serializer=mock_serializer,
                registry=faulty_registry,
            )

    @pytest.mark.parametrize("closed_status", [True, False])
    def test_is_closed_property(
        self,
        structured_transport: StructuredDatagramTransport,
        mock_datagram_transport: AsyncMock,
        closed_status: bool,
    ) -> None:
        type(mock_datagram_transport).is_closed = closed_status

        assert structured_transport.is_closed is closed_status

    @pytest.mark.asyncio
    async def test_receive_obj_successful(
        self,
        structured_transport: StructuredDatagramTransport,
        mock_datagram_transport: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        type_id = 2
        message_class = MockMsgB
        serialized_payload = b"serialized_data_b"
        header = struct.pack("!H", type_id)
        mock_datagram_transport.receive.return_value = header + serialized_payload
        deserialized_obj = MockMsgB()
        mock_serializer.deserialize.return_value = deserialized_obj

        result = await structured_transport.receive_obj(timeout=5.0)

        mock_datagram_transport.receive.assert_awaited_once_with(timeout=5.0)
        mock_serializer.deserialize.assert_called_once_with(data=serialized_payload, obj_type=message_class)
        assert result is deserialized_obj

    @pytest.mark.asyncio
    async def test_receive_obj_unknown_type_id_raises_error(
        self,
        structured_transport: StructuredDatagramTransport,
        mock_datagram_transport: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        unknown_type_id = 99
        header = struct.pack("!H", unknown_type_id)
        payload = b"some_payload"
        mock_datagram_transport.receive.return_value = header + payload

        with pytest.raises(SerializationError) as exc_info:
            await structured_transport.receive_obj()

        assert f"Received unknown message type ID: {unknown_type_id}" in str(exc_info.value)
        mock_serializer.deserialize.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_obj_successful(
        self,
        structured_transport: StructuredDatagramTransport,
        mock_datagram_transport: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        obj_to_send = MockMsgA()
        type_id = 1
        serialized_payload = b"serialized_data"
        mock_serializer.serialize.return_value = serialized_payload

        await structured_transport.send_obj(obj=obj_to_send, priority=5, ttl=10.0)

        mock_serializer.serialize.assert_called_once_with(obj=obj_to_send)
        header = struct.pack("!H", type_id)
        mock_datagram_transport.send.assert_awaited_once_with(data=header + serialized_payload, priority=5, ttl=10.0)

    @pytest.mark.asyncio
    async def test_send_obj_unregistered_raises_error(
        self,
        structured_transport: StructuredDatagramTransport,
        mock_datagram_transport: AsyncMock,
        mock_serializer: MagicMock,
    ) -> None:
        class UnregisteredMsg:
            pass

        obj_to_send = UnregisteredMsg()

        with pytest.raises(SerializationError) as exc_info:
            await structured_transport.send_obj(obj=obj_to_send)

        assert "Object of type 'UnregisteredMsg' is not registered" in str(exc_info.value)
        mock_serializer.serialize.assert_not_called()
        mock_datagram_transport.send.assert_not_awaited()
