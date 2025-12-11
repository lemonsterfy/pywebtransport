"""Unit tests for the pywebtransport._protocol.events module."""

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from pywebtransport._protocol.events import (
    CapsuleReceived,
    CleanupH3Stream,
    CloseQuicConnection,
    CompleteUserFuture,
    ConnectionClose,
    ConnectStreamClosed,
    CreateH3Session,
    CreateQuicStream,
    DatagramReceived,
    Effect,
    EmitConnectionEvent,
    EmitSessionEvent,
    EmitStreamEvent,
    FailUserFuture,
    GoawayReceived,
    H3Event,
    HeadersReceived,
    InternalBindH3Session,
    InternalBindQuicStream,
    InternalCleanupEarlyEvents,
    InternalCleanupResources,
    InternalFailH3Session,
    InternalFailQuicStream,
    InternalReturnStreamData,
    LogH3Frame,
    ProtocolEvent,
    RescheduleQuicTimer,
    ResetQuicStream,
    SendH3Capsule,
    SendH3Datagram,
    SendH3Goaway,
    SendH3Headers,
    SendQuicData,
    SendQuicDatagram,
    SettingsReceived,
    StopQuicStream,
    TransportConnectionTerminated,
    TransportDatagramFrameReceived,
    TransportHandshakeCompleted,
    TransportQuicParametersReceived,
    TransportQuicTimerFired,
    TransportStreamDataReceived,
    TransportStreamReset,
    TriggerQuicTimer,
    UserAcceptSession,
    UserCloseSession,
    UserConnectionGracefulClose,
    UserCreateSession,
    UserCreateStream,
    UserEvent,
    UserGetConnectionDiagnostics,
    UserGetSessionDiagnostics,
    UserGetStreamDiagnostics,
    UserGrantDataCredit,
    UserGrantStreamsCredit,
    UserRejectSession,
    UserResetStream,
    UserSendDatagram,
    UserSendStreamData,
    UserStopStream,
    UserStreamRead,
    WebTransportStreamDataReceived,
)


@pytest.fixture
def mock_exception() -> Exception:
    return ValueError("Test Exception")


@pytest.fixture
def mock_future(mocker: MockerFixture) -> MagicMock:
    return mocker.create_autospec(asyncio.Future, instance=True)


@pytest.mark.parametrize(
    "effect_class, kwargs, expected_attrs",
    [
        (CleanupH3Stream, {"stream_id": 4}, {"stream_id": 4}),
        (CloseQuicConnection, {"error_code": 100, "reason": "test close"}, {"error_code": 100, "reason": "test close"}),
        (CompleteUserFuture, {"value": "result"}, {"value": "result"}),
        (
            CreateH3Session,
            {
                "session_id": 1,
                "path": "/test",
                "headers": {b":path": b"/test"},
                "create_future": "mock_future_placeholder",
            },
            {
                "session_id": 1,
                "path": "/test",
                "headers": {b":path": b"/test"},
                "create_future": "mock_future_placeholder",
            },
        ),
        (
            CreateQuicStream,
            {"session_id": 1, "is_unidirectional": True, "create_future": "mock_future_placeholder"},
            {"session_id": 1, "is_unidirectional": True, "create_future": "mock_future_placeholder"},
        ),
        (
            EmitConnectionEvent,
            {"event_type": "connected", "data": {"key": "value"}},
            {"event_type": "connected", "data": {"key": "value"}},
        ),
        (
            EmitSessionEvent,
            {"session_id": 1, "event_type": "opened", "data": {}},
            {"session_id": 1, "event_type": "opened", "data": {}},
        ),
        (
            EmitStreamEvent,
            {"stream_id": 4, "event_type": "data_received", "data": {"len": 10}},
            {"stream_id": 4, "event_type": "data_received", "data": {"len": 10}},
        ),
        (FailUserFuture, {"exception": "mock_exception_placeholder"}, {"exception": "mock_exception_placeholder"}),
        (
            LogH3Frame,
            {"category": "test", "event": "frame", "data": {"id": 1}},
            {"category": "test", "event": "frame", "data": {"id": 1}},
        ),
        (RescheduleQuicTimer, {}, {}),
        (ResetQuicStream, {"stream_id": 4, "error_code": 100}, {"stream_id": 4, "error_code": 100}),
        (
            SendH3Capsule,
            {"stream_id": 1, "capsule_type": 0x01, "capsule_data": b"cap"},
            {"stream_id": 1, "capsule_type": 0x01, "capsule_data": b"cap"},
        ),
        (SendH3Datagram, {"stream_id": 1, "data": b"dgram"}, {"stream_id": 1, "data": b"dgram"}),
        (SendH3Goaway, {}, {}),
        (
            SendH3Headers,
            {"stream_id": 1, "status": 404, "end_stream": True},
            {"stream_id": 1, "status": 404, "end_stream": True},
        ),
        (
            SendQuicData,
            {"stream_id": 4, "data": b"data", "end_stream": False},
            {"stream_id": 4, "data": b"data", "end_stream": False},
        ),
        (SendQuicDatagram, {"data": b"dgram"}, {"data": b"dgram"}),
        (StopQuicStream, {"stream_id": 4, "error_code": 100}, {"stream_id": 4, "error_code": 100}),
        (TriggerQuicTimer, {}, {}),
    ],
)
def test_effects(
    effect_class: Callable[..., Effect],
    kwargs: dict[str, Any],
    expected_attrs: dict[str, Any],
    mock_future: MagicMock,
    mock_exception: Exception,
) -> None:
    processed_kwargs: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value == "mock_future_placeholder":
            processed_kwargs[key] = mock_future
        elif value == "mock_exception_placeholder":
            processed_kwargs[key] = mock_exception
        else:
            processed_kwargs[key] = value

    processed_expected: dict[str, Any] = {}
    for key, value in expected_attrs.items():
        if value == "mock_future_placeholder":
            processed_expected[key] = mock_future
        elif value == "mock_exception_placeholder":
            processed_expected[key] = mock_exception
        else:
            processed_expected[key] = value

    if effect_class in (CompleteUserFuture, FailUserFuture):
        if "future" not in processed_kwargs:
            processed_kwargs["future"] = mock_future
        if "future" not in processed_expected:
            processed_expected["future"] = mock_future

    effect = effect_class(**processed_kwargs)

    assert isinstance(effect, Effect)
    for attr, expected_value in processed_expected.items():
        assert getattr(effect, attr) == expected_value


