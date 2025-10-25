"""Custom exception hierarchy for the Pub/Sub system."""

from __future__ import annotations

from pywebtransport.exceptions import WebTransportError

__all__: list[str] = ["NotSubscribedError", "PubSubError", "SubscriptionFailedError"]


class PubSubError(WebTransportError):
    """Base exception for Pub/Sub errors."""

    pass


class NotSubscribedError(PubSubError):
    """Raised when trying to operate on a topic without being subscribed."""

    pass


class SubscriptionFailedError(PubSubError):
    """Raised when subscribing to a topic fails."""

    pass
