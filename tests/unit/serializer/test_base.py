"""Unit tests for the pywebtransport.serializer._base module."""

from dataclasses import dataclass
from typing import Any

import pytest

from pywebtransport.exceptions import SerializationError
from pywebtransport.serializer._base import _BaseDataclassSerializer


@dataclass
class SimpleDataclass:
    value_int: int
    value_str: str


@dataclass
class ComplexDataclass:
    simple: SimpleDataclass
    items: list[int]
    mapping: dict[str, SimpleDataclass]
    optional_value: Any = None
    defaults: str = "default"


@dataclass
class DataclassWithMissingField:
    required: str
    optional_with_default: int = 123


class TestBaseDataclassSerializer:
    @pytest.fixture
    def serializer(self) -> _BaseDataclassSerializer:
        return _BaseDataclassSerializer()

    def test_convert_ignores_extra_fields(self, serializer: _BaseDataclassSerializer) -> None:
        data = {"value_int": 1, "value_str": "text", "extra_field": "ignore"}

        result = serializer._convert_to_type(data=data, target_type=SimpleDataclass)

        assert isinstance(result, SimpleDataclass)
        assert not hasattr(result, "extra_field")

    def test_convert_to_complex_dataclass(self, serializer: _BaseDataclassSerializer) -> None:
        data = {
            "simple": {"value_int": 1, "value_str": "nested"},
            "items": ["2", "3", "4"],
            "mapping": {"first": {"value_int": 100, "value_str": "a"}, "second": {"value_int": 200, "value_str": "b"}},
            "optional_value": "provided",
        }

        result = serializer._convert_to_type(data=data, target_type=ComplexDataclass)

        assert isinstance(result, ComplexDataclass)
        assert isinstance(result.simple, SimpleDataclass)
        assert result.simple.value_int == 1
        assert result.items == [2, 3, 4]
        assert isinstance(result.mapping["first"], SimpleDataclass)
        assert result.mapping["second"].value_int == 200
        assert result.optional_value == "provided"
        assert result.defaults == "default"

    def test_convert_to_simple_dataclass(self, serializer: _BaseDataclassSerializer) -> None:
        data = {"value_int": 10, "value_str": "hello"}

        result = serializer._convert_to_type(data=data, target_type=SimpleDataclass)

        assert isinstance(result, SimpleDataclass)
        assert result.value_int == 10
        assert result.value_str == "hello"

    @pytest.mark.parametrize(
        "data, target_type, expected",
        [
            (None, int, None),
            (123, Any, 123),
            ([1], Any, [1]),
            ("42", int, 42),
            (42, str, "42"),
            ("not-an-int", int, "not-an-int"),
            (None, int, None),
            (123, int, 123),
            ([1, "a"], list, [1, "a"]),
            ([1, "a"], tuple, (1, "a")),
            ([1, "a", 1], set, {1, "a"}),
            ({"k": "v"}, dict, {"k": "v"}),
            (["1", "2"], list[int], [1, 2]),
            (("1",), tuple[int], (1,)),
            (["1", "2", "1"], set[int], {1, 2}),
            (
                [{"value_int": "1", "value_str": "a"}],
                list[SimpleDataclass],
                [SimpleDataclass(value_int=1, value_str="a")],
            ),
            ({"key": "123"}, dict[str, int], {"key": 123}),
            ({"1": "value"}, dict[int, str], {1: "value"}),
        ],
    )
    def test_convert_to_type_various(
        self, serializer: _BaseDataclassSerializer, data: Any, target_type: Any, expected: Any
    ) -> None:
        result = serializer._convert_to_type(data=data, target_type=target_type)

        assert result == expected

    def test_from_dict_to_dataclass_raises_serialization_error(self, serializer: _BaseDataclassSerializer) -> None:
        data = {"optional_with_default": 456}

        with pytest.raises(SerializationError) as exc_info:
            serializer._from_dict_to_dataclass(data=data, cls=DataclassWithMissingField)

        assert "Failed to unpack dictionary" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)
