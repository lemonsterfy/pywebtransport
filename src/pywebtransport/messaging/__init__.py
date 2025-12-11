"""High-level structured messaging over streams and datagrams."""

from .datagram import StructuredDatagramTransport
from .stream import StructuredStream

__all__: list[str] = ["StructuredDatagramTransport", "StructuredStream"]
