"""Unit tests for the pywebtransport.datagram.structured module."""

import struct
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio

from pywebtransport import ConfigurationError, Event, SessionError, StructuredDatagramTransport, TimeoutError
from pywebtransport.exceptions import SerializationError
from pywebtransport.types import EventType


@pytest.mark.asyncio
class TestStructuredDatagramTransport:

    @pytest.fixture
    def mock_serializer(self) -> Mock:
        serializer = Mock()
        serializer.serialize.side_effect = lambda obj: str(obj).encode("utf-8")
        serializer.deserialize.side_effect = lambda data, obj_type: int(data.decode("utf-8"))
        return serializer

    @pytest.fixture
    def mock_session(self) -> Mock:
        session = Mock()
        session.is_closed = False
        session.session_id = "test_session_id"
        session.events = Mock()
        session.send_datagram = AsyncMock()
        return session

    @pytest.fixture
    def registry(self) -> dict[int, type[Any]]:
        return {1: int, 2: str}

    @pytest_asyncio.fixture
    async def transport(
        self, mock_session: Mock, mock_serializer: Mock, registry: dict[int, type[Any]]
    ) -> StructuredDatagramTransport:
        transport = StructuredDatagramTransport(session=mock_session, serializer=mock_serializer, registry=registry)
        await transport.initialize()
        return transport

    async def test_close_behavior(self, mock_session: Mock, transport: StructuredDatagramTransport) -> None:
        await transport.close()

        assert transport.is_closed
        mock_session.events.off.assert_called_once()

    async def test_close_handles_garbage_collected_session(
        self, mock_session: Mock, transport: StructuredDatagramTransport
    ) -> None:
        with patch.object(transport, "_session", return_value=None):
            await transport.close()

        assert transport.is_closed
        mock_session.events.off.assert_not_called()

    async def test_close_idempotency(self, mock_session: Mock, transport: StructuredDatagramTransport) -> None:
        await transport.close()
        await transport.close()

        mock_session.events.off.assert_called_once()

    async def test_close_uninitialized_transport(
        self, mock_session: Mock, mock_serializer: Mock, registry: dict[int, type[Any]]
    ) -> None:
        transport = StructuredDatagramTransport(session=mock_session, serializer=mock_serializer, registry=registry)

        await transport.close()

        assert transport.is_closed
        mock_session.events.off.assert_called_once()

    async def test_init_raises_configuration_error_on_duplicate_types(
        self, mock_session: Mock, mock_serializer: Mock
    ) -> None:
        registry: dict[int, type[Any]] = {1: int, 2: int}

        with pytest.raises(ConfigurationError):
            StructuredDatagramTransport(session=mock_session, serializer=mock_serializer, registry=registry)

    @pytest.mark.parametrize(
        "session_condition, expected_error_msg",
        [("closed", "parent session is closed"), ("collected", "parent session is already gone")],
    )
    async def test_initialize_session_errors(
        self,
        mock_session: Mock,
        mock_serializer: Mock,
        registry: dict[int, type[Any]],
        session_condition: str,
        expected_error_msg: str,
    ) -> None:
        if session_condition == "closed":
            mock_session.is_closed = True
            patcher = None
        else:
            patcher = patch("weakref.ref", return_value=None)

        transport = StructuredDatagramTransport(session=mock_session, serializer=mock_serializer, registry=registry)

        try:
            if session_condition == "collected":
                with patch.object(transport, "_session", return_value=None):
                    with pytest.raises(SessionError, match=expected_error_msg):
                        await transport.initialize()
            else:
                with pytest.raises(SessionError, match=expected_error_msg):
                    await transport.initialize()
        finally:
            if patcher:
                patcher.stop()

    async def test_initialize_success_and_idempotency(
        self, mock_session: Mock, transport: StructuredDatagramTransport
    ) -> None:
        mock_session.events.on.assert_called_once_with(
            event_type=EventType.DATAGRAM_RECEIVED, handler=transport._on_datagram_received
        )

        await transport.initialize()

        mock_session.events.on.assert_called_once()

    @pytest.mark.parametrize(
        "session_state, transport_state, expected_closed",
        [("active", "open", False), ("active", "closed", True), ("closed", "open", True), ("collected", "open", True)],
    )
    async def test_is_closed_property(
        self,
        mock_session: Mock,
        transport: StructuredDatagramTransport,
        session_state: str,
        transport_state: str,
        expected_closed: bool,
    ) -> None:
        if transport_state == "closed":
            await transport.close()

        if session_state == "closed":
            mock_session.is_closed = True
        elif session_state == "collected":
            with patch.object(transport, "_session", return_value=None):
                assert transport.is_closed is expected_closed
                return

        assert transport.is_closed is expected_closed

    async def test_on_datagram_received_errors(
        self, transport: StructuredDatagramTransport, mock_serializer: Mock
    ) -> None:
        header = struct.pack("!H", 1)
        payload = b"123"
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": header + payload})
        mock_serializer.deserialize.side_effect = RuntimeError("Generic failure")

        with patch("pywebtransport.datagram.structured.logger") as mock_logger:
            await transport._on_datagram_received(event)
            mock_logger.error.assert_called_once()

    @pytest.mark.parametrize(
        "event_data, closed_state, expect_process",
        [
            ({"data": struct.pack("!H", 1) + b"valid"}, False, True),
            ({"data": struct.pack("!H", 1) + b"valid"}, True, False),
            ("not a dict", False, False),
            ({}, False, False),
            ({"data": None}, False, False),
        ],
    )
    async def test_on_datagram_received_ignored_cases(
        self,
        transport: StructuredDatagramTransport,
        mock_serializer: Mock,
        event_data: Any,
        closed_state: bool,
        expect_process: bool,
    ) -> None:
        if closed_state:
            await transport.close()

        event = Event(type=EventType.DATAGRAM_RECEIVED, data=event_data)
        await transport._on_datagram_received(event)

        if expect_process:
            mock_serializer.deserialize.assert_called()
        else:
            mock_serializer.deserialize.assert_not_called()

    async def test_on_datagram_received_queue_full(
        self, mock_session: Mock, mock_serializer: Mock, registry: dict[int, type[Any]]
    ) -> None:
        transport = StructuredDatagramTransport(session=mock_session, serializer=mock_serializer, registry=registry)
        await transport.initialize(queue_size=1)
        header = struct.pack("!H", 1)
        payload = b"123"
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": header + payload})

        with patch("pywebtransport.datagram.structured.logger") as mock_logger:
            await transport._on_datagram_received(event)
            await transport._on_datagram_received(event)
            mock_logger.warning.assert_called()

    @pytest.mark.parametrize(
        "header_val, payload, error_type", [(1, b"invalid", SerializationError), (999, b"123", SerializationError)]
    )
    async def test_receive_obj_drops_bad_datagrams(
        self,
        transport: StructuredDatagramTransport,
        mock_serializer: Mock,
        header_val: int,
        payload: bytes,
        error_type: type[Exception],
    ) -> None:
        if header_val == 999:
            pass
        else:
            mock_serializer.deserialize.side_effect = error_type("fail")

        header = struct.pack("!H", header_val)
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": header + payload})

        with patch("pywebtransport.datagram.structured.logger") as mock_logger:
            await transport._on_datagram_received(event)
            mock_logger.warning.assert_called()

        with pytest.raises(TimeoutError):
            await transport.receive_obj(timeout=0.01)

    async def test_receive_obj_drops_malformed_header(self, transport: StructuredDatagramTransport) -> None:
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": b"x"})

        with patch("pywebtransport.datagram.structured.logger") as mock_logger:
            await transport._on_datagram_received(event)
            mock_logger.warning.assert_called()

        with pytest.raises(TimeoutError):
            await transport.receive_obj(timeout=0.01)

    @pytest.mark.parametrize(
        "scenario, expected_error, match",
        [
            ("uninitialized", SessionError, "not been initialized"),
            ("closed_transport", SessionError, "is closed"),
            ("poison_pill", SessionError, "closed while receiving"),
            ("timeout", TimeoutError, "Receive object timeout"),
        ],
    )
    async def test_receive_obj_errors(
        self,
        mock_session: Mock,
        mock_serializer: Mock,
        registry: dict[int, type[Any]],
        scenario: str,
        expected_error: type[Exception],
        match: str,
    ) -> None:
        transport = StructuredDatagramTransport(session=mock_session, serializer=mock_serializer, registry=registry)

        if scenario != "uninitialized":
            await transport.initialize()

        if scenario == "closed_transport":
            await transport.close()

        if scenario == "poison_pill":
            assert transport._incoming_obj_queue is not None
            transport._incoming_obj_queue.put_nowait(item=None)

        if scenario == "timeout":
            kwargs = {"timeout": 0.01}
        else:
            kwargs = {}

        with pytest.raises(expected_error, match=match):
            await transport.receive_obj(**kwargs)

    async def test_receive_obj_success(self, transport: StructuredDatagramTransport) -> None:
        header = struct.pack("!H", 1)
        payload = b"123"
        event = Event(type=EventType.DATAGRAM_RECEIVED, data={"data": header + payload})

        await transport._on_datagram_received(event)
        obj = await transport.receive_obj()

        assert obj == 123

    @pytest.mark.parametrize(
        "scenario, expected_error, match",
        [
            ("uninitialized", SessionError, "not been initialized"),
            ("session_closed", SessionError, "Session is closed"),
            ("session_collected", SessionError, "Session is closed"),
            ("unregistered_type", SerializationError, "not registered"),
        ],
    )
    async def test_send_obj_errors(
        self,
        mock_session: Mock,
        mock_serializer: Mock,
        registry: dict[int, type[Any]],
        scenario: str,
        expected_error: type[Exception],
        match: str,
    ) -> None:
        transport = StructuredDatagramTransport(session=mock_session, serializer=mock_serializer, registry=registry)

        if scenario != "uninitialized":
            await transport.initialize()

        obj: Any = 123

        if scenario == "session_closed":
            mock_session.is_closed = True
        elif scenario == "session_collected":
            patcher = patch.object(transport, "_session", return_value=None)
            patcher.start()
            self.patcher = patcher
        elif scenario == "unregistered_type":
            obj = 1.23

        try:
            with pytest.raises(expected_error, match=match):
                await transport.send_obj(obj=obj)
        finally:
            if scenario == "session_collected" and hasattr(self, "patcher"):
                self.patcher.stop()

    async def test_send_obj_success(
        self, mock_session: Mock, mock_serializer: Mock, transport: StructuredDatagramTransport
    ) -> None:
        obj = 123
        expected_header = struct.pack("!H", 1)
        expected_payload = b"123"

        await transport.send_obj(obj=obj)

        mock_serializer.serialize.assert_called_once_with(obj=obj)
        mock_session.send_datagram.assert_awaited_once_with(data=expected_header + expected_payload)
