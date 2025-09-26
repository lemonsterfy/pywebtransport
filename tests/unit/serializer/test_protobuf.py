"""Unit tests for the pywebtransport.serializer.protobuf module."""

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConfigurationError, SerializationError

try:
    from google.protobuf.message import DecodeError, Message
except ImportError:
    Message = None
    DecodeError = None


@pytest.fixture
def ProtobufSerializer_class() -> type[Any]:
    from pywebtransport.serializer import ProtobufSerializer

    return ProtobufSerializer


@pytest.fixture
def MockMessage(mocker: MockerFixture) -> Any:

    if Message is None:
        yield type("DummyMessage", (), {})
        return

    mock_class = MagicMock()
    mock_class.__name__ = "MockMessage"

    original_issubclass = issubclass
    target = "pywebtransport.serializer.protobuf.issubclass"

    def issubclass_side_effect(cls: Any, base: Any) -> bool:
        if cls is mock_class and base is Message:
            return True
        return original_issubclass(cls, base)

    patcher = mocker.patch(target, side_effect=issubclass_side_effect)
    patcher.start()
    yield mock_class
    patcher.stop()


@pytest.mark.skipif(Message is None, reason="protobuf library not installed")
class TestProtobufSerializer:

    def test_init_raises_error_for_invalid_message_class(
        self, ProtobufSerializer_class: type[Any], mocker: MockerFixture
    ) -> None:
        mocker.patch("pywebtransport.serializer.protobuf.issubclass", return_value=False)

        class NotAMessage:
            pass

        with pytest.raises(TypeError) as exc_info:
            ProtobufSerializer_class(message_class=NotAMessage)
        assert "'NotAMessage' is not a valid Protobuf Message class." in str(exc_info.value)

    def test_init_successful(self, ProtobufSerializer_class: type[Any], MockMessage: MagicMock) -> None:
        serializer = ProtobufSerializer_class(message_class=MockMessage)
        assert serializer._message_class is MockMessage

    def test_serialize_raises_error_for_non_message_instance(
        self, ProtobufSerializer_class: type[Any], MockMessage: MagicMock
    ) -> None:
        serializer = ProtobufSerializer_class(message_class=MockMessage)
        obj = "this is just a string"
        with pytest.raises(SerializationError) as exc_info:
            serializer.serialize(obj=obj)
        assert "is not a Protobuf Message instance" in str(exc_info.value)

    def test_serialize_successful(
        self,
        ProtobufSerializer_class: type[Any],
        MockMessage: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        serializer = ProtobufSerializer_class(message_class=MockMessage)
        mocker.patch("pywebtransport.serializer.protobuf.isinstance", return_value=True)
        mock_instance = MockMessage()
        expected_bytes = b"serialized_data"
        mock_instance.SerializeToString.return_value = expected_bytes

        result = serializer.serialize(obj=mock_instance)

        assert result == expected_bytes
        mock_instance.SerializeToString.assert_called_once()

    def test_serialize_handles_exception(
        self,
        ProtobufSerializer_class: type[Any],
        MockMessage: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        serializer = ProtobufSerializer_class(message_class=MockMessage)
        mocker.patch("pywebtransport.serializer.protobuf.isinstance", return_value=True)
        mock_instance = MockMessage()
        original_exception = RuntimeError("Serialization failed")
        mock_instance.SerializeToString.side_effect = original_exception

        with pytest.raises(SerializationError) as exc_info:
            serializer.serialize(obj=mock_instance)
        assert exc_info.value.__cause__ is original_exception

    def test_deserialize_successful(self, ProtobufSerializer_class: type[Any], MockMessage: MagicMock) -> None:
        serializer = ProtobufSerializer_class(message_class=MockMessage)
        mock_instance = MagicMock()
        MockMessage.return_value = mock_instance
        data = b"serialized_data"

        result = serializer.deserialize(data=data)

        MockMessage.assert_called_once()
        mock_instance.ParseFromString.assert_called_once_with(serialized=data)
        assert result is mock_instance

    def test_deserialize_handles_decode_error(
        self, ProtobufSerializer_class: type[Any], MockMessage: MagicMock
    ) -> None:
        serializer = ProtobufSerializer_class(message_class=MockMessage)
        mock_instance = MagicMock()
        MockMessage.return_value = mock_instance
        original_exception = DecodeError("Decoding failed")
        mock_instance.ParseFromString.side_effect = original_exception
        data = b"invalid_data"

        with pytest.raises(SerializationError) as exc_info:
            serializer.deserialize(data=data)

        MockMessage.assert_called_once()
        assert "Failed to deserialize data into 'MockMessage'" in str(exc_info.value)
        assert exc_info.value.__cause__ is original_exception

    def test_deserialize_ignores_obj_type(self, ProtobufSerializer_class: type[Any], MockMessage: MagicMock) -> None:

        serializer = ProtobufSerializer_class(message_class=MockMessage)
        mock_instance = MagicMock()
        MockMessage.return_value = mock_instance
        data = b"some_data"

        result = serializer.deserialize(data=data, obj_type=list)

        MockMessage.assert_called_once()
        mock_instance.ParseFromString.assert_called_once_with(serialized=data)
        assert result is mock_instance


def test_init_raises_error_if_protobuf_not_installed(
    mocker: MockerFixture,
) -> None:

    mocker.patch.dict("sys.modules", {"google.protobuf.message": None})
    if "pywebtransport.serializer.protobuf" in sys.modules:
        del sys.modules["pywebtransport.serializer.protobuf"]
    if "pywebtransport.serializer" in sys.modules:
        del sys.modules["pywebtransport.serializer"]

    with pytest.raises(ConfigurationError):
        from pywebtransport.serializer import ProtobufSerializer

        ProtobufSerializer(message_class=type("Dummy", (), {}))
