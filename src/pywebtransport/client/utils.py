"""Shared utility functions for client-side components."""

from __future__ import annotations

import urllib.parse

from pywebtransport.constants import WEBTRANSPORT_DEFAULT_PORT, WEBTRANSPORT_SCHEME
from pywebtransport.types import URL, URLParts

__all__: list[str] = ["parse_webtransport_url", "validate_url"]


def parse_webtransport_url(*, url: URL) -> URLParts:
    """Parse a WebTransport URL into its host, port, and path components."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != WEBTRANSPORT_SCHEME:
        raise ValueError(f"Unsupported scheme '{parsed.scheme}'. Must be '{WEBTRANSPORT_SCHEME}'")

    if not parsed.hostname:
        raise ValueError("Missing hostname in URL")

    port = parsed.port or WEBTRANSPORT_DEFAULT_PORT

    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"

    return (parsed.hostname, port, path)


def validate_url(*, url: URL) -> bool:
    """Validate the format of a WebTransport URL."""
    try:
        parse_webtransport_url(url=url)
        return True
    except ValueError:
        return False