@pytest.mark.parametrize(
    "event_class, kwargs, expected_attrs",
    [
        (
            CapsuleReceived,
            {"capsule_data": b"capsule", "capsule_type": 0x01, "stream_id": 1},
            {"capsule_data": b"capsule", "capsule_type": 0x01, "stream_id": 1},
        ),
        (ConnectStreamClosed, {"stream_id": 1}, {"stream_id": 1}),
        (DatagramReceived, {"data": b"datagram", "stream_id": 1}, {"data": b"datagram", "stream_id": 1}),
        (GoawayReceived, {}, {}),
        (
            HeadersReceived,
            {"headers": {b":status": b"200"}, "stream_id": 1, "stream_ended": False},
            {"headers": {b":status": b"200"}, "stream_id": 1, "stream_ended": False},
        ),
        (SettingsReceived, {"settings": {0x01: 0x01}}, {"settings": {0x01: 0x01}}),
        (
            WebTransportStreamDataReceived,
            {"data": b"data", "control_stream_id": 1, "stream_id": 4, "stream_ended": True},
            {"data": b"data", "control_stream_id": 1, "stream_id": 4, "stream_ended": True},
        ),
    ],
)
def test_h3_events(event_class: Callable[..., H3Event], kwargs: dict[str, Any], expected_attrs: dict[str, Any]) -> None:
    event = event_class(**kwargs)

    assert isinstance(event, H3Event)
    for attr, expected_value in expected_attrs.items():
        assert getattr(event, attr) == expected_value


