"""Unit tests for the pywebtransport.server._adapter module."""

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import (
    ConnectionTerminated,
    DatagramFrameReceived,
    HandshakeCompleted,
    QuicEvent,
    StreamDataReceived,
    StreamReset,
)
from pytest_mock import MockerFixture

from pywebtransport import ServerConfig
from pywebtransport._protocol.events import (
    TransportConnectionTerminated,
    TransportDatagramFrameReceived,
    TransportHandshakeCompleted,
    TransportQuicParametersReceived,
    TransportQuicTimerFired,
    TransportStreamDataReceived,
    TransportStreamReset,
)
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import ServerError
from pywebtransport.server._adapter import WebTransportServerProtocol, create_server


@pytest.mark.asyncio
class TestCreateServer:
    @pytest.fixture
    def connection_creator(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def mock_create_quic_config(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.patch("pywebtransport.server._adapter.create_quic_configuration"))

    @pytest.fixture
    def mock_path_class(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.patch("pywebtransport.server._adapter.Path"))

    @pytest.fixture
    def mock_quic_serve(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.patch("pywebtransport.server._adapter.quic_serve", new_callable=mocker.AsyncMock))

    @pytest.fixture
    def server_config(self) -> ServerConfig:
        config = ServerConfig()
        config.certfile = "cert.pem"
        config.keyfile = "key.pem"
        return config

    @pytest.fixture
    def tmp_certs(self, tmp_path: Path, server_config: ServerConfig) -> None:
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.touch()
        key.touch()
        server_config.certfile = str(cert)
        server_config.keyfile = str(key)

    async def test_create_server_ca_certs_not_found(
        self,
        server_config: ServerConfig,
        connection_creator: MagicMock,
        mock_create_quic_config: MagicMock,
        tmp_certs: None,
        tmp_path: Path,
    ) -> None:
        quic_config_instance = mock_create_quic_config.return_value
        quic_config_instance.load_cert_chain = MagicMock()
        server_config.ca_certs = str(tmp_path / "nonexistent_ca.pem")

        with pytest.raises(FileNotFoundError, match="CA certs file not found"):
            await create_server(
                host="127.0.0.1", port=4433, config=server_config, connection_creator=connection_creator
            )

    async def test_create_server_cert_file_not_found(
        self, server_config: ServerConfig, connection_creator: MagicMock, tmp_path: Path
    ) -> None:
        server_config.certfile = str(tmp_path / "nonexistent_cert.pem")
        server_config.keyfile = str(tmp_path / "key.pem")
        (tmp_path / "key.pem").touch()

        with pytest.raises(FileNotFoundError, match="Certificate file not found"):
            await create_server(
                host="127.0.0.1", port=4433, config=server_config, connection_creator=connection_creator
            )

    async def test_create_server_key_file_not_found(
        self, server_config: ServerConfig, connection_creator: MagicMock, tmp_path: Path
    ) -> None:
        server_config.certfile = str(tmp_path / "cert.pem")
        server_config.keyfile = str(tmp_path / "nonexistent_key.pem")
        (tmp_path / "cert.pem").touch()

        with pytest.raises(FileNotFoundError, match="Key file not found"):
            await create_server(
                host="127.0.0.1", port=4433, config=server_config, connection_creator=connection_creator
            )

    async def test_create_server_missing_cert_config(
        self, server_config: ServerConfig, connection_creator: MagicMock
    ) -> None:
        server_config.certfile = ""

        with pytest.raises(ServerError, match="Certificate or key file not configured"):
            await create_server(
                host="127.0.0.1", port=4433, config=server_config, connection_creator=connection_creator
            )

    async def test_create_server_protocol_factory(
        self,
        server_config: ServerConfig,
        connection_creator: MagicMock,
        mock_quic_serve: MagicMock,
        mock_create_quic_config: MagicMock,
        mocker: MockerFixture,
        tmp_certs: None,
    ) -> None:
        mocker.patch("aioquic.asyncio.protocol.QuicConnectionProtocol.__init__", return_value=None)

        await create_server(host="127.0.0.1", port=4433, config=server_config, connection_creator=connection_creator)

        factory = mock_quic_serve.call_args.kwargs["create_protocol"]
        protocol = factory(quic=MagicMock())

        assert isinstance(protocol, WebTransportServerProtocol)
        assert protocol._server_config == server_config
        assert protocol._connection_creator == connection_creator

    async def test_create_server_success(
        self,
        server_config: ServerConfig,
        connection_creator: MagicMock,
        mock_quic_serve: MagicMock,
        mock_create_quic_config: MagicMock,
        tmp_certs: None,
    ) -> None:
        quic_config_instance = mock_create_quic_config.return_value

        result = await create_server(
            host="127.0.0.1", port=4433, config=server_config, connection_creator=connection_creator
        )

        assert result == mock_quic_serve.return_value
        mock_create_quic_config.assert_called_once_with(
            alpn_protocols=server_config.alpn_protocols,
            congestion_control_algorithm=server_config.congestion_control_algorithm,
            idle_timeout=server_config.connection_idle_timeout,
            is_client=False,
            max_datagram_size=server_config.max_datagram_size,
        )
        quic_config_instance.load_cert_chain.assert_called_once()
        mock_quic_serve.assert_awaited_once()

    async def test_create_server_with_ca_certs_success(
        self,
        server_config: ServerConfig,
        connection_creator: MagicMock,
        mock_create_quic_config: MagicMock,
        mock_quic_serve: MagicMock,
        tmp_certs: None,
        tmp_path: Path,
    ) -> None:
        ca_cert = tmp_path / "ca.pem"
        ca_cert.touch()
        server_config.ca_certs = str(ca_cert)
        quic_config_instance = mock_create_quic_config.return_value

        await create_server(host="127.0.0.1", port=4433, config=server_config, connection_creator=connection_creator)

        quic_config_instance.load_verify_locations.assert_called_once()


class TestWebTransportServerProtocol:
    @pytest.fixture
    def mock_connection_creator(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.Mock())

    @pytest.fixture
    def mock_loop(self, mocker: MockerFixture) -> MagicMock:
        loop = mocker.Mock(spec=asyncio.AbstractEventLoop)
        loop.time.return_value = 1000.0
        mocker.patch("asyncio.get_running_loop", return_value=loop)
        return cast(MagicMock, loop)

    @pytest.fixture
    def mock_queue(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.Mock(spec=asyncio.Queue))

    @pytest.fixture
    def mock_quic(self, mocker: MockerFixture) -> MagicMock:
        quic = mocker.Mock(spec=QuicConnection)
        quic._close_event = None
        quic._remote_max_datagram_frame_size = 1200
        quic.configuration = mocker.Mock(spec=QuicConfiguration)
        quic.configuration.server_name = "example.com"
        quic.datagrams_to_send.return_value = []
        quic.get_timer.return_value = 12345.6
        return cast(MagicMock, quic)

    @pytest.fixture
    def mock_server_config(self, mocker: MockerFixture) -> MagicMock:
        return cast(MagicMock, mocker.Mock(spec=ServerConfig))

    @pytest.fixture
    def mock_transport(self, mocker: MockerFixture) -> MagicMock:
        transport = mocker.Mock(spec=asyncio.DatagramTransport)
        transport.is_closing.return_value = False
        return cast(MagicMock, transport)

    @pytest.fixture
    def protocol(
        self,
        mock_quic: MagicMock,
        mock_loop: MagicMock,
        mock_server_config: MagicMock,
        mock_connection_creator: MagicMock,
    ) -> WebTransportServerProtocol:
        protocol = WebTransportServerProtocol(
            quic=mock_quic, server_config=mock_server_config, connection_creator=mock_connection_creator
        )
        assert protocol._loop == mock_loop
        return protocol

    def test_close_connection(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.close_connection(error_code=0x100, reason_phrase="shutdown")

        mock_quic.close.assert_called_once_with(error_code=0x100, reason_phrase="shutdown")
        spy_transmit.assert_called_once()

    def test_close_connection_ignored_if_already_closing(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock
    ) -> None:
        mock_quic._close_event = object()

        protocol.close_connection(error_code=1)

        mock_quic.close.assert_not_called()

    def test_connection_lost_cancels_timer(self, protocol: WebTransportServerProtocol, mock_queue: MagicMock) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        timer_handle = protocol._timer_handle
        assert timer_handle is not None

        protocol.connection_lost(exc=None)

        cast(MagicMock, timer_handle.cancel).assert_called_once()
        assert protocol._timer_handle is None

    def test_connection_lost_clean_closure(self, protocol: WebTransportServerProtocol, mock_queue: MagicMock) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)

        protocol.connection_lost(exc=None)

        mock_queue.put_nowait.assert_called_once()
        event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(event, TransportConnectionTerminated)
        assert event.error_code == ErrorCodes.NO_ERROR
        assert event.reason_phrase == "Connection closed"

    def test_connection_lost_ignores_connection_terminated_exception(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        exc = cast(Any, ConnectionTerminated(error_code=0, frame_type=0, reason_phrase="remote close"))

        protocol.connection_lost(exc=exc)

        mock_queue.put_nowait.assert_not_called()

    def test_connection_lost_no_queue_buffers_event(self, protocol: WebTransportServerProtocol) -> None:
        protocol.connection_lost(exc=None)

        assert len(protocol._pending_events) == 1
        assert isinstance(protocol._pending_events[0], TransportConnectionTerminated)

    def test_connection_lost_reports_termination(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        exc = Exception("Network failure")

        protocol.connection_lost(exc=exc)

        mock_queue.put_nowait.assert_called_once()
        event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(event, TransportConnectionTerminated)
        assert event.reason_phrase == "Network failure"
        assert event.error_code == ErrorCodes.INTERNAL_ERROR

    def test_connection_lost_silent_if_locally_closing(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock, mock_quic: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        mock_quic._close_event = object()

        protocol.connection_lost(exc=None)

        mock_queue.put_nowait.assert_not_called()

    def test_connection_made(
        self, protocol: WebTransportServerProtocol, mock_transport: MagicMock, mock_connection_creator: MagicMock
    ) -> None:
        protocol.connection_made(transport=mock_transport)

        assert protocol._transport == mock_transport
        mock_connection_creator.assert_called_once_with(protocol, mock_transport)

    def test_get_next_available_stream_id(self, protocol: WebTransportServerProtocol, mock_quic: MagicMock) -> None:
        mock_quic.get_next_available_stream_id.return_value = 4

        result = protocol.get_next_available_stream_id(is_unidirectional=True)

        assert result == 4
        mock_quic.get_next_available_stream_id.assert_called_once_with(is_unidirectional=True)

    def test_get_server_name(self, protocol: WebTransportServerProtocol) -> None:
        assert protocol.get_server_name() == "example.com"

    def test_handle_timer_internal_callback(self, protocol: WebTransportServerProtocol, mock_queue: MagicMock) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)

        protocol._handle_timer()

        assert protocol._timer_handle is None
        mock_queue.put_nowait.assert_called_once()
        event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(event, TransportQuicTimerFired)

    def test_handle_timer_internal_callback_allowed_if_closing(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock, mock_quic: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        mock_quic._close_event = object()

        protocol._handle_timer()

        mock_queue.put_nowait.assert_called_once()
        event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(event, TransportQuicTimerFired)

    def test_handle_timer_internal_callback_ignored_if_no_queue(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        protocol._handle_timer()

        mock_queue.put_nowait.assert_not_called()

    def test_handle_timer_now(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mock_loop: MagicMock, mocker: MockerFixture
    ) -> None:
        spy_transmit = mocker.spy(protocol, "transmit")
        mock_quic.next_event.side_effect = [None]

        protocol.handle_timer_now()

        mock_quic.handle_timer.assert_called_once_with(now=mock_loop.time())
        spy_transmit.assert_called_once()

    def test_handle_timer_now_allowed_if_closing(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mock_loop: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_quic._close_event = object()
        mock_quic.next_event.side_effect = [None]
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.handle_timer_now()

        mock_quic.handle_timer.assert_called_once_with(now=mock_loop.time())
        spy_transmit.assert_called_once()

    def test_handle_timer_now_drains_events(
        self,
        protocol: WebTransportServerProtocol,
        mock_quic: MagicMock,
        mock_loop: MagicMock,
        mock_queue: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        event1 = DatagramFrameReceived(data=b"1")
        event2 = DatagramFrameReceived(data=b"2")
        mock_quic.next_event.side_effect = [event1, event2, None]
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.handle_timer_now()

        mock_quic.handle_timer.assert_called_once_with(now=mock_loop.time())
        assert mock_queue.put_nowait.call_count == 2
        spy_transmit.assert_called_once()

    def test_init(
        self,
        protocol: WebTransportServerProtocol,
        mock_quic: MagicMock,
        mock_server_config: MagicMock,
        mock_connection_creator: MagicMock,
    ) -> None:
        assert protocol._quic == mock_quic
        assert protocol._server_config == mock_server_config
        assert protocol._connection_creator == mock_connection_creator
        assert protocol._engine_queue is None
        assert protocol._timer_handle is None
        assert protocol._pending_events == []

    def test_log_event(self, protocol: WebTransportServerProtocol, mock_quic: MagicMock) -> None:
        mock_logger = MagicMock()
        protocol._quic_logger = mock_logger
        data: dict[str, Any] = {"key": "value"}

        protocol.log_event(category="http", event="request", data=data)

        mock_logger.log_event.assert_called_once_with(category="http", event="request", data=data)

    def test_log_event_no_logger(self, protocol: WebTransportServerProtocol) -> None:
        protocol._quic_logger = None

        protocol.log_event(category="http", event="request", data={})

    def test_quic_event_received_connection_terminated(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        event = ConnectionTerminated(error_code=0x1, frame_type=0x0, reason_phrase="closed")

        protocol.quic_event_received(event)

        mock_queue.put_nowait.assert_called_once()
        sent_event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(sent_event, TransportConnectionTerminated)
        assert sent_event.error_code == 0x1
        assert sent_event.reason_phrase == "closed"

    def test_quic_event_received_datagram(self, protocol: WebTransportServerProtocol, mock_queue: MagicMock) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        event = DatagramFrameReceived(data=b"payload")

        protocol.quic_event_received(event)

        mock_queue.put_nowait.assert_called_once()
        sent_event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(sent_event, TransportDatagramFrameReceived)
        assert sent_event.data == b"payload"

    def test_quic_event_received_handshake_completed(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        event = HandshakeCompleted(alpn_protocol="h3", early_data_accepted=False, session_resumed=False)

        protocol.quic_event_received(event)

        assert mock_queue.put_nowait.call_count == 2
        args_1 = mock_queue.put_nowait.call_args_list[0].kwargs["item"]
        assert isinstance(args_1, TransportHandshakeCompleted)
        args_2 = mock_queue.put_nowait.call_args_list[1].kwargs["item"]
        assert isinstance(args_2, TransportQuicParametersReceived)
        assert args_2.remote_max_datagram_frame_size == 1200

    def test_quic_event_received_handshake_completed_none_max_datagram_size(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock, mock_quic: MagicMock
    ) -> None:
        mock_quic._remote_max_datagram_frame_size = None
        protocol.set_engine_queue(engine_queue=mock_queue)
        event = HandshakeCompleted(alpn_protocol="h3", early_data_accepted=False, session_resumed=False)

        protocol.quic_event_received(event)

        assert mock_queue.put_nowait.call_count == 2
        param_event = mock_queue.put_nowait.call_args_list[1].kwargs["item"]
        assert isinstance(param_event, TransportQuicParametersReceived)
        assert param_event.remote_max_datagram_frame_size == 0

    def test_quic_event_received_no_queue_buffers_event(self, protocol: WebTransportServerProtocol) -> None:
        event = DatagramFrameReceived(data=b"data")

        protocol.quic_event_received(event)

        assert len(protocol._pending_events) == 1
        assert isinstance(protocol._pending_events[0], TransportDatagramFrameReceived)

    def test_set_engine_queue_flushes_pending(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        event1 = DatagramFrameReceived(data=b"1")
        protocol.quic_event_received(event1)

        protocol.set_engine_queue(engine_queue=mock_queue)

        assert len(protocol._pending_events) == 0
        mock_queue.put_nowait.assert_called_once()
        assert isinstance(mock_queue.put_nowait.call_args.kwargs["item"], TransportDatagramFrameReceived)

    def test_quic_event_received_stream_data(self, protocol: WebTransportServerProtocol, mock_queue: MagicMock) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        event = StreamDataReceived(data=b"chunk", end_stream=True, stream_id=10)

        protocol.quic_event_received(event)

        mock_queue.put_nowait.assert_called_once()
        sent_event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(sent_event, TransportStreamDataReceived)
        assert sent_event.data == b"chunk"
        assert sent_event.end_stream is True
        assert sent_event.stream_id == 10

    def test_quic_event_received_stream_reset(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        event = StreamReset(error_code=0x100, stream_id=5)

        protocol.quic_event_received(event)

        mock_queue.put_nowait.assert_called_once()
        sent_event = mock_queue.put_nowait.call_args.kwargs["item"]
        assert isinstance(sent_event, TransportStreamReset)
        assert sent_event.error_code == 0x100
        assert sent_event.stream_id == 5

    def test_quic_event_received_unknown_event(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)
        event = cast(QuicEvent, MagicMock())

        protocol.quic_event_received(event)

        mock_queue.put_nowait.assert_not_called()

    def test_reset_stream(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.reset_stream(stream_id=1, error_code=99)

        mock_quic.reset_stream.assert_called_once_with(stream_id=1, error_code=99)
        spy_transmit.assert_called_once()

    def test_reset_stream_ignored_if_closing(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_quic._close_event = object()
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.reset_stream(stream_id=1, error_code=99)

        mock_quic.reset_stream.assert_not_called()
        spy_transmit.assert_not_called()

    def test_reset_stream_state_conflict(self, protocol: WebTransportServerProtocol, mock_quic: MagicMock) -> None:
        mock_quic.reset_stream.side_effect = AssertionError("I/O state conflict")

        protocol.reset_stream(stream_id=1, error_code=99)

        mock_quic.reset_stream.assert_called_once_with(stream_id=1, error_code=99)

    def test_schedule_timer_now(self, protocol: WebTransportServerProtocol, mock_loop: MagicMock) -> None:
        protocol.schedule_timer_now()

        cast(MagicMock, protocol._quic.get_timer).assert_called_once()
        mock_loop.call_at.assert_called_once()

    def test_schedule_timer_now_allowed_if_closing(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mock_loop: MagicMock
    ) -> None:
        mock_quic._close_event = object()

        protocol.schedule_timer_now()

        cast(MagicMock, mock_quic.get_timer).assert_called_once()
        mock_loop.call_at.assert_called_once()

    def test_schedule_timer_now_no_timer_needed(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mock_loop: MagicMock
    ) -> None:
        mock_quic.get_timer.return_value = None

        protocol.schedule_timer_now()

        mock_loop.call_at.assert_not_called()

    def test_schedule_timer_now_reschedules_existing_timer(
        self, protocol: WebTransportServerProtocol, mock_loop: MagicMock
    ) -> None:
        mock_loop.call_at.side_effect = lambda *args, **kwargs: MagicMock()

        protocol.schedule_timer_now()
        first_handle = protocol._timer_handle
        assert first_handle is not None

        protocol.schedule_timer_now()

        cast(MagicMock, first_handle.cancel).assert_called_once()
        assert protocol._timer_handle is not None
        assert protocol._timer_handle is not first_handle
        assert mock_loop.call_at.call_count == 2

    def test_send_datagram_frame(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        spy_transmit = mocker.spy(protocol, "transmit")
        data = b"udp-payload"

        protocol.send_datagram_frame(data=data)

        mock_quic.send_datagram_frame.assert_called_once_with(data=data)
        spy_transmit.assert_called_once()

    def test_send_datagram_frame_ignored_if_closed(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_quic._close_event = object()
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.send_datagram_frame(data=b"data")

        mock_quic.send_datagram_frame.assert_not_called()
        spy_transmit.assert_not_called()

    def test_send_stream_data(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.send_stream_data(stream_id=1, data=b"hi", end_stream=True)

        mock_quic.send_stream_data.assert_called_once_with(stream_id=1, data=b"hi", end_stream=True)
        spy_transmit.assert_called_once()

    def test_send_stream_data_fin_only_allowed_during_closing(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_quic._close_event = object()
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.send_stream_data(stream_id=1, data=b"", end_stream=True)

        mock_quic.send_stream_data.assert_called_once_with(stream_id=1, data=b"", end_stream=True)
        spy_transmit.assert_called_once()

    def test_send_stream_data_ignored_if_closing(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mocker: MockerFixture
    ) -> None:
        mock_quic._close_event = object()
        spy_transmit = mocker.spy(protocol, "transmit")

        protocol.send_stream_data(stream_id=1, data=b"hi", end_stream=False)

        mock_quic.send_stream_data.assert_not_called()
        spy_transmit.assert_not_called()

    def test_send_stream_data_state_conflict(self, protocol: WebTransportServerProtocol, mock_quic: MagicMock) -> None:
        mock_quic.send_stream_data.side_effect = AssertionError("Stream state error")

        protocol.send_stream_data(stream_id=1, data=b"hi")

        mock_quic.send_stream_data.assert_called_once()

    def test_set_engine_queue(
        self, protocol: WebTransportServerProtocol, mock_queue: MagicMock, mock_loop: MagicMock
    ) -> None:
        protocol.set_engine_queue(engine_queue=mock_queue)

        assert protocol._engine_queue == mock_queue
        mock_loop.call_at.assert_called_once()

    def test_stop_stream(self, protocol: WebTransportServerProtocol, mock_quic: MagicMock) -> None:
        protocol.stop_stream(stream_id=2, error_code=88)

        mock_quic.stop_stream.assert_called_once_with(stream_id=2, error_code=88)

    def test_stop_stream_state_conflict(self, protocol: WebTransportServerProtocol, mock_quic: MagicMock) -> None:
        mock_quic.stop_stream.side_effect = AssertionError("I/O state conflict")

        protocol.stop_stream(stream_id=2, error_code=88)

        mock_quic.stop_stream.assert_called_once()

    def test_transmit_generic_exception(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mock_transport: MagicMock
    ) -> None:
        protocol.connection_made(transport=mock_transport)
        mock_quic.datagrams_to_send.return_value = [(b"packet", "addr")]
        mock_transport.sendto.side_effect = ValueError("Unexpected error")

        protocol.transmit()

        mock_transport.sendto.assert_called_once()

    def test_transmit_handles_os_error(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mock_transport: MagicMock
    ) -> None:
        protocol.connection_made(transport=mock_transport)
        mock_quic.datagrams_to_send.return_value = [(b"packet", "addr")]
        mock_transport.sendto.side_effect = OSError("Network unreachable")

        protocol.transmit()

        mock_transport.sendto.assert_called_once()

    def test_transmit_ignored_if_transport_closed(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock, mock_transport: MagicMock
    ) -> None:
        protocol.connection_made(transport=mock_transport)
        mock_transport.is_closing.return_value = True

        protocol.transmit()

        mock_quic.datagrams_to_send.assert_not_called()
        mock_transport.sendto.assert_not_called()

    def test_transmit_ignored_if_transport_none(
        self, protocol: WebTransportServerProtocol, mock_quic: MagicMock
    ) -> None:
        protocol._transport = None

        protocol.transmit()

        mock_quic.datagrams_to_send.assert_not_called()

    def test_transmit_sends_packets(
        self,
        protocol: WebTransportServerProtocol,
        mock_quic: MagicMock,
        mock_transport: MagicMock,
        mock_loop: MagicMock,
    ) -> None:
        protocol.connection_made(transport=mock_transport)
        mock_quic.datagrams_to_send.return_value = [(b"packet1", "addr1"), (b"packet2", "addr2")]

        protocol.transmit()

        mock_quic.datagrams_to_send.assert_called_once_with(now=mock_loop.time())
        assert mock_transport.sendto.call_count == 2
        mock_transport.sendto.assert_any_call(b"packet1", "addr1")
        mock_transport.sendto.assert_any_call(b"packet2", "addr2")
