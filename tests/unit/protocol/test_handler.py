"""Unit tests for the pywebtransport.protocol.handler module."""

import asyncio
from typing import Any, Generator

import pytest
from aioquic.quic.connection import QuicConnection, QuicConnectionState
from aioquic.quic.events import StreamDataReceived
from pytest_mock import MockerFixture

from pywebtransport import (
    ConnectionError,
    ConnectionState,
    Event,
    EventType,
    ProtocolError,
    SessionState,
    StreamDirection,
    StreamState,
    TimeoutError,
)
from pywebtransport.protocol import StreamInfo, WebTransportProtocolHandler, WebTransportSessionInfo
from pywebtransport.protocol.h3 import DatagramReceived
from pywebtransport.protocol.h3 import DataReceived as H3DataReceived
from pywebtransport.protocol.h3 import H3Connection, HeadersReceived, WebTransportStreamDataReceived


@pytest.fixture
def handler_client(
    mocker: MockerFixture, mock_quic_connection: Any, mock_parent_connection: Any, mock_h3_connection: Any
) -> WebTransportProtocolHandler:
    mocker.patch("pywebtransport.protocol.handler.H3Connection", return_value=mock_h3_connection)
    handler = WebTransportProtocolHandler(
        quic_connection=mock_quic_connection,
        is_client=True,
        connection=mock_parent_connection,
    )
    return handler


@pytest.fixture
def handler_server(
    mocker: MockerFixture, mock_quic_connection: Any, mock_parent_connection: Any, mock_h3_connection: Any
) -> WebTransportProtocolHandler:
    mocker.patch("pywebtransport.protocol.handler.H3Connection", return_value=mock_h3_connection)
    handler = WebTransportProtocolHandler(
        quic_connection=mock_quic_connection,
        is_client=False,
        connection=mock_parent_connection,
    )
    return handler


@pytest.fixture
def mock_h3_connection(mocker: MockerFixture) -> Any:
    return mocker.create_autospec(H3Connection, instance=True)


@pytest.fixture
def mock_parent_connection(mocker: MockerFixture) -> Any:
    mock = mocker.MagicMock()
    mock._transmit = mocker.MagicMock()
    return mock


@pytest.fixture
def mock_quic_connection(mocker: MockerFixture) -> Any:
    mock = mocker.create_autospec(QuicConnection, instance=True)
    mock.configuration.server_name = "test.server"
    mock._state = QuicConnectionState.CONNECTED
    mock.get_next_available_stream_id.return_value = 4
    return mock


@pytest.fixture(autouse=True)
def patch_dependencies(mocker: MockerFixture) -> Generator[None, None, None]:
    mocker.patch("pywebtransport.protocol.handler.get_logger")
    mocker.patch("pywebtransport.protocol.handler.get_timestamp", return_value=1678886400.0)
    mocker.patch("pywebtransport.protocol.handler.generate_session_id", return_value="test-session-id")
    mocker.patch(
        "pywebtransport.protocol.handler.asyncio.create_task", side_effect=lambda coro: asyncio.ensure_future(coro)
    )
    yield