@pytest.mark.parametrize(
    "event_class, kwargs, expected_attrs",
    [
        (
            InternalBindH3Session,
            {"session_id": 1, "control_stream_id": 2, "future": "mock_future_placeholder"},
            {"session_id": 1, "control_stream_id": 2, "future": "mock_future_placeholder"},
        ),
        (
            InternalBindQuicStream,
            {"stream_id": 1, "session_id": 1, "is_unidirectional": True, "future": "mock_future_placeholder"},
            {"stream_id": 1, "session_id": 1, "is_unidirectional": True, "future": "mock_future_placeholder"},
        ),
        (InternalCleanupEarlyEvents, {}, {}),
        (InternalCleanupResources, {}, {}),
        (
            InternalFailH3Session,
            {"session_id": 1, "exception": "mock_exception_placeholder", "future": "mock_future_placeholder"},
            {"session_id": 1, "exception": "mock_exception_placeholder", "future": "mock_future_placeholder"},
        ),
        (
            InternalFailQuicStream,
            {
                "session_id": 1,
                "is_unidirectional": True,
                "exception": "mock_exception_placeholder",
                "future": "mock_future_placeholder",
            },
            {
                "session_id": 1,
                "is_unidirectional": True,
                "exception": "mock_exception_placeholder",
                "future": "mock_future_placeholder",
            },
        ),
        (InternalReturnStreamData, {"stream_id": 1, "data": b"returned"}, {"stream_id": 1, "data": b"returned"}),
        (
            TransportConnectionTerminated,
            {"error_code": 100, "reason_phrase": "test reason"},
            {"error_code": 100, "reason_phrase": "test reason"},
        ),
        (TransportDatagramFrameReceived, {"data": b"datagram_data"}, {"data": b"datagram_data"}),
        (TransportHandshakeCompleted, {}, {}),
        (
            TransportQuicParametersReceived,
            {"remote_max_datagram_frame_size": 1500},
            {"remote_max_datagram_frame_size": 1500},
        ),
        (TransportQuicTimerFired, {}, {}),
        (
            TransportStreamDataReceived,
            {"data": b"stream_data", "end_stream": True, "stream_id": 4},
            {"data": b"stream_data", "end_stream": True, "stream_id": 4},
        ),
        (TransportStreamReset, {"error_code": 101, "stream_id": 4}, {"error_code": 101, "stream_id": 4}),
    ],
)
def test_internal_protocol_events(
    event_class: Callable[..., ProtocolEvent],
    kwargs: dict[str, Any],
    expected_attrs: dict[str, Any],
    mock_future: MagicMock,
    mock_exception: Exception,
) -> None:
    processed_kwargs: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value == "mock_future_placeholder":
            processed_kwargs[key] = mock_future
        elif value == "mock_exception_placeholder":
            processed_kwargs[key] = mock_exception
        else:
            processed_kwargs[key] = value

    processed_expected: dict[str, Any] = {}
    for key, value in expected_attrs.items():
        if value == "mock_future_placeholder":
            processed_expected[key] = mock_future
        elif value == "mock_exception_placeholder":
            processed_expected[key] = mock_exception
        else:
            processed_expected[key] = value

    event = event_class(**processed_kwargs)

    assert isinstance(event, ProtocolEvent)
    for attr, expected_value in processed_expected.items():
        assert getattr(event, attr) == expected_value


@pytest.mark.parametrize(
    "event_class, kwargs, expected_attrs",
    [
        (ConnectionClose, {"error_code": 100, "reason": "closing"}, {"error_code": 100, "reason": "closing"}),
        (UserAcceptSession, {"session_id": 1}, {"session_id": 1}),
        (
            UserCloseSession,
            {"session_id": 1, "error_code": 100, "reason": "test"},
            {"session_id": 1, "error_code": 100, "reason": "test"},
        ),
        (UserConnectionGracefulClose, {}, {}),
        (
            UserCreateSession,
            {"path": "/test", "headers": {b":path": b"/test"}},
            {"path": "/test", "headers": {b":path": b"/test"}},
        ),
        (UserCreateStream, {"session_id": 1, "is_unidirectional": True}, {"session_id": 1, "is_unidirectional": True}),
        (UserGetConnectionDiagnostics, {}, {}),
        (UserGetSessionDiagnostics, {"session_id": 1}, {"session_id": 1}),
        (UserGetStreamDiagnostics, {"stream_id": 4}, {"stream_id": 4}),
        (UserGrantDataCredit, {"session_id": 1, "max_data": 1024}, {"session_id": 1, "max_data": 1024}),
        (
            UserGrantStreamsCredit,
            {"session_id": 1, "max_streams": 10, "is_unidirectional": False},
            {"session_id": 1, "max_streams": 10, "is_unidirectional": False},
        ),
        (UserRejectSession, {"session_id": 1, "status_code": 404}, {"session_id": 1, "status_code": 404}),
        (UserResetStream, {"stream_id": 4, "error_code": 100}, {"stream_id": 4, "error_code": 100}),
        (UserSendDatagram, {"session_id": 1, "data": b"datagram"}, {"session_id": 1, "data": b"datagram"}),
        (
            UserSendStreamData,
            {"stream_id": 4, "data": b"data", "end_stream": True},
            {"stream_id": 4, "data": b"data", "end_stream": True},
        ),
        (UserStopStream, {"stream_id": 4, "error_code": 100}, {"stream_id": 4, "error_code": 100}),
        (UserStreamRead, {"stream_id": 4, "max_bytes": 1024}, {"stream_id": 4, "max_bytes": 1024}),
    ],
)
def test_user_events(
    event_class: Callable[..., UserEvent[Any]],
    kwargs: dict[str, Any],
    expected_attrs: dict[str, Any],
    mock_future: MagicMock,
) -> None:
    kwargs_with_future = {"future": mock_future, **kwargs}
    expected_with_future = {"future": mock_future, **expected_attrs}

    event = event_class(**kwargs_with_future)

    assert isinstance(event, UserEvent)
    for attr, expected_value in expected_with_future.items():
        assert getattr(event, attr) == expected_value
