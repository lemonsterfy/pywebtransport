"""
High-level structured data datagrams for WebTransport.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any, Type

from pywebtransport.exceptions import SerializationError
from pywebtransport.types import Serializer

if TYPE_CHECKING:
    from pywebtransport.datagram.transport import WebTransportDatagramDuplexStream


__all__ = ["StructuredDatagramStream"]


class StructuredDatagramStream:
    """A high-level wrapper for sending and receiving structured objects."""

    _HEADER_FORMAT = "!H"
    _HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)

    def __init__(
        self,
        *,
        datagram_stream: WebTransportDatagramDuplexStream,
        serializer: Serializer,
        registry: dict[int, Type[Any]],
    ):
        """Initialize the structured datagram stream."""
        self._datagram_stream = datagram_stream
        self._serializer = serializer
        self._registry = registry
        self._class_to_id = {v: k for k, v in registry.items()}

    @property
    def is_closed(self) -> bool:
        """Check if the underlying datagram stream is closed."""
        return self._datagram_stream.is_closed

    async def close(self) -> None:
        """Close the underlying datagram stream."""
        await self._datagram_stream.close()

    async def receive_obj(self, *, timeout: float | None = None) -> Any:
        """Receive and deserialize a Python object from a datagram."""
        datagram = await self._datagram_stream.receive(timeout=timeout)

        header_bytes, payload = datagram[: self._HEADER_SIZE], datagram[self._HEADER_SIZE :]
        type_id = struct.unpack(self._HEADER_FORMAT, header_bytes)[0]
        message_class = self._registry.get(type_id)

        if message_class is None:
            raise SerializationError(f"Received unknown message type ID: {type_id}")

        return self._serializer.deserialize(data=payload, obj_type=message_class)

    async def send_obj(
        self,
        *,
        obj: Any,
        priority: int = 0,
        ttl: float | None = None,
    ) -> None:
        """Serialize and send a Python object as a datagram."""
        obj_type = type(obj)
        type_id = self._class_to_id.get(obj_type)
        if type_id is None:
            raise SerializationError(f"Object of type '{obj_type.__name__}' is not registered.")

        header = struct.pack(self._HEADER_FORMAT, type_id)
        payload = self._serializer.serialize(obj=obj)

        await self._datagram_stream.send(data=header + payload, priority=priority, ttl=ttl)
