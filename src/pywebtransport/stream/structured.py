"""High-level wrapper for structured data over a reliable stream."""

from __future__ import annotations

import asyncio
import struct
from typing import TYPE_CHECKING, Any

from pywebtransport.constants import DEFAULT_MAX_MESSAGE_SIZE
from pywebtransport.exceptions import ConfigurationError, SerializationError, StreamError
from pywebtransport.types import Serializer

if TYPE_CHECKING:
    from pywebtransport.stream.stream import WebTransportStream


__all__: list[str] = ["StructuredStream"]


class StructuredStream:
    """A high-level wrapper for sending and receiving structured objects."""

    _HEADER_FORMAT = "!HI"
    _HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)

    def __init__(
        self,
        *,
        stream: WebTransportStream,
        serializer: Serializer,
        registry: dict[int, type[Any]],
        max_message_size: int = DEFAULT_MAX_MESSAGE_SIZE,
    ) -> None:
        """Initialize the structured stream."""
        if len(set(registry.values())) != len(registry):
            raise ConfigurationError(message="Types in the structured stream registry must be unique.")

        self._stream = stream
        self._serializer = serializer
        self._registry = registry
        self._max_message_size = max_message_size
        self._class_to_id = {v: k for k, v in registry.items()}

    @property
    def is_closed(self) -> bool:
        """Check if the underlying stream is closed."""
        return self._stream.is_closed

    @property
    def stream_id(self) -> int:
        """Get the underlying stream's ID."""
        return self._stream.stream_id

    async def close(self) -> None:
        """Close the underlying stream."""
        await self._stream.close()

    async def receive_obj(self) -> Any:
        """Receive, deserialize, and return a Python object from the stream."""
        try:
            header_bytes = await self._stream.readexactly(n=self._HEADER_SIZE)
        except asyncio.IncompleteReadError as e:
            raise StreamError(message="Stream closed while waiting for message header.") from e

        type_id, payload_len = struct.unpack(self._HEADER_FORMAT, header_bytes)

        if payload_len > self._max_message_size:
            await self._stream.abort()
            raise SerializationError(
                message=f"Incoming message size {payload_len} exceeds the configured limit of {self._max_message_size}."
            )

        message_class = self._registry.get(type_id)
        if message_class is None:
            raise SerializationError(message=f"Received unknown message type ID: {type_id}")

        try:
            payload = await self._stream.readexactly(n=payload_len)
        except asyncio.IncompleteReadError as e:
            raise StreamError(
                message=(
                    f"Stream closed prematurely while reading payload of size {payload_len} " f"for type ID {type_id}."
                )
            ) from e

        return self._serializer.deserialize(data=payload, obj_type=message_class)

    async def send_obj(self, *, obj: Any) -> None:
        """Serialize and send a Python object over the stream."""
        obj_type = type(obj)
        type_id = self._class_to_id.get(obj_type)
        if type_id is None:
            raise SerializationError(message=f"Object of type '{obj_type.__name__}' is not registered.")

        payload = self._serializer.serialize(obj=obj)
        payload_len = len(payload)
        header = struct.pack(self._HEADER_FORMAT, type_id, payload_len)

        await self._stream.write(data=header + payload)

    def __aiter__(self) -> "StructuredStream":
        """Return self as the asynchronous iterator."""
        return self

    async def __anext__(self) -> Any:
        """Receive the next object in the async iteration."""
        try:
            return await self.receive_obj()
        except StreamError:
            raise StopAsyncIteration
