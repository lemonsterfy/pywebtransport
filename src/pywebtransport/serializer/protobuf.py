"""Serializer implementation using the Protocol Buffers format."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pywebtransport.exceptions import ConfigurationError, SerializationError
from pywebtransport.types import Serializer

try:
    from google.protobuf.message import DecodeError, Message
except ImportError:
    Message = None
    DecodeError = None

if TYPE_CHECKING:
    from google.protobuf.message import Message as MessageType


__all__: list[str] = ["ProtobufSerializer"]


class ProtobufSerializer(Serializer):
    """Serializer for encoding and decoding using the Protobuf format."""

    def __init__(self, *, message_class: type[MessageType]) -> None:
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

    def deserialize(self, *, data: bytes, obj_type: Any = None) -> MessageType:
        """Deserialize bytes into an instance of the configured Protobuf message class."""
        if obj_type and obj_type is not self._message_class:
            raise SerializationError(
                message=(
                    f"This ProtobufSerializer is configured for type '{self._message_class.__name__}', "
                    f"but was asked to deserialize into '{obj_type.__name__}'."
                )
            )

        instance = self._message_class()

        try:
            instance.ParseFromString(serialized=data)
            return instance
        except (DecodeError, Exception) as e:
            raise SerializationError(
                message=f"Failed to deserialize data into '{self._message_class.__name__}'.",
                original_exception=e,
            ) from e

    def serialize(self, *, obj: Any) -> bytes:
        """Serialize a Protobuf message object into bytes."""
        if not isinstance(obj, self._message_class):
            raise SerializationError(
                message=(
                    f"This ProtobufSerializer is configured for type '{self._message_class.__name__}', "
                    f"but received an object of type '{type(obj).__name__}'."
                )
            )

        try:
            return cast(bytes, obj.SerializeToString())
        except Exception as e:
            raise SerializationError(
                message=f"Failed to serialize Protobuf message: {e}",
                original_exception=e,
            ) from e
