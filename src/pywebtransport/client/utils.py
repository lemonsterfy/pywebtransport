"""Shared utility functions for client-side components."""

from __future__ import annotations

import functools
import urllib.parse

from pywebtransport.constants import DEFAULT_SECURE_PORT, WEBTRANSPORT_SCHEME
from pywebtransport.exceptions import ConfigurationError
from pywebtransport.types import URL, URLParts

__all__: list[str] = ["parse_webtransport_url", "validate_url"]


@functools.cache
def parse_webtransport_url(*, url: URL) -> URLParts:
    """Parse a WebTransport URL into its host, port, and path components."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != WEBTRANSPORT_SCHEME:
        raise ConfigurationError(
            message=f"Unsupported scheme '{parsed.scheme}'. Must be '{WEBTRANSPORT_SCHEME}'", config_key="url"
        )
    if not parsed.hostname:
        raise ConfigurationError(message="Missing hostname in URL", config_key="url")

    port = parsed.port or DEFAULT_SECURE_PORT

    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    if parsed.fragment:
        path += f"#{parsed.fragment}"
    return (parsed.hostname, port, path)


def validate_url(*, url: URL) -> bool:
    """Validate the format of a WebTransport URL."""
    try:
        parse_webtransport_url(url=url)
        return True
    except Exception:
        return False
