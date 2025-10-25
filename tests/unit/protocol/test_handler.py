"""Unit tests for the pywebtransport.protocol.handler module."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aioquic.quic.events import StreamDataReceived, StreamReset
from pytest_mock import MockerFixture

from pywebtransport import Event, ProtocolError
from pywebtransport.connection import WebTransportConnection
from pywebtransport.exceptions import FlowControlError
from pywebtransport.protocol import WebTransportProtocolHandler
from pywebtransport.protocol.events import (
    CapsuleReceived,
    DatagramReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.types import ConnectionState, EventType, SessionState, StreamState


@pytest.fixture
def handler(
    mock_quic: MagicMock,
    mock_connection: MagicMock,
    mock_trigger_transmission: MagicMock,
    mock_h3_engine: MagicMock,
    mock_session_tracker: MagicMock,
    mock_stream_tracker: MagicMock,
    mock_pending_event_manager: MagicMock,
) -> WebTransportProtocolHandler:
    return WebTransportProtocolHandler(
        quic_connection=mock_quic,
        trigger_transmission=mock_trigger_transmission,
        is_client=True,
        connection=mock_connection,
    )


@pytest.fixture
def mock_connection(mocker: MockerFixture) -> MagicMock:
    mock = mocker.create_autospec(WebTransportConnection, instance=True)
    config_mock = MagicMock()
    config_mock.max_datagram_frame_size = 65535
    mock.config = config_mock
    mocker.patch("weakref.ref", return_value=lambda: mock)
    return cast(MagicMock, mock)


@pytest.fixture
def mock_h3_engine(mocker: MockerFixture) -> MagicMock:
    return cast(
        MagicMock,
        mocker.patch(
            "pywebtransport.protocol.handler.WebTransportH3Engine",
            autospec=True,
        ).return_value,
    )


@pytest.fixture
def mock_pending_event_manager(mocker: MockerFixture) -> MagicMock:
    return cast(
        MagicMock,
        mocker.patch(
            "pywebtransport.protocol.handler._PendingEventManager",
            autospec=True,
        ).return_value,
    )


@pytest.fixture
def mock_quic(mocker: MockerFixture) -> MagicMock:
    mock = mocker.create_autospec(MagicMock, instance=True)
    mock.configuration = MagicMock()
    mock._quic_logger = MagicMock()
    mock.get_next_available_stream_id = MagicMock(return_value=0)
    mock.send_stream_data = MagicMock()
    return cast(MagicMock, mock)


@pytest.fixture
def mock_session_tracker(mocker: MockerFixture) -> MagicMock:
    return cast(
        MagicMock,
        mocker.patch(
            "pywebtransport.protocol.handler._ProtocolSessionTracker",
            autospec=True,
        ).return_value,
    )


@pytest.fixture
def mock_stream_tracker(mocker: MockerFixture) -> MagicMock:
    return cast(
        MagicMock,
        mocker.patch(
            "pywebtransport.protocol.handler._ProtocolStreamTracker",
            autospec=True,
        ).return_value,
    )


@pytest.fixture
def mock_trigger_transmission() -> MagicMock:
    return MagicMock()


class TestH3EventRouting:
    @pytest.mark.asyncio
    async def test_handle_datagram_received(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_emit = mocker.patch.object(handler, "emit", new_callable=AsyncMock)
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = MagicMock()
        event = DatagramReceived(stream_id=0, data=b"datagram")

        await handler._handle_datagram_received(event=event)

        mock_emit.assert_awaited_once_with(
            event_type=EventType.DATAGRAM_RECEIVED,
            data={"session_id": "s1", "data": b"datagram"},
        )
        assert handler._stats["bytes_received"] == 8
        assert handler._stats["datagrams_received"] == 1

    @pytest.mark.asyncio
    async def test_handle_datagram_received_buffers_if_no_session(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_pending_event_manager: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_emit = mocker.patch.object(handler, "emit", new_callable=AsyncMock)
        mock_session_tracker.get_session_by_control_stream.return_value = None
        event = DatagramReceived(stream_id=0, data=b"datagram")

        await handler._handle_datagram_received(event=event)

        mock_emit.assert_not_awaited()
        mock_pending_event_manager.buffer_event.assert_called_once_with(session_stream_id=0, event=event)

    @pytest.mark.asyncio
    async def test_handle_datagram_received_buffers_if_session_info_missing(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_pending_event_manager: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_emit = mocker.patch.object(handler, "emit", new_callable=AsyncMock)
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = None
        event = DatagramReceived(stream_id=0, data=b"datagram")

        await handler._handle_datagram_received(event=event)

        mock_emit.assert_not_awaited()
        mock_pending_event_manager.buffer_event.assert_called_once_with(session_stream_id=0, event=event)

    @pytest.mark.asyncio
    async def test_handle_datagram_received_no_record_activity_method(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_connection: MagicMock,
    ) -> None:
        del mock_connection.record_activity
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = MagicMock()
        event = DatagramReceived(stream_id=0, data=b"datagram")
        await handler._handle_datagram_received(event=event)

    @pytest.mark.asyncio
    async def test_handle_datagram_received_records_activity(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_connection: MagicMock,
    ) -> None:
        mock_connection.record_activity = MagicMock()
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = MagicMock()
        event = DatagramReceived(stream_id=0, data=b"datagram")

        await handler._handle_datagram_received(event=event)
        mock_connection.record_activity.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_h3_event_buffers_unhandled_stream_data(
        self,
        handler: WebTransportProtocolHandler,
        mock_stream_tracker: MagicMock,
        mock_pending_event_manager: MagicMock,
    ) -> None:
        event = WebTransportStreamDataReceived(
            stream_id=4,
            control_stream_id=0,
            data=b"data",
            stream_ended=True,
        )
        mock_stream_tracker.handle_webtransport_stream_data.return_value = event

        await handler._handle_h3_event(h3_event=event)

        mock_pending_event_manager.buffer_event.assert_called_once_with(session_stream_id=0, event=event)

    @pytest.mark.asyncio
    async def test_handle_h3_event_routes_capsule(
        self, handler: WebTransportProtocolHandler, mock_session_tracker: MagicMock
    ) -> None:
        event = CapsuleReceived(stream_id=0, capsule_type=1, capsule_data=b"")

        await handler._handle_h3_event(h3_event=event)

        mock_session_tracker.handle_capsule_received.assert_awaited_once_with(event=event)

    @pytest.mark.asyncio
    async def test_handle_h3_event_routes_headers(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_pending_event_manager: MagicMock,
    ) -> None:
        event = HeadersReceived(stream_id=0, headers={}, stream_ended=False)
        mock_session_tracker.handle_headers_received.return_value = "s1"

        await handler._handle_h3_event(h3_event=event)

        mock_session_tracker.handle_headers_received.assert_awaited_once()
        mock_pending_event_manager.process_pending_events.assert_called_once_with(connect_stream_id=0)

    @pytest.mark.asyncio
    async def test_handle_h3_event_routes_headers_no_session_id(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_pending_event_manager: MagicMock,
    ) -> None:
        event = HeadersReceived(stream_id=0, headers={}, stream_ended=False)
        mock_session_tracker.handle_headers_received.return_value = None

        await handler._handle_h3_event(h3_event=event)

        mock_session_tracker.handle_headers_received.assert_awaited_once()
        mock_pending_event_manager.process_pending_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_h3_event_routes_stream_data(
        self, handler: WebTransportProtocolHandler, mock_stream_tracker: MagicMock
    ) -> None:
        event = WebTransportStreamDataReceived(
            stream_id=4,
            control_stream_id=0,
            data=b"data",
            stream_ended=True,
        )
        mock_stream_tracker.handle_webtransport_stream_data.return_value = None

        await handler._handle_h3_event(h3_event=event)

        mock_stream_tracker.handle_webtransport_stream_data.assert_awaited_once_with(event=event)

    @pytest.mark.asyncio
    async def test_handle_h3_event_unhandled_event_type(
        self, handler: WebTransportProtocolHandler, mocker: MockerFixture
    ) -> None:
        class UnhandledH3Event(H3Event):
            pass

        mock_logger = mocker.patch("pywebtransport.protocol.handler.logger")
        event = UnhandledH3Event()
        await handler._handle_h3_event(h3_event=event)
        mock_logger.debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_stream_reset_routes_to_session_tracker(
        self, handler: WebTransportProtocolHandler, mock_session_tracker: MagicMock
    ) -> None:
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        event = StreamReset(stream_id=0, error_code=1)

        await handler._handle_stream_reset(event=event)

        mock_session_tracker.handle_stream_reset.assert_awaited_once_with(stream_id=0, error_code=1)

    @pytest.mark.asyncio
    async def test_handle_stream_reset_routes_to_stream_tracker(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_stream_tracker: MagicMock,
    ) -> None:
        mock_session_tracker.get_session_by_control_stream.return_value = None
        event = StreamReset(stream_id=4, error_code=1)

        await handler._handle_stream_reset(event=event)

        mock_stream_tracker.handle_stream_reset.assert_called_once_with(stream_id=4)

    @pytest.mark.asyncio
    async def test_on_capsule_received(
        self, handler: WebTransportProtocolHandler, mock_session_tracker: MagicMock
    ) -> None:
        capsule = CapsuleReceived(stream_id=0, capsule_type=1, capsule_data=b"")
        event = Event(type=EventType.CAPSULE_RECEIVED, data=capsule)
        await handler._on_capsule_received(event)
        mock_session_tracker.handle_capsule_received.assert_awaited_once_with(event=capsule)

    @pytest.mark.asyncio
    async def test_on_capsule_received_ignores_wrong_event_data_type(
        self, handler: WebTransportProtocolHandler, mock_session_tracker: MagicMock
    ) -> None:
        event = Event(type=EventType.CAPSULE_RECEIVED, data="not a capsule")
        await handler._on_capsule_received(event)
        mock_session_tracker.handle_capsule_received.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_buffered_events_delegates_correctly(
        self,
        handler: WebTransportProtocolHandler,
        mock_stream_tracker: MagicMock,
        mock_session_tracker: MagicMock,
    ) -> None:
        stream_event = WebTransportStreamDataReceived(
            stream_id=4,
            control_stream_id=0,
            data=b"data",
            stream_ended=True,
        )
        datagram_event = DatagramReceived(stream_id=0, data=b"dg")
        events: list[tuple[float, H3Event]] = [(123.0, stream_event), (124.0, datagram_event)]

        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = MagicMock()

        await handler._process_buffered_events(events)

        mock_stream_tracker.handle_webtransport_stream_data.assert_awaited_once_with(event=stream_event)
        mock_session_tracker.get_session_by_control_stream.assert_called_once_with(stream_id=0)

    @pytest.mark.asyncio
    async def test_process_buffered_events_handles_datagram_only(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        mock_emit = mocker.patch.object(handler, "emit", new_callable=AsyncMock)
        datagram_event = DatagramReceived(stream_id=0, data=b"dg")
        events: list[tuple[float, H3Event]] = [(124.0, datagram_event)]
        mock_session_tracker.get_session_by_control_stream.return_value = "s1"
        mock_session_tracker.get_session_info.return_value = MagicMock()
        await handler._process_buffered_events(events)
        mock_emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_buffered_events_handles_stream_data_only(
        self, handler: WebTransportProtocolHandler, mock_stream_tracker: MagicMock
    ) -> None:
        stream_event = WebTransportStreamDataReceived(stream_id=4, control_stream_id=0, data=b"data", stream_ended=True)
        events: list[tuple[float, H3Event]] = [(123.0, stream_event)]
        await handler._process_buffered_events(events)
        mock_stream_tracker.handle_webtransport_stream_data.assert_awaited_once_with(event=stream_event)

    @pytest.mark.asyncio
    async def test_process_buffered_events_with_no_events(self, handler: WebTransportProtocolHandler) -> None:
        await handler._process_buffered_events([])


class TestWebTransportProtocolHandler:
    def test_abort_stream(self, handler: WebTransportProtocolHandler, mock_stream_tracker: MagicMock) -> None:
        handler.abort_stream(stream_id=4, error_code=123)
        mock_stream_tracker.abort_stream.assert_called_once_with(stream_id=4, error_code=123)

    def test_accept_webtransport_session(
        self, handler: WebTransportProtocolHandler, mock_session_tracker: MagicMock
    ) -> None:
        handler.accept_webtransport_session(stream_id=0, session_id="s1")
        mock_session_tracker.accept_webtransport_session.assert_called_once_with(stream_id=0, session_id="s1")

    @pytest.mark.asyncio
    async def test_close(
        self,
        handler: WebTransportProtocolHandler,
        mock_pending_event_manager: MagicMock,
        mock_h3_engine: MagicMock,
    ) -> None:
        await handler.close()

        mock_pending_event_manager.close.assert_awaited_once()
        mock_h3_engine.off.assert_called_once_with(
            event_type=EventType.CAPSULE_RECEIVED,
            handler=handler._on_capsule_received,
        )

    @pytest.mark.asyncio
    async def test_close_idempotency(self, handler: WebTransportProtocolHandler) -> None:
        await handler.close()
        await handler.close()
        cast(AsyncMock, handler._pending_event_manager.close).assert_awaited_once()

    def test_close_webtransport_session(
        self, handler: WebTransportProtocolHandler, mock_session_tracker: MagicMock
    ) -> None:
        handler.close_webtransport_session(session_id="s1", code=42, reason="test")
        mock_session_tracker.close_webtransport_session.assert_called_once_with(session_id="s1", code=42, reason="test")

    def test_connection_established(
        self,
        handler: WebTransportProtocolHandler,
        mock_pending_event_manager: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        handler.connection_established()

        mock_pending_event_manager.start.assert_called_once()
        mock_trigger_transmission.assert_called_once()
        assert handler._stats["connected_at"] is not None

    def test_connection_established_noop_if_connected(
        self,
        handler: WebTransportProtocolHandler,
        mock_pending_event_manager: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        handler._connection_state = ConnectionState.CONNECTED
        handler.connection_established()
        mock_pending_event_manager.start.assert_not_called()
        mock_trigger_transmission.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_webtransport_session(
        self, handler: WebTransportProtocolHandler, mock_session_tracker: MagicMock
    ) -> None:
        mock_session_tracker.create_webtransport_session.return_value = ("s1", 0)

        result = await handler.create_webtransport_session(path="/", headers={})

        assert result == ("s1", 0)
        mock_session_tracker.create_webtransport_session.assert_awaited_once_with(path="/", headers={})

    def test_create_webtransport_stream(
        self, handler: WebTransportProtocolHandler, mock_stream_tracker: MagicMock
    ) -> None:
        mock_stream_tracker.create_webtransport_stream.return_value = 4

        result = handler.create_webtransport_stream(session_id="s1", is_unidirectional=True)

        assert result == 4
        mock_stream_tracker.create_webtransport_stream.assert_called_once_with(session_id="s1", is_unidirectional=True)

    @pytest.mark.asyncio
    async def test_handle_quic_event_noop_if_closed(
        self, handler: WebTransportProtocolHandler, mock_h3_engine: MagicMock
    ) -> None:
        await handler.close()
        event = StreamDataReceived(stream_id=0, data=b"hello", end_stream=True)
        await handler.handle_quic_event(event=event)
        mock_h3_engine.handle_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_quic_event_routes_to_h3(
        self,
        handler: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        event = StreamDataReceived(stream_id=0, data=b"hello", end_stream=True)
        mock_h3_engine.handle_event.return_value = []

        await handler.handle_quic_event(event=event)

        mock_h3_engine.handle_event.assert_awaited_once_with(event=event)
        mock_trigger_transmission.assert_called_once()

    def test_initialization(
        self,
        handler: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
        mock_session_tracker: MagicMock,
        mock_stream_tracker: MagicMock,
        mock_pending_event_manager: MagicMock,
    ) -> None:
        assert handler._session_tracker is mock_session_tracker
        assert handler._stream_tracker is mock_stream_tracker
        assert handler._pending_event_manager is mock_pending_event_manager
        mock_h3_engine.on.assert_called_once_with(
            event_type=EventType.CAPSULE_RECEIVED,
            handler=handler._on_capsule_received,
        )

    def test_initialization_no_connection(
        self,
        mock_quic: MagicMock,
        mock_h3_engine: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        handler = WebTransportProtocolHandler(
            quic_connection=mock_quic,
            trigger_transmission=mock_trigger_transmission,
            is_client=True,
            connection=None,
        )
        assert handler._connection_ref is None

    def test_quic_connection_property(self, handler: WebTransportProtocolHandler, mock_quic: MagicMock) -> None:
        assert handler.quic_connection is mock_quic

    def test_reject_session_request(
        self,
        handler: WebTransportProtocolHandler,
        mock_h3_engine: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        handler.reject_session_request(stream_id=0, status_code=403)
        mock_h3_engine.send_headers.assert_called_once_with(stream_id=0, headers={":status": "403"}, end_stream=True)
        mock_trigger_transmission.assert_called_once()

    def test_send_webtransport_datagram(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        mock_h3_engine: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        session_info = MagicMock(state=SessionState.CONNECTED, control_stream_id=0)
        mock_session_tracker.get_session_info.return_value = session_info

        handler.send_webtransport_datagram(session_id="s1", data=b"datagram")

        mock_h3_engine.send_datagram.assert_called_once_with(stream_id=0, data=b"datagram")
        mock_trigger_transmission.assert_called_once()
        assert handler._stats["bytes_sent"] == 8
        assert handler._stats["datagrams_sent"] == 1

    @pytest.mark.parametrize(
        "session_info",
        [
            None,
            MagicMock(state=SessionState.CLOSED),
        ],
    )
    def test_send_webtransport_datagram_raises_error(
        self,
        handler: WebTransportProtocolHandler,
        mock_session_tracker: MagicMock,
        session_info: MagicMock | None,
    ) -> None:
        mock_session_tracker.get_session_info.return_value = session_info
        with pytest.raises(ProtocolError):
            handler.send_webtransport_datagram(session_id="s1", data=b"datagram")

    def test_send_webtransport_stream_data(
        self,
        handler: WebTransportProtocolHandler,
        mock_stream_tracker: MagicMock,
        mock_session_tracker: MagicMock,
        mock_h3_engine: MagicMock,
        mock_trigger_transmission: MagicMock,
    ) -> None:
        stream_info = MagicMock(state=StreamState.OPEN, session_id="s1", bytes_sent=0)
        session_info = MagicMock(local_data_sent=0, peer_max_data=100)
        mock_stream_tracker._streams = MagicMock()
        mock_stream_tracker._streams.get.return_value = stream_info
        mock_session_tracker.get_session_info.return_value = session_info

        handler.send_webtransport_stream_data(stream_id=4, data=b"data")

        mock_h3_engine.send_data.assert_called_once_with(stream_id=4, data=b"data", end_stream=False)
        mock_stream_tracker.update_stream_state_on_send_end.assert_not_called()
        mock_trigger_transmission.assert_called_once()
        assert handler._stats["bytes_sent"] == 4
        assert stream_info.bytes_sent == 4
        assert session_info.local_data_sent == 4

    def test_send_webtransport_stream_data_ends_stream(
        self,
        handler: WebTransportProtocolHandler,
        mock_stream_tracker: MagicMock,
        mock_session_tracker: MagicMock,
    ) -> None:
        stream_info = MagicMock(state=StreamState.OPEN, session_id="s1")
        session_info = MagicMock(local_data_sent=0, peer_max_data=100)
        mock_stream_tracker._streams = MagicMock()
        mock_stream_tracker._streams.get.return_value = stream_info
        mock_session_tracker.get_session_info.return_value = session_info

        handler.send_webtransport_stream_data(stream_id=4, data=b"data", end_stream=True)

        mock_stream_tracker.update_stream_state_on_send_end.assert_called_once_with(stream_id=4)

    @pytest.mark.parametrize(
        "stream_info",
        [
            None,
            MagicMock(state=StreamState.CLOSED),
            MagicMock(state=StreamState.HALF_CLOSED_LOCAL),
        ],
    )
    def test_send_webtransport_stream_data_raises_error_on_bad_stream(
        self,
        handler: WebTransportProtocolHandler,
        mock_stream_tracker: MagicMock,
        stream_info: MagicMock | None,
    ) -> None:
        mock_stream_tracker._streams = MagicMock()
        mock_stream_tracker._streams.get.return_value = stream_info
        with pytest.raises(ProtocolError, match="not found or not writable"):
            handler.send_webtransport_stream_data(stream_id=4, data=b"data")

    def test_send_webtransport_stream_data_raises_error_on_no_session(
        self,
        handler: WebTransportProtocolHandler,
        mock_stream_tracker: MagicMock,
        mock_session_tracker: MagicMock,
    ) -> None:
        stream_info = MagicMock(state=StreamState.OPEN, session_id="s1")
        mock_stream_tracker._streams = MagicMock()
        mock_stream_tracker._streams.get.return_value = stream_info
        mock_session_tracker.get_session_info.return_value = None
        with pytest.raises(ProtocolError, match="No session found"):
            handler.send_webtransport_stream_data(stream_id=4, data=b"data")

    def test_send_webtransport_stream_data_raises_flow_control_error(
        self,
        handler: WebTransportProtocolHandler,
        mock_stream_tracker: MagicMock,
        mock_session_tracker: MagicMock,
    ) -> None:
        stream_info = MagicMock(state=StreamState.OPEN, session_id="s1")
        session_info = MagicMock(local_data_sent=90, peer_max_data=100)
        mock_stream_tracker._streams = MagicMock()
        mock_stream_tracker._streams.get.return_value = stream_info
        mock_session_tracker.get_session_info.return_value = session_info

        with pytest.raises(FlowControlError):
            handler.send_webtransport_stream_data(stream_id=4, data=b"data" * 3)
        mock_session_tracker._send_blocked_capsule.assert_called_once()
