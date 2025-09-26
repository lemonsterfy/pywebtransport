"""MsgPack Serializer for WebTransport."""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from typing import Any, cast, get_args, get_origin

from pywebtransport.exceptions import ConfigurationError, SerializationError
from pywebtransport.types import Serializer

try:
    import msgpack
except ImportError:
    msgpack = None


__all__ = ["MsgPackSerializer"]


class MsgPackSerializer(Serializer):
    """A serializer that encodes and decodes objects using the MsgPack format."""

    def __init__(
        self,
        *,
        pack_kwargs: dict[str, Any] | None = None,
        unpack_kwargs: dict[str, Any] | None = None,
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
                message="Data is not valid MsgPack or cannot be unpacked.",
                original_exception=e,
            ) from e

    def serialize(self, *, obj: Any) -> bytes:
        """Serialize a Python object into a MsgPack byte string."""

        def default_handler(o: Any) -> Any:
            if not isinstance(o, type) and is_dataclass(o):
                return asdict(obj=o)
            raise TypeError(f"Object of type {o.__class__.__name__} is not MsgPack serializable")

        try:
            return cast(
                bytes,
                msgpack.packb(o=obj, default=default_handler, **self._pack_kwargs),
            )
        except TypeError as e:
            raise SerializationError(
                message=f"Object of type {type(obj).__name__} is not MsgPack serializable.",
                original_exception=e,
            ) from e

    def _convert_to_type(self, *, data: Any, target_type: Any) -> Any:
        """Recursively convert a decoded object to a specific target type."""
        if target_type is Any or data is None:
            return data

        origin = get_origin(target_type)
        args = get_args(target_type)

        if isinstance(target_type, type) and is_dataclass(target_type) and isinstance(data, dict):
            return self._from_dict_to_dataclass(data=data, cls=target_type)

        if (origin in (list, tuple, set) or target_type in (list, tuple, set)) and isinstance(data, list):
            container = origin or target_type
            if not args:
                return container(data)
            inner_type = args[0]
            items = [self._convert_to_type(data=item, target_type=inner_type) for item in data]
            return container(items)

        if (origin is dict or target_type is dict) and isinstance(data, dict):
            if not args:
                return data
            key_type, value_type = args
            return {
                self._convert_to_type(data=k, target_type=key_type): self._convert_to_type(
                    data=v, target_type=value_type
                )
                for k, v in data.items()
            }

        if callable(target_type) and not isinstance(data, target_type):
            try:
                return target_type(data)
            except (TypeError, ValueError):
                pass

        return data

    def _from_dict_to_dataclass(self, *, data: dict[str, Any], cls: type[Any]) -> Any:
        """Recursively convert a dictionary to a dataclass instance."""
        constructor_args = {}

        for field in fields(cls):
            if field.name in data:
                field_value = data[field.name]
                constructor_args[field.name] = self._convert_to_type(data=field_value, target_type=field.type)

        try:
            return cls(**constructor_args)
        except TypeError as e:
            raise SerializationError(
                message=f"Failed to unpack dictionary to dataclass {cls.__name__}.",
                original_exception=e,
            ) from e
