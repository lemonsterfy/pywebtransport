"""High-level wrapper for structured data over datagrams."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from pywebtransport.exceptions import ConfigurationError, SerializationError
from pywebtransport.types import Serializer

if TYPE_CHECKING:
    from pywebtransport.datagram.transport import WebTransportDatagramTransport


__all__: list[str] = ["StructuredDatagramTransport"]


class StructuredDatagramTransport:
    """Send and receive structured objects over datagrams."""

    _HEADER_FORMAT = "!H"
    _HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)

    def __init__(
        self,
        *,
        datagram_transport: WebTransportDatagramTransport,
        serializer: Serializer,
        registry: dict[int, type[Any]],
    ) -> None:
        """Initialize the structured datagram transport."""
        if len(set(registry.values())) != len(registry):
            raise ConfigurationError(message="Types in the structured datagram registry must be unique.")

        self._datagram_transport = datagram_transport
        self._serializer = serializer
        self._registry = registry
        self._class_to_id = {v: k for k, v in registry.items()}

    @property
    def is_closed(self) -> bool:
        """Check if the underlying datagram transport is closed."""
        return self._datagram_transport.is_closed

    async def close(self) -> None:
        """Close the underlying datagram transport."""
        await self._datagram_transport.close()

    async def receive_obj(self, *, timeout: float | None = None) -> Any:
        """Receive and deserialize a Python object from a datagram."""
        datagram = await self._datagram_transport.receive(timeout=timeout)

        header_bytes, payload = datagram[: self._HEADER_SIZE], datagram[self._HEADER_SIZE :]
        type_id = struct.unpack(self._HEADER_FORMAT, header_bytes)[0]
        message_class = self._registry.get(type_id)

        if message_class is None:
            raise SerializationError(message=f"Received unknown message type ID: {type_id}")

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
            raise SerializationError(message=f"Object of type '{obj_type.__name__}' is not registered.")

        header = struct.pack(self._HEADER_FORMAT, type_id)
        payload = self._serializer.serialize(obj=obj)

        await self._datagram_transport.send(data=header + payload, priority=priority, ttl=ttl)
