"""Base class for serializers handling dataclass conversion."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, get_args, get_origin

from pywebtransport.exceptions import SerializationError

__all__: list[str] = []


class _BaseDataclassSerializer:
    """Base class providing recursive dict-to-dataclass conversion."""

    def _convert_to_type(self, *, data: Any, target_type: Any) -> Any:
        """Recursively convert a decoded object to a specific target type."""
        if target_type is Any or data is None:
            return data

        origin = get_origin(target_type)
        args = get_args(target_type)

        if isinstance(target_type, type) and is_dataclass(target_type) and isinstance(data, dict):
            return self._from_dict_to_dataclass(data=data, cls=target_type)

        if (origin in (list, tuple, set) or target_type in (list, tuple, set)) and isinstance(data, (list, tuple, set)):
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
                message=f"Failed to unpack dictionary to dataclass {cls.__name__}.", original_exception=e
            ) from e
