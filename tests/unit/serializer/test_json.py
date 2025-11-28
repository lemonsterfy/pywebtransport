"""Unit tests for the pywebtransport.serializer.json module."""

from dataclasses import dataclass

import pytest

from pywebtransport.exceptions import SerializationError
from pywebtransport.serializer import JSONSerializer


@dataclass
class SimpleData:
    id: int
    name: str


class NonSerializable:
    pass


class TestJSONSerializer:
    @pytest.fixture
    def serializer(self) -> JSONSerializer:
        return JSONSerializer()

    @pytest.mark.parametrize("invalid_data", [b"{'id': 1, 'name': 'test'}", b'{"id": 1, "name": "test"', b"not json"])
    def test_deserialize_invalid_json_raises_error(self, serializer: JSONSerializer, invalid_data: bytes) -> None:
        with pytest.raises(SerializationError, match="Data is not valid JSON"):
            serializer.deserialize(data=invalid_data)

    def test_deserialize_to_dataclass(self, serializer: JSONSerializer) -> None:
        data = b'{"id": 1, "name": "test"}'

        result = serializer.deserialize(data=data, obj_type=SimpleData)

        assert result == SimpleData(id=1, name="test")

    def test_deserialize_to_dataclass_with_type_conversion(self, serializer: JSONSerializer) -> None:
        data = b'{"id": "1", "name": 123}'

        result = serializer.deserialize(data=data, obj_type=SimpleData)

        assert result == SimpleData(id=1, name="123")

    def test_deserialize_to_dict(self, serializer: JSONSerializer) -> None:
        data = b'{"id": 1, "name": "test"}'

        result = serializer.deserialize(data=data)

        assert result == {"id": 1, "name": "test"}

    def test_deserialize_type_mismatch_raises_error(self, serializer: JSONSerializer) -> None:
        data = b'{"name": "test"}'

        with pytest.raises(SerializationError, match="Failed to unpack"):
            serializer.deserialize(data=data, obj_type=SimpleData)

    def test_serialize_dataclass(self, serializer: JSONSerializer) -> None:
        instance = SimpleData(id=1, name="test")
        expected = b'{"id": 1, "name": "test"}'

        result = serializer.serialize(obj=instance)

        assert result == expected

    def test_serialize_dict(self, serializer: JSONSerializer) -> None:
        data = {"key": "value", "items": [1, True, None]}
        expected = b'{"key": "value", "items": [1, true, null]}'

        result = serializer.serialize(obj=data)

        assert result == expected

    def test_serialize_unsupported_type_raises_error(self, serializer: JSONSerializer) -> None:
        with pytest.raises(SerializationError) as exc_info:
            serializer.serialize(obj=NonSerializable())

        assert "is not JSON serializable" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)

    def test_serialize_with_kwargs(self) -> None:
        serializer = JSONSerializer(indent=2, sort_keys=True)
        instance = SimpleData(name="test", id=1)
        expected = b'{\n  "id": 1,\n  "name": "test"\n}'

        result = serializer.serialize(obj=instance)

        assert result == expected
