"""Serializer implementation using the MsgPack format."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, cast

from pywebtransport.exceptions import ConfigurationError, SerializationError
from pywebtransport.serializer._base import _BaseDataclassSerializer
from pywebtransport.types import Serializer

try:
    import msgpack
except ImportError:
    msgpack = None


__all__: list[str] = ["MsgPackSerializer"]


class MsgPackSerializer(_BaseDataclassSerializer, Serializer):
    """Serializer for encoding and decoding using the MsgPack format."""

    def __init__(
        self, *, pack_kwargs: dict[str, Any] | None = None, unpack_kwargs: dict[str, Any] | None = None
    ) -> None:
        """Initialize the MsgPack serializer."""
        if msgpack is None:
            raise ConfigurationError(
                message="The 'msgpack' library is required for MsgPackSerializer.",
                config_key="dependency.msgpack",
                details={"installation_guide": "Please install it with: pip install pywebtransport[msgpack]"},
            )

        self._pack_kwargs = pack_kwargs or {}
        self._unpack_kwargs = unpack_kwargs or {}

    def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any:
        """Deserialize a MsgPack byte string into a Python object."""
        try:
            unpack_kwargs = {"raw": False, **self._unpack_kwargs}
            decoded_obj = msgpack.unpackb(packed=data, **unpack_kwargs)

            if not obj_type:
                return decoded_obj
            return self._convert_to_type(data=decoded_obj, target_type=obj_type)
        except (msgpack.UnpackException, TypeError, ValueError) as e:
            raise SerializationError(
                message="Data is not valid MsgPack or cannot be unpacked.", original_exception=e
            ) from e

    def serialize(self, *, obj: Any) -> bytes:
        """Serialize a Python object into a MsgPack byte string."""

        def default_handler(o: Any) -> Any:
            if not isinstance(o, type) and is_dataclass(o):
                return asdict(obj=o)
            raise TypeError(f"Object of type {o.__class__.__name__} is not MsgPack serializable")

        try:
            return cast(bytes, msgpack.packb(o=obj, default=default_handler, **self._pack_kwargs))
        except TypeError as e:
            raise SerializationError(
                message=f"Object of type {type(obj).__name__} is not MsgPack serializable.", original_exception=e
            ) from e
