"""Unit tests for the pywebtransport.serializer.json module."""

import json
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from pywebtransport import SerializationError
from pywebtransport.serializer import JSONSerializer


@dataclass(kw_only=True)
class SimpleData:
    id: int
    name: str


@dataclass(kw_only=True)
class ComplexData:
    event: str
    data: SimpleData


class TestJSONSerializer:

    def test_init_default(self) -> None:
        serializer = JSONSerializer()
        assert serializer._kwargs == {}

    def test_init_with_kwargs(self) -> None:
        kwargs = {"indent": 2, "sort_keys": True}
        serializer = JSONSerializer(**kwargs)
        assert serializer._kwargs == kwargs

    @pytest.mark.parametrize(
        "obj, expected_json",
        [
            ({"a": 1, "b": "test"}, b'{"a": 1, "b": "test"}'),
            ([1, True, None, "str"], b'[1, true, null, "str"]'),
            ("a simple string", b'"a simple string"'),
            (123, b"123"),
            (123.45, b"123.45"),
            (True, b"true"),
            (None, b"null"),
        ],
    )
    def test_serialize_standard_types(self, obj: Any, expected_json: bytes) -> None:
        serializer = JSONSerializer()
        assert serializer.serialize(obj=obj) == expected_json

    def test_serialize_dataclass(self) -> None:
        serializer = JSONSerializer()
        instance = SimpleData(id=1, name="test")
        expected_json = b'{"id": 1, "name": "test"}'
        assert serializer.serialize(obj=instance) == expected_json

    def test_serialize_nested_dataclass(self) -> None:
        serializer = JSONSerializer(sort_keys=True)
        instance = ComplexData(event="new_data", data=SimpleData(id=2, name="nested"))
        expected_json = b'{"data": {"id": 2, "name": "nested"}, "event": "new_data"}'
        assert serializer.serialize(obj=instance) == expected_json

    def test_serialize_unserializable_raises_error(self) -> None:
        serializer = JSONSerializer()
        unserializable_obj = set([1, 2, 3])

        with pytest.raises(SerializationError) as exc_info:
            serializer.serialize(obj=unserializable_obj)
        assert "is not JSON serializable" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)

    def test_serialize_with_kwargs(self) -> None:
        serializer = JSONSerializer(indent=2, sort_keys=True)
        obj = {"z": 1, "a": 2}
        expected_json = b'{\n  "a": 2,\n  "z": 1\n}'
        assert serializer.serialize(obj=obj) == expected_json

    @pytest.mark.parametrize(
        "data, expected_obj",
        [
            (b'{"a": 1, "b": "test"}', {"a": 1, "b": "test"}),
            (b'[1, true, null, "str"]', [1, True, None, "str"]),
            (b'"a simple string"', "a simple string"),
            (b"123", 123),
        ],
    )
    def test_deserialize_standard_types(self, data: bytes, expected_obj: Any) -> None:
        serializer = JSONSerializer()
        assert serializer.deserialize(data=data) == expected_obj

    def test_deserialize_to_dataclass(self) -> None:
        serializer = JSONSerializer()
        data = b'{"id": 10, "name": "from_json"}'
        result = serializer.deserialize(data=data, obj_type=SimpleData)

        assert isinstance(result, SimpleData)
        assert result.id == 10
        assert result.name == "from_json"

    def test_deserialize_to_nested_dataclass(self) -> None:
        serializer = JSONSerializer()
        data = b'{"event": "update", "data": {"id": 5, "name": "sub"}}'
        result = serializer.deserialize(data=data, obj_type=ComplexData)

        assert isinstance(result, ComplexData)
        assert result.event == "update"
        assert isinstance(result.data, SimpleData)
        assert result.data.id == 5
        assert result.data.name == "sub"

    def test_deserialize_to_list_of_dataclasses(self) -> None:
        serializer = JSONSerializer()
        data = b'[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]'
        result = serializer.deserialize(data=data, obj_type=List[SimpleData])

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(item, SimpleData) for item in result)
        assert result[0].name == "A"
        assert result[1].id == 2

    def test_deserialize_to_dict_of_dataclasses(self) -> None:
        serializer = JSONSerializer()
        data = b'{"item1": {"id": 1, "name": "A"}, "item2": {"id": 2, "name": "B"}}'
        result = serializer.deserialize(data=data, obj_type=Dict[str, SimpleData])

        assert isinstance(result, dict)
        assert len(result) == 2
        assert isinstance(result["item1"], SimpleData)
        assert isinstance(result["item2"], SimpleData)
        assert result["item1"].name == "A"
        assert result["item2"].id == 2

    def test_deserialize_to_dict_of_standard_types(self) -> None:
        serializer = JSONSerializer()
        data = b'{"1": "a", "2": "b"}'
        result = serializer.deserialize(data=data, obj_type=Dict[int, str])

        assert result == {1: "a", 2: "b"}

    def test_deserialize_to_list_of_standard_types(self) -> None:
        serializer = JSONSerializer()
        data = b"[1, 2, 3]"
        result = serializer.deserialize(data=data, obj_type=List[int])
        assert result == [1, 2, 3]

    def test_deserialize_to_raw_list(self) -> None:
        serializer = JSONSerializer()
        data = b'[1, "a"]'
        result = serializer.deserialize(data=data, obj_type=list)
        assert result == [1, "a"]

    def test_deserialize_to_raw_dict(self) -> None:
        serializer = JSONSerializer()
        data = b'{"a": 1}'
        result = serializer.deserialize(data=data, obj_type=dict)
        assert result == {"a": 1}

    def test_deserialize_any_type(self) -> None:
        serializer = JSONSerializer()
        data = b'{"any": "data"}'
        result = serializer.deserialize(data=data, obj_type=Any)
        assert result == {"any": "data"}

    def test_deserialize_to_dataclass_with_mismatched_data_raises_error(
        self,
    ) -> None:
        serializer = JSONSerializer()
        data = b'{"id": 10}'
        with pytest.raises(SerializationError) as exc_info:
            serializer.deserialize(data=data, obj_type=SimpleData)

        assert "Failed to unpack dictionary" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)

    def test_deserialize_invalid_json_raises_error(self) -> None:
        serializer = JSONSerializer()
        invalid_data = b'{"key": "value"'

        with pytest.raises(SerializationError) as exc_info:
            serializer.deserialize(data=invalid_data)
        assert "is not valid JSON" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)

    def test_deserialize_basic_type_conversion_failure_returns_original(self) -> None:
        serializer = JSONSerializer()
        data = b'"not_an_int"'
        result = serializer.deserialize(data=data, obj_type=int)
        assert result == "not_an_int"

    def test_deserialize_dataclass_with_failing_field_conversion(self) -> None:
        serializer = JSONSerializer()
        data = b'{"id": "abc", "name": "test"}'
        result = serializer.deserialize(data=data, obj_type=SimpleData)

        assert isinstance(result, SimpleData)
        assert result.id == "abc"  # type: ignore[comparison-overlap]
        assert result.name == "test"
