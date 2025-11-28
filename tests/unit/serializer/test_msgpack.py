"""Unit tests for the pywebtransport.serializer.msgpack module."""

import importlib
import sys
from dataclasses import dataclass
from typing import Any

import pytest
from pytest_mock import MockerFixture

from pywebtransport import ConfigurationError
from pywebtransport.exceptions import SerializationError

try:
    import msgpack
except ImportError:
    msgpack = None


@dataclass
class SimpleData:
    id: int
    name: str


class NonSerializable:
    pass


@pytest.mark.skipif(msgpack is None, reason="msgpack library not installed")
class TestMsgPackSerializer:
    @pytest.fixture
    def serializer(self) -> Any:
        import pywebtransport.serializer.msgpack

        importlib.reload(pywebtransport.serializer.msgpack)
        from pywebtransport.serializer.msgpack import MsgPackSerializer

        return MsgPackSerializer()

    def test_deserialize_invalid_data_raises_error(self, serializer: Any) -> None:
        with pytest.raises(SerializationError, match="Data is not valid MsgPack"):
            serializer.deserialize(data=b"\xc1")

    def test_deserialize_to_dataclass(self, serializer: Any) -> None:
        data = msgpack.packb({"id": 1, "name": "test"})

        result = serializer.deserialize(data=data, obj_type=SimpleData)

        assert result == SimpleData(id=1, name="test")

    def test_deserialize_to_dict(self, serializer: Any) -> None:
        data = msgpack.packb({"id": 1, "name": "test"})

        result = serializer.deserialize(data=data)

        assert result == {"id": 1, "name": "test"}

    def test_deserialize_type_mismatch_raises_error(self, serializer: Any) -> None:
        data = msgpack.packb({"name": "test"})

        with pytest.raises(SerializationError, match="Failed to unpack"):
            serializer.deserialize(data=data, obj_type=SimpleData)

    def test_deserialize_with_unpack_kwargs(self, mocker: MockerFixture) -> None:
        from pywebtransport.serializer.msgpack import MsgPackSerializer

        mock_unpackb = mocker.patch("msgpack.unpackb")
        serializer = MsgPackSerializer(unpack_kwargs={"strict_map_key": False})
        data = b"\x80"

        serializer.deserialize(data=data)

        mock_unpackb.assert_called_once()
        _, kwargs = mock_unpackb.call_args
        assert kwargs["strict_map_key"] is False
        assert kwargs["raw"] is False

    def test_import_error_handling(self, mocker: MockerFixture) -> None:
        mocker.patch.dict(sys.modules, {"msgpack": None})
        import pywebtransport.serializer.msgpack

        importlib.reload(pywebtransport.serializer.msgpack)
        from pywebtransport.serializer.msgpack import MsgPackSerializer

        assert getattr(pywebtransport.serializer.msgpack, "msgpack") is None

        with pytest.raises(ConfigurationError, match="library is required"):
            MsgPackSerializer()

        mocker.stopall()
        importlib.reload(pywebtransport.serializer.msgpack)

    def test_initialization_fails_if_msgpack_is_not_installed(self, mocker: MockerFixture) -> None:
        from pywebtransport.serializer.msgpack import MsgPackSerializer

        mocker.patch("pywebtransport.serializer.msgpack.msgpack", None)

        with pytest.raises(ConfigurationError, match="library is required"):
            MsgPackSerializer()

    def test_serialize_dataclass(self, serializer: Any) -> None:
        instance = SimpleData(id=1, name="test")

        result = serializer.serialize(obj=instance)

        unpacked = msgpack.unpackb(result)
        assert unpacked == {"id": 1, "name": "test"}

    def test_serialize_dict(self, serializer: Any) -> None:
        data = {"key": "value", "items": [1, True, None]}

        result = serializer.serialize(obj=data)

        unpacked = msgpack.unpackb(result)
        assert unpacked == data

    def test_serialize_unsupported_type_raises_error(self, serializer: Any) -> None:
        with pytest.raises(SerializationError) as exc_info:
            serializer.serialize(obj=NonSerializable())

        assert "is not MsgPack serializable" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TypeError)

    def test_serialize_with_pack_kwargs(self, mocker: MockerFixture) -> None:
        import pywebtransport.serializer.msgpack

        importlib.reload(pywebtransport.serializer.msgpack)
        from pywebtransport.serializer.msgpack import MsgPackSerializer

        mock_packb = mocker.patch("msgpack.packb")
        serializer = MsgPackSerializer(pack_kwargs={"use_bin_type": False})
        obj = {"data": "test"}

        serializer.serialize(obj=obj)

        mock_packb.assert_called_once()
        _, kwargs = mock_packb.call_args
        assert kwargs["use_bin_type"] is False
