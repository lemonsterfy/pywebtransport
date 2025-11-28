"""Unit tests for the pywebtransport.pubsub.exceptions module."""

import pytest

from pywebtransport import WebTransportError
from pywebtransport.pubsub import NotSubscribedError, PubSubError, SubscriptionFailedError


@pytest.mark.parametrize(
    "exception_class, base_class",
    [(PubSubError, WebTransportError), (NotSubscribedError, PubSubError), (SubscriptionFailedError, PubSubError)],
)
def test_exception_inheritance_and_instantiation(
    exception_class: type[WebTransportError], base_class: type[Exception]
) -> None:
    message = f"This is a test for {exception_class.__name__}"

    error = exception_class(message=message)

    assert issubclass(exception_class, base_class)
    assert isinstance(error, base_class)
    assert message in str(error)
