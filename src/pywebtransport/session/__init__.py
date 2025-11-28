"""Core abstraction for a logical WebTransport session."""

from .session import SessionDiagnostics, WebTransportSession

__all__: list[str] = ["SessionDiagnostics", "WebTransportSession"]
