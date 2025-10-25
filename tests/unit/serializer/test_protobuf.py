from typing import Any

import pytest

from pywebtransport import ConfigurationError
from pywebtransport.exceptions import SerializationError

try:
    from google.protobuf.message import DecodeError, Message
except ImportError:
    Message = None
    DecodeError = None


class MockProtoMessage:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def SerializeToString(self) -> bytes:
        if hasattr(self, "_raise_on_serialize"):
            raise RuntimeError("Serialization failed")
        return b"serialized_data"

    def ParseFromString(self, serialized: bytes) -> None:
        if serialized == b"invalid_data":
            if DecodeError:
                raise DecodeError("Invalid wire format")
            raise RuntimeError("Cannot parse")
        self.id = 1
        self.name = "parsed"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, MockProtoMessage):
            return NotImplemented
        return self.__dict__ == other.__dict__


class AnotherMockProtoMessage(MockProtoMessage):
    pass


class NotAMessage:
    pass


@pytest.mark.skipif(Message is None, reason="protobuf library not installed")
class TestProtobufSerializer:
    @pytest.fixture
    def serializer(self, mocker: Any) -> Any:
        from pywebtransport.serializer.protobuf import ProtobufSerializer

        mocker.patch("pywebtransport.serializer.protobuf.issubclass", return_value=True)
        return ProtobufSerializer(message_class=MockProtoMessage)

    def test_deserialize_invalid_data_raises_error(self, serializer: Any) -> None:
        data = b"invalid_data"
        with pytest.raises(SerializationError, match="Failed to deserialize data"):
            serializer.deserialize(data=data)

    def test_deserialize_success(self, serializer: Any) -> None:
        data = b"valid_data"
        result = serializer.deserialize(data=data)
        assert isinstance(result, MockProtoMessage)
        assert result.id == 1
        assert result.name == "parsed"

    def test_deserialize_with_correct_obj_type(self, serializer: Any) -> None:
        data = b"valid_data"
        result = serializer.deserialize(data=data, obj_type=MockProtoMessage)
        assert result == MockProtoMessage(id=1, name="parsed")

    def test_deserialize_with_mismatched_obj_type_raises_error(self, serializer: Any) -> None:
        data = b"valid_data"
        with pytest.raises(SerializationError, match="was asked to deserialize into"):
            serializer.deserialize(data=data, obj_type=AnotherMockProtoMessage)

    def test_initialization_fails_if_protobuf_is_not_installed(self, mocker: Any) -> None:
        from pywebtransport.serializer.protobuf import ProtobufSerializer

        mocker.patch("pywebtransport.serializer.protobuf.Message", None)

        with pytest.raises(ConfigurationError, match="library is required"):
            ProtobufSerializer(message_class=MockProtoMessage)

    def test_initialization_fails_with_invalid_message_class(self, mocker: Any) -> None:
        from pywebtransport.serializer.protobuf import ProtobufSerializer

        mocker.patch("pywebtransport.serializer.protobuf.issubclass", return_value=False)
        with pytest.raises(TypeError, match="is not a valid Protobuf Message class"):
            ProtobufSerializer(message_class=NotAMessage)

    def test_serialize_internal_failure_raises_error(self, serializer: Any) -> None:
        message = MockProtoMessage(_raise_on_serialize=True)
        with pytest.raises(SerializationError, match="Failed to serialize"):
            serializer.serialize(obj=message)

    def test_serialize_success(self, serializer: Any) -> None:
        message = MockProtoMessage(id=1, name="test")
        result = serializer.serialize(obj=message)
        assert result == b"serialized_data"

    def test_serialize_wrong_object_type_raises_error(self, serializer: Any) -> None:
        message = NotAMessage()
        with pytest.raises(SerializationError, match="received an object of type"):
            serializer.serialize(obj=message)
