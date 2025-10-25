"""Pluggable serializers for structured data transmission."""

from .json import JSONSerializer
from .msgpack import MsgPackSerializer
from .protobuf import ProtobufSerializer

__all__: list[str] = ["JSONSerializer", "MsgPackSerializer", "ProtobufSerializer"]