class TestWebTransportProtocolHandler:
    def test_initialization_client(self, handler_client: Any, mock_quic_connection: Any) -> None:
        assert handler_client._quic is mock_quic_connection
        assert handler_client._is_client is True
        assert handler_client.connection_state == ConnectionState.IDLE

    def test_initialization_server(self, handler_server: Any) -> None:
        assert handler_server._is_client is False

    def test_connection_established(self, handler_client: Any, mock_parent_connection: Any) -> None:
        handler_client.connection_established()

        assert handler_client.connection_state == ConnectionState.CONNECTED
        assert handler_client.is_connected is True
        mock_parent_connection._transmit.assert_called_once()

    def test_connection_established_when_already_connected(self, handler_client: Any) -> None:
        handler_client.connection_established()
        handler_client._stats["connected_at"] = 123.0

        handler_client.connection_established()

        assert handler_client._stats["connected_at"] == 123.0

    def test_properties(self, handler_client: Any, mock_quic_connection: Any) -> None:
        assert handler_client.quic_connection is mock_quic_connection
        assert isinstance(handler_client.stats, dict)

    def test_get_session_info_and_all_sessions(self, handler_client: Any) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)

        assert handler_client.get_session_info("s1") is session_info
        assert handler_client.get_session_info("s2") is None
        assert handler_client.get_all_sessions() == [session_info]

    def test_get_health_status(self, handler_client: Any) -> None:
        handler_client.connection_established()
        s_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", s_info)
        stream_info = handler_client._register_stream("s1", 4, StreamDirection.BIDIRECTIONAL)
        stream_info.state = StreamState.OPEN
        handler_client._stats["errors"] = 1
        handler_client._stats["sessions_created"] = 5

        health = handler_client.get_health_status()

        assert health["status"] == "degraded"
        assert health["active_streams"] == 1

    def test_get_health_status_unhealthy(self, handler_client: Any) -> None:
        health = handler_client.get_health_status()
        assert health["status"] == "unhealthy"
        assert health["uptime"] == 0.0

        handler_client.connection_established()
        handler_client._stats["errors"] = 2
        handler_client._stats["sessions_created"] = 10
        assert handler_client.get_health_status()["status"] == "degraded"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "headers, expected_authority",
        [
            (None, b"test.server"),
            ([("host", "custom.host")], b"custom.host"),
            ([("x-custom", "value")], b"test.server"),
        ],
    )
    async def test_create_webtransport_session_client_success(
        self,
        handler_client: Any,
        mock_quic_connection: Any,
        mock_h3_connection: Any,
        headers: Any,
        expected_authority: bytes,
    ) -> None:
        mock_quic_connection.get_next_available_stream_id.return_value = 8

        session_id, stream_id = await handler_client.create_webtransport_session(path="/test", headers=headers)

        assert session_id == "test-session-id"
        assert stream_id == 8
        mock_h3_connection.send_headers.assert_called_once()
        sent_headers = dict(mock_h3_connection.send_headers.call_args[0][1])
        assert sent_headers[b":method"] == b"CONNECT"
        assert sent_headers[b":path"] == b"/test"
        assert sent_headers[b":authority"] == expected_authority
        if headers and "x-custom" in dict(headers):
            assert sent_headers[b"x-custom"] == b"value"

    @pytest.mark.asyncio
    async def test_create_webtransport_session_server_raises_error(self, handler_server: Any) -> None:
        with pytest.raises(ProtocolError, match="Only clients can create WebTransport sessions"):
            await handler_server.create_webtransport_session(path="/test")

    @pytest.mark.asyncio
    async def test_create_session_with_no_server_name(
        self, handler_client: Any, mock_quic_connection: Any, mock_h3_connection: Any
    ) -> None:
        mock_quic_connection.configuration.server_name = None

        await handler_client.create_webtransport_session(path="/")

        sent_headers = dict(mock_h3_connection.send_headers.call_args[0][1])
        assert sent_headers[b":authority"] == b"localhost"

    @pytest.mark.asyncio
    async def test_establish_session_not_connected(self, handler_client: Any) -> None:
        with pytest.raises(ConnectionError):
            await handler_client.establish_session(path="/")

    @pytest.mark.asyncio
    async def test_establish_session_timeout(self, handler_client: Any, mocker: MockerFixture) -> None:
        handler_client.connection_established()
        mocker.patch.object(handler_client, "wait_for", side_effect=asyncio.TimeoutError)

        with pytest.raises(asyncio.TimeoutError):
            await handler_client.establish_session(path="/", timeout=0.1)

    @pytest.mark.asyncio
    async def test_recover_session_success(self, handler_client: Any, mocker: MockerFixture) -> None:
        sleep_mock = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        create_session_mock = mocker.patch.object(
            handler_client, "create_webtransport_session", new_callable=mocker.AsyncMock
        )
        create_session_mock.side_effect = [ProtocolError("fail"), ("s2", 4)]
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, path="/recover", headers={}, state=SessionState.CLOSED, created_at=0
        )
        handler_client._register_session("s1", session_info)

        result = await handler_client.recover_session(session_id="s1")

        assert result is True
        assert sleep_mock.call_count == 1
        assert create_session_mock.call_count == 2

    @pytest.mark.asyncio
    async def test_recover_session_failure(self, handler_client: Any, mocker: MockerFixture) -> None:
        sleep_mock = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
        create_session_mock = mocker.patch.object(
            handler_client, "create_webtransport_session", new_callable=mocker.AsyncMock
        )
        create_session_mock.side_effect = ProtocolError("fail always")
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, path="/recover", headers={}, state=SessionState.CLOSED, created_at=0
        )
        handler_client._register_session("s1", session_info)

        assert await handler_client.recover_session(session_id="s1") is False
        assert sleep_mock.call_count == 2
        assert create_session_mock.call_count == 3
        assert await handler_client.recover_session(session_id="s-none") is False

    def test_accept_webtransport_session_server_success(self, handler_server: Any, mock_h3_connection: Any) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTING, path="/", created_at=0
        )
        handler_server._register_session("s1", session_info)

        handler_server.accept_webtransport_session(stream_id=0, session_id="s1")

        mock_h3_connection.send_headers.assert_called_once_with(0, [(b":status", b"200")])

    def test_accept_webtransport_session_client_raises_error(self, handler_client: Any) -> None:
        with pytest.raises(ProtocolError):
            handler_client.accept_webtransport_session(stream_id=0, session_id="any")

    def test_accept_webtransport_session_server_not_found_raises_error(self, handler_server: Any) -> None:
        with pytest.raises(ProtocolError):
            handler_server.accept_webtransport_session(stream_id=0, session_id="none")

    @pytest.mark.asyncio
    async def test_close_webtransport_session(self, handler_client: Any, mock_quic_connection: Any) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=4, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)
        future: asyncio.Future[Any] = asyncio.Future()

        async def handler(event: Event) -> None:
            future.set_result(event)

        handler_client.on(EventType.SESSION_CLOSED, handler)

        handler_client.close_webtransport_session("s1", code=123)

        mock_quic_connection.reset_stream.assert_called_once_with(4, 123)
        await asyncio.wait_for(future, 1)

    def test_close_session_no_op(self, handler_client: Any) -> None:
        handler_client.close_webtransport_session("non-existent-session")

    @pytest.mark.parametrize("is_unidirectional", [True, False])
    def test_create_webtransport_stream(
        self, handler_client: Any, mock_h3_connection: Any, is_unidirectional: bool
    ) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)
        mock_h3_connection.create_webtransport_stream.return_value = 8

        handler_client.create_webtransport_stream("s1", is_unidirectional=is_unidirectional)

        mock_h3_connection.create_webtransport_stream.assert_called_once()

    def test_create_stream_on_invalid_session_raises_error(self, handler_client: Any) -> None:
        with pytest.raises(ProtocolError):
            handler_client.create_webtransport_stream("none")

    def test_send_webtransport_stream_data(self, handler_client: Any, mock_h3_connection: Any) -> None:
        s_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", s_info)
        handler_client._register_stream("s1", 4, StreamDirection.BIDIRECTIONAL)

        handler_client.send_webtransport_stream_data(4, b"data", end_stream=True)

        mock_h3_connection.send_data.assert_called_once_with(stream_id=4, data=b"data", end_stream=True)

    def test_send_to_unwritable_stream_raises_error(self, handler_client: Any) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)
        stream_info = handler_client._register_stream("s1", 4, StreamDirection.BIDIRECTIONAL)
        stream_info.state = StreamState.HALF_CLOSED_LOCAL

        with pytest.raises(ProtocolError, match="not found or not writable"):
            handler_client.send_webtransport_stream_data(4, b"data")

        with pytest.raises(ProtocolError, match="not found or not writable"):
            handler_client.send_webtransport_stream_data(99, b"data")

    @pytest.mark.asyncio
    async def test_read_and_write_stream(self, handler_client: Any) -> None:
        handler_client.connection_established()
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)
        handler_client._register_stream("s1", 4, StreamDirection.BIDIRECTIONAL)
        read_task = asyncio.create_task(handler_client.read_stream_complete(stream_id=4, timeout=0.1))
        await asyncio.sleep(0)

        await handler_client.emit("stream_data_received:4", data={"data": b"chunk1", "end_stream": False})
        await handler_client.emit("stream_data_received:4", data={"data": b"chunk2", "end_stream": True})
        result = await read_task

        assert result == b"chunk1chunk2"
        with pytest.raises(TimeoutError):
            await handler_client.read_stream_complete(stream_id=4, timeout=0.01)

    def test_write_stream_chunked_with_error(self, handler_client: Any, mocker: MockerFixture) -> None:
        handler_client.connection_established()
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)
        handler_client._register_stream("s1", 4, StreamDirection.BIDIRECTIONAL)
        send_mock = mocker.patch.object(handler_client, "send_webtransport_stream_data")
        send_mock.side_effect = [None, ProtocolError("Stream broke")]

        sent_bytes = handler_client.write_stream_chunked(stream_id=4, data=b"abc" * 10, chunk_size=10)

        assert sent_bytes == 10
        assert send_mock.call_count == 2

    def test_abort_stream(self, handler_client: Any, mock_quic_connection: Any) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)
        handler_client._register_stream("s1", 4, StreamDirection.BIDIRECTIONAL)

        handler_client.abort_stream(stream_id=4, error_code=555)

        mock_quic_connection.reset_stream.assert_called_once_with(4, 555)
        assert 4 not in handler_client._streams

    def test_send_webtransport_datagram(self, handler_client: Any, mock_h3_connection: Any) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)

        handler_client.send_webtransport_datagram("s1", b"dgram")

        mock_h3_connection.send_datagram.assert_called_once_with(stream_id=0, data=b"dgram")
        assert handler_client.stats["datagrams_sent"] == 1
        with pytest.raises(ProtocolError):
            handler_client.send_webtransport_datagram("s-none", b"dgram")

    @pytest.mark.asyncio
    async def test_handle_h3_event_routes_correctly(self, handler_client: Any, mocker: MockerFixture) -> None:
        mock_h3_connection = handler_client._h3
        headers_event = HeadersReceived(stream_id=0, headers=[], stream_ended=False)
        data_event = WebTransportStreamDataReceived(stream_id=4, data=b"", stream_ended=False, session_id=0)
        datagram_event = DatagramReceived(stream_id=0, data=b"")
        mock_h3_connection.handle_event.return_value = [headers_event, data_event, datagram_event]
        handler_client._handle_session_headers = mocker.AsyncMock()
        handler_client._handle_webtransport_stream_data = mocker.AsyncMock()
        handler_client._handle_datagram_received = mocker.AsyncMock()

        await handler_client.handle_quic_event(StreamDataReceived(stream_id=0, data=b"", end_stream=False))

        handler_client._handle_session_headers.assert_awaited_once_with(headers_event)
        handler_client._handle_webtransport_stream_data.assert_awaited_once_with(data_event)
        handler_client._handle_datagram_received.assert_awaited_once_with(datagram_event)

    @pytest.mark.asyncio
    async def test_handle_session_headers_client_success(self, handler_client: Any) -> None:
        session_id, stream_id = await handler_client.create_webtransport_session(path="/test")
        future: asyncio.Future[Any] = asyncio.Future()

        async def handler(event: Event) -> None:
            future.set_result(event)

        handler_client.on(EventType.SESSION_READY, handler)

        await handler_client._handle_session_headers(
            HeadersReceived(stream_id=stream_id, headers=[(b":status", b"200")], stream_ended=False)
        )

        event_result = await asyncio.wait_for(future, 1)
        assert event_result.data["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_handle_session_headers_client_failure(self, handler_client: Any) -> None:
        session_id, stream_id = await handler_client.create_webtransport_session(path="/test")
        future: asyncio.Future[Any] = asyncio.Future()

        async def handler(event: Event) -> None:
            future.set_result(event)

        handler_client.on(EventType.SESSION_CLOSED, handler)

        await handler_client._handle_session_headers(
            HeadersReceived(stream_id=stream_id, headers=[(b":status", b"404")], stream_ended=True)
        )

        result = await asyncio.wait_for(future, 1)
        assert result.data["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_handle_session_headers_server_request(
        self, handler_server: Any, mock_parent_connection: Any
    ) -> None:
        future: asyncio.Future[Any] = asyncio.Future()

        async def handler(event: Event) -> None:
            future.set_result(event)

        handler_server.on(EventType.SESSION_REQUEST, handler)
        headers = [(b":method", b"CONNECT"), (b":protocol", b"webtransport"), (b":path", b"/")]

        await handler_server._handle_session_headers(HeadersReceived(stream_id=0, headers=headers, stream_ended=False))

        result = await asyncio.wait_for(future, 1)
        assert result.data["session_id"] == "test-session-id"
        assert result.data["connection"] is mock_parent_connection

    @pytest.mark.asyncio
    async def test_handle_webtransport_stream_data_new_stream(self, handler_server: Any, mocker: MockerFixture) -> None:
        s_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_server._register_session("s1", s_info)
        mock_h3_stream = mocker.MagicMock()
        mock_h3_stream.session_id = 0
        handler_server._h3._get_or_create_stream.return_value = mock_h3_stream
        opened_future: asyncio.Future[Any] = asyncio.Future()
        initial_data = b"initial data"
        initial_ended = True

        async def handler(event: Event) -> None:
            opened_future.set_result(event)

        handler_server.on(EventType.STREAM_OPENED, handler)

        await handler_server._handle_webtransport_stream_data(
            WebTransportStreamDataReceived(stream_id=5, data=initial_data, stream_ended=initial_ended, session_id=0)
        )

        event_result = await asyncio.wait_for(opened_future, 1)
        assert event_result.data["direction"] == StreamDirection.BIDIRECTIONAL
        assert "initial_payload" in event_result.data
        assert event_result.data["initial_payload"]["data"] == initial_data
        assert event_result.data["initial_payload"]["end_stream"] == initial_ended

    @pytest.mark.asyncio
    async def test_handle_unhandled_h3_event(self, handler_client: Any) -> None:
        unhandled_event = H3DataReceived(stream_id=0, data=b"", stream_ended=False)
        handler_client._h3.handle_event.return_value = [unhandled_event]

        await handler_client.handle_quic_event(StreamDataReceived(stream_id=0, data=b"", end_stream=False))

    @pytest.mark.asyncio
    async def test_handle_data_for_unknown_session(self, handler_server: Any) -> None:
        handler_server._h3._get_or_create_stream.return_value = StreamInfo(
            session_id="some-session-id",
            stream_id=5,
            direction=StreamDirection.BIDIRECTIONAL,
            state=StreamState.OPEN,
            created_at=0,
        )

        await handler_server._handle_webtransport_stream_data(
            WebTransportStreamDataReceived(stream_id=5, data=b"", stream_ended=True, session_id=0)
        )

    @pytest.mark.asyncio
    async def test_handle_datagram_for_unknown_session(self, handler_server: Any) -> None:
        await handler_server._handle_datagram_received(DatagramReceived(stream_id=0, data=b""))

    def test_stream_state_transitions_to_closed(self, handler_client: Any) -> None:
        session_info = WebTransportSessionInfo(
            session_id="s1", stream_id=0, state=SessionState.CONNECTED, path="/", created_at=0
        )
        handler_client._register_session("s1", session_info)
        stream_info = handler_client._register_stream("s1", 4, StreamDirection.BIDIRECTIONAL)
        stream_info.state = StreamState.OPEN

        handler_client._update_stream_state_on_send_end(4)
        assert stream_info.state == StreamState.HALF_CLOSED_LOCAL

        handler_client._update_stream_state_on_receive_end(4)
        assert 4 not in handler_client._streams

        stream_info = handler_client._register_stream("s1", 8, StreamDirection.BIDIRECTIONAL)
        handler_client._update_stream_state_on_receive_end(8)
        assert stream_info.state == StreamState.HALF_CLOSED_REMOTE

        handler_client._update_stream_state_on_send_end(8)
        assert 8 not in handler_client._streams
