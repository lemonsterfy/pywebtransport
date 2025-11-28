# API Reference: serializer

This document provides a reference for the `pywebtransport.serializer` subpackage, which provides pluggable serializers for structured data transmission.

---

## JSONSerializer Class

A serializer that encodes and decodes objects using the JSON format. It supports automatic conversion between dictionaries and Python dataclasses.

### Constructor

- **`def **init**(self, **kwargs: Any) -> None`**: Initializes the JSON serializer. Keyword arguments are passed directly to `json.dumps`.

### Instance Methods

- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any`**: Deserializes a JSON byte string into a Python object. If `obj_type` is a dataclass type, it attempts to recursively convert the dictionary to that type.
- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes a Python object into a JSON byte string (UTF-8 encoded). Automatically handles dataclasses.

## MsgPackSerializer Class

A serializer that encodes and decodes objects using the MessagePack format. It supports automatic conversion between dictionaries and Python dataclasses.

### Constructor

- **`def __init__(self, *, pack_kwargs: dict[str, Any] | None = None, unpack_kwargs: dict[str, Any] | None = None) -> None`**: Initializes the MsgPack serializer.
  - `pack_kwargs`: Dictionary of keyword arguments passed to `msgpack.packb`.
  - `unpack_kwargs`: Dictionary of keyword arguments passed to `msgpack.unpackb`.

### Instance Methods

- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any`**: Deserializes a MsgPack byte string into a Python object. If `obj_type` is a dataclass type, it attempts to recursively convert the data.
- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes a Python object into a MsgPack byte string. Automatically handles dataclasses.

## ProtobufSerializer Class

A serializer that encodes and decodes objects using the Protocol Buffers (Protobuf) format.

### Constructor

- **`def __init__(self, *, message_class: type[Message]) -> None`**: Initializes the Protobuf serializer with a specific Protobuf `Message` class. Raises `ConfigurationError` if the `protobuf` library is missing.

### Instance Methods

- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Message`**: Deserializes bytes into an instance of the configured Protobuf message class. If `obj_type` is provided, it must match the configured class.
- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes a Protobuf message object into bytes. Raises `SerializationError` if the object is not an instance of the configured message class.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
