"""Serializer implementation using the JSON format."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from pywebtransport.exceptions import SerializationError
from pywebtransport.serializer._base import _BaseDataclassSerializer
from pywebtransport.types import Serializer

__all__: list[str] = ["JSONSerializer"]


class JSONSerializer(_BaseDataclassSerializer, Serializer):
    """Serializer for encoding and decoding using the JSON format."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the JSON serializer."""
        self._kwargs = kwargs

    def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any:
        """Deserialize a JSON byte string into a Python object."""
        try:
            decoded_obj = json.loads(s=data)

            if not obj_type:
                return decoded_obj
            return self._convert_to_type(data=decoded_obj, target_type=obj_type)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise SerializationError(
                message="Data is not valid JSON or cannot be unpacked.",
                original_exception=e,
            ) from e

    def serialize(self, *, obj: Any) -> bytes:
        """Serialize a Python object into a JSON byte string."""

        def default_handler(o: Any) -> Any:
            if not isinstance(o, type) and is_dataclass(o):
                return asdict(obj=o)
            raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

        try:
            return json.dumps(obj=obj, default=default_handler, **self._kwargs).encode("utf-8")
        except TypeError as e:
            raise SerializationError(
                message=f"Object of type {type(obj).__name__} is not JSON serializable.",
                original_exception=e,
            ) from e
