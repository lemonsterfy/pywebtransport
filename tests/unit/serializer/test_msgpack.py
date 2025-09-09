"""
Unit tests for the pywebtransport.serializer.msgpack module.
"""

import sys
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Type

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConfigurationError, SerializationError

try:
    import msgpack
except ImportError:
    msgpack = None


@dataclass(kw_only=True)
class SimpleData:
    id: int
    name: str


@dataclass(kw_only=True)
class ComplexData:
    event: str
    data: SimpleData


@pytest.fixture
def MsgPackSerializer_class() -> Type[Any]:
    """Fixture to dynamically import the MsgPackSerializer class."""
    from pywebtransport.serializer import MsgPackSerializer

    return MsgPackSerializer


@pytest.mark.skipif(msgpack is None, reason="msgpack library not installed")
class TestMsgPackSerializer:
    """
    Test suite for the MsgPackSerializer class.
    """

    def test_init_default(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        assert serializer._pack_kwargs == {}
        assert serializer._unpack_kwargs == {}

    def test_init_with_kwargs(self, MsgPackSerializer_class: Type[Any]) -> None:
        pack_kwargs = {"use_bin_type": True}
        unpack_kwargs = {"raw": False}
        serializer = MsgPackSerializer_class(pack_kwargs=pack_kwargs, unpack_kwargs=unpack_kwargs)
        assert serializer._pack_kwargs == pack_kwargs
        assert serializer._unpack_kwargs == unpack_kwargs

    @pytest.mark.parametrize(
        "obj",
        [
            {"a": 1, "b": "test"},
            [1, True, None, "str"],
            "a simple string",
            123,
            123.45,
            True,
            None,
        ],
    )
    def test_serialize_standard_types(self, obj: Any, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        expected_bytes = msgpack.packb(o=obj, default=asdict)
        assert serializer.serialize(obj=obj) == expected_bytes

    def test_serialize_dataclass(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        instance = SimpleData(id=1, name="test")
        expected_bytes = msgpack.packb(o={"id": 1, "name": "test"})
        assert serializer.serialize(obj=instance) == expected_bytes

    def test_serialize_nested_dataclass(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        instance = ComplexData(event="new_data", data=SimpleData(id=2, name="nested"))
        expected_bytes = msgpack.packb(
            o={"event": "new_data", "data": {"id": 2, "name": "nested"}},
        )
        assert serializer.serialize(obj=instance) == expected_bytes

    def test_serialize_unserializable_raises_error(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        unserializable_obj = {1, 2, 3}
        with pytest.raises(SerializationError) as exc_info:
            serializer.serialize(obj=unserializable_obj)
        assert "is not MsgPack serializable" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)

    @pytest.mark.parametrize(
        "obj",
        [
            {"a": 1, "b": "test"},
            [1, True, None, "str"],
            "a simple string",
            123,
        ],
    )
    def test_deserialize_standard_types(self, obj: Any, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o=obj)
        assert serializer.deserialize(data=data) == obj

    def test_deserialize_to_dataclass(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o={"id": 10, "name": "from_msgpack"})
        result = serializer.deserialize(data=data, obj_type=SimpleData)
        assert isinstance(result, SimpleData)
        assert result.id == 10
        assert result.name == "from_msgpack"

    def test_deserialize_to_nested_dataclass(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o={"event": "update", "data": {"id": 5, "name": "sub"}})
        result = serializer.deserialize(data=data, obj_type=ComplexData)
        assert isinstance(result, ComplexData)
        assert result.event == "update"
        assert isinstance(result.data, SimpleData)
        assert result.data.id == 5
        assert result.data.name == "sub"

    def test_deserialize_to_list_of_dataclasses(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o=[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
        result = serializer.deserialize(data=data, obj_type=List[SimpleData])
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(item, SimpleData) for item in result)
        assert result[0].name == "A"
        assert result[1].id == 2

    def test_deserialize_to_dict_of_dataclasses(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o={"item1": {"id": 1, "name": "A"}, "item2": {"id": 2, "name": "B"}})
        result = serializer.deserialize(data=data, obj_type=Dict[str, SimpleData])
        assert isinstance(result, dict)
        assert len(result) == 2
        assert isinstance(result["item1"], SimpleData)
        assert result["item2"].id == 2

    def test_deserialize_to_dict_of_standard_types(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class(unpack_kwargs={"strict_map_key": False})
        data = msgpack.packb(o={1: "a", 2: "b"})
        result = serializer.deserialize(data=data, obj_type=Dict[int, str])
        assert result == {1: "a", 2: "b"}

    def test_deserialize_to_list_of_standard_types(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o=[1, 2, 3])
        result = serializer.deserialize(data=data, obj_type=List[int])
        assert result == [1, 2, 3]

    def test_deserialize_to_raw_list(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o=[1, "a"])
        result = serializer.deserialize(data=data, obj_type=list)
        assert result == [1, "a"]

    def test_deserialize_to_raw_dict(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o={"a": 1})
        result = serializer.deserialize(data=data, obj_type=dict)
        assert result == {"a": 1}

    def test_deserialize_any_type(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o={"any": "data"})
        result = serializer.deserialize(data=data, obj_type=Any)
        assert result == {"any": "data"}

    def test_deserialize_to_dataclass_with_mismatched_data_raises_error(
        self, MsgPackSerializer_class: Type[Any]
    ) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o={"id": 10})
        with pytest.raises(SerializationError) as exc_info:
            serializer.deserialize(data=data, obj_type=SimpleData)
        assert "Failed to unpack dictionary" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)

    def test_deserialize_failure_invalid_data(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        invalid_data = b"\xc1"  # Invalid msgpack data
        with pytest.raises(SerializationError) as exc_info:
            serializer.deserialize(data=invalid_data)
        assert "Data is not valid MsgPack" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, (msgpack.UnpackException, ValueError))

    def test_deserialize_basic_type_conversion_failure_returns_original(
        self, MsgPackSerializer_class: Type[Any]
    ) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o="not_an_int")
        result = serializer.deserialize(data=data, obj_type=int)
        assert result == "not_an_int"

    def test_deserialize_dataclass_with_failing_field_conversion(self, MsgPackSerializer_class: Type[Any]) -> None:
        serializer = MsgPackSerializer_class()
        data = msgpack.packb(o={"id": "abc", "name": "test"})
        result = serializer.deserialize(data=data, obj_type=SimpleData)
        assert isinstance(result, SimpleData)
        assert result.id == "abc"  # type: ignore[comparison-overlap]
        assert result.name == "test"


def test_init_raises_error_if_msgpack_not_installed(mocker: MockerFixture) -> None:
    """
    Verify __init__ raises ConfigurationError if msgpack is not installed.
    """
    mocker.patch.dict("sys.modules", {"msgpack": None})
    if "pywebtransport.serializer.msgpack" in sys.modules:
        del sys.modules["pywebtransport.serializer.msgpack"]
    if "pywebtransport.serializer" in sys.modules:
        del sys.modules["pywebtransport.serializer"]

    with pytest.raises(ConfigurationError):
        from pywebtransport.serializer import MsgPackSerializer

        MsgPackSerializer()
