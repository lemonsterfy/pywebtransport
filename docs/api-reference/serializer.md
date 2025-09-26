# API Reference: serializer

This document provides a reference for the `pywebtransport.serializer` subpackage, which offers a framework for serializing and deserializing structured data.

---

## JSONSerializer Class

A serializer that encodes and decodes objects using the JSON format.

### Constructor

- **`def **init**(self, **kwargs: Any) -> None`**: Initializes the JSON serializer. Keyword arguments are passed to `json.dumps`.

### Instance Methods

- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any`**: Deserializes a JSON byte string into a Python object.
- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes a Python object into a JSON byte string.

## MsgPackSerializer Class

A serializer that encodes and decodes objects using the MessagePack format.

**Note on Usage**: This is an optional feature. You must install `pywebtransport` with the `msgpack` extra: `pip install pywebtransport[msgpack]`.

### Constructor

- **`def __init__(self, *, pack_kwargs: dict[str, Any] | None = None, unpack_kwargs: dict[str, Any] | None = None) -> None`**: Initializes the MsgPack serializer.

### Instance Methods

- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Any`**: Deserializes a MsgPack byte string into a Python object.
- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes a Python object into a MsgPack byte string.

## ProtobufSerializer Class

A serializer that encodes and decodes objects using the Protocol Buffers (Protobuf) format.

**Note on Usage**: This is an optional feature. You must install `pywebtransport` with the `protobuf` extra: `pip install pywebtransport[protobuf]`.

### Constructor

- **`def __init__(self, *, message_class: type[Message]) -> None`**: Initializes the Protobuf serializer with a specific Protobuf `Message` class.

### Instance Methods

- **`def deserialize(self, *, data: bytes, obj_type: Any = None) -> Message`**: Deserializes bytes into an instance of the configured Protobuf message class.
- **`def serialize(self, *, obj: Any) -> bytes`**: Serializes a Protobuf message object into bytes.

## See Also

- **[Configuration API](config.md)**: Understand how to configure clients and servers.
- **[Constants API](constants.md)**: Review default values and protocol-level constants.
- **[Events API](events.md)**: Learn about the event system and how to use handlers.
- **[Exceptions API](exceptions.md)**: Understand the library's error and exception hierarchy.
