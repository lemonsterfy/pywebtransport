"""Protocol Buffers (Protobuf) Serializer for WebTransport."""

from __future__ import annotations

from typing import Any, cast

from pywebtransport.exceptions import ConfigurationError, SerializationError
from pywebtransport.types import Serializer

try:
    from google.protobuf.message import DecodeError, Message
except ImportError:
    Message = None
    DecodeError = None


__all__ = ["ProtobufSerializer"]


class ProtobufSerializer(Serializer):
    """A serializer that encodes and decodes objects using the Protobuf format."""

    def __init__(self, *, message_class: type[Message]) -> None:
        """Initialize the Protobuf serializer."""
        if Message is None:
            raise ConfigurationError(
                message="The 'protobuf' library is required for ProtobufSerializer.",
                config_key="dependency.protobuf",
                details={"installation_guide": "Please install it with: pip install pywebtransport[protobuf]"},
            )
        if not issubclass(message_class, Message):
            raise TypeError(f"'{message_class.__name__}' is not a valid Protobuf Message class.")

        self._message_class = message_class

    def deserialize(self, *, data: bytes, obj_type: Any = None) -> Message:
        """Deserialize bytes into an instance of the configured Protobuf message class."""
        instance = self._message_class()

        try:
            instance.ParseFromString(serialized=data)
            return instance
        except DecodeError as e:
            raise SerializationError(
                message=f"Failed to deserialize data into '{self._message_class.__name__}'.",
                original_exception=e,
            ) from e

    def serialize(self, *, obj: Any) -> bytes:
        """Serialize a Protobuf message object into bytes."""
        if not isinstance(obj, Message):
            raise SerializationError(message=f"Object of type {type(obj).__name__} is not a Protobuf Message instance.")

        try:
            return cast(bytes, obj.SerializeToString())
        except Exception as e:
            raise SerializationError(
                message=f"Failed to serialize Protobuf message: {e}",
                original_exception=e,
            ) from e
