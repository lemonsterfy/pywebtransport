"""Unit tests for the pywebtransport.protocol.h3_engine module."""

import asyncio
import re
from typing import cast
from unittest.mock import MagicMock

import pylsqpack
import pytest
from aioquic.buffer import encode_uint_var
from aioquic.quic.connection import QuicConfiguration, QuicConnection
from aioquic.quic.events import DatagramFrameReceived, QuicEvent, StreamDataReceived

from pywebtransport import constants
from pywebtransport.config import ClientConfig, ServerConfig
from pywebtransport.constants import ErrorCodes
from pywebtransport.events import Event
from pywebtransport.exceptions import ProtocolError
from pywebtransport.protocol.events import (
    CapsuleReceived,
    DatagramReceived,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.protocol.h3_engine import (
    HeadersState,
    WebTransportH3Engine,
    encode_frame,
    encode_settings,
    parse_settings,
)
from pywebtransport.types import EventType

CLIENT_BIDI_STREAM_ID = 0
SERVER_BIDI_STREAM_ID = 1
CLIENT_UNI_STREAM_ID = 2
SERVER_UNI_STREAM_ID = 3


@pytest.fixture
def mock_quic(mocker: MagicMock) -> MagicMock:
    mock = cast(MagicMock, mocker.create_autospec(QuicConnection, instance=True))
    mock.configuration = QuicConfiguration(is_client=True)
    mock._quic_logger = MagicMock()
    mock._remote_max_datagram_frame_size = 65536
    stream_counters = {True: 2, False: 0}

    def get_next_available_stream_id(*, is_unidirectional: bool = False) -> int:
        stream_id = stream_counters[is_unidirectional]
        stream_counters[is_unidirectional] += 4
        return stream_id

    mock.get_next_available_stream_id.side_effect = get_next_available_stream_id
    return mock


@pytest.fixture
def client_config() -> ClientConfig:
    return ClientConfig.create(
        initial_max_data=1024,
        initial_max_streams_bidi=10,
        initial_max_streams_uni=5,
    )


@pytest.fixture
def server_config() -> ServerConfig:
    return ServerConfig.create(
        max_sessions=50,
        initial_max_data=2048,
        initial_max_streams_bidi=20,
        initial_max_streams_uni=15,
    )


@pytest.fixture
def mock_quic_server(mock_quic: MagicMock) -> MagicMock:
    mock_quic.configuration.is_client = False
    return mock_quic


@pytest.fixture
def mock_pylsqpack(mocker: MagicMock) -> dict[str, MagicMock]:
    mock_decoder_cls = mocker.patch("pywebtransport.protocol.h3_engine.pylsqpack.Decoder", autospec=True)
    mock_encoder_cls = mocker.patch("pywebtransport.protocol.h3_engine.pylsqpack.Encoder", autospec=True)
    mock_encoder_instance = mock_encoder_cls.return_value
    mock_encoder_instance.encode.return_value = (b"encoder-stream-bytes", b"headers-payload")
    mock_encoder_instance.apply_settings.return_value = b"encoder-settings-bytes"
    mock_encoder_instance.feed_decoder.return_value = b""
    mock_decoder_instance = mock_decoder_cls.return_value
    mock_decoder_instance.feed_header.return_value = (b"decoder-stream-bytes", [(b":status", b"200")])
    mock_decoder_instance.resume_header.return_value = (
        b"decoder-stream-bytes-resumed",
        [(b":status", b"201")],
    )
    mock_decoder_instance.feed_encoder.return_value = []

    return {
        "decoder": mock_decoder_cls,
        "encoder": mock_encoder_cls,
        "decoder_instance": mock_decoder_instance,
        "encoder_instance": mock_encoder_instance,
    }


class TestWebTransportH3EngineInitialization:
    def test_init_client_mode(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)

        assert mock_quic.send_stream_data.call_count == 4
        assert engine._is_client is True

    def test_init_server_mode(self, mock_quic_server: MagicMock, server_config: ServerConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic_server, config=server_config)

        assert engine._is_client is False

    def test_init_sends_correct_settings_client(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        WebTransportH3Engine(quic=mock_quic, config=client_config)

        settings_frame_payload = mock_quic.send_stream_data.call_args_list[1].kwargs["data"]
        settings_bytes = settings_frame_payload[2:]

        settings = parse_settings(data=settings_bytes)

        assert settings[constants.SETTINGS_WT_MAX_SESSIONS] == 1
        assert settings[constants.SETTINGS_H3_DATAGRAM] == 1
        assert settings[constants.SETTINGS_ENABLE_CONNECT_PROTOCOL] == 1
        assert settings[constants.SETTINGS_WT_INITIAL_MAX_DATA] == 1024
        assert settings[constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI] == 10
        assert settings[constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI] == 5

    def test_init_sends_correct_settings_server(self, mock_quic_server: MagicMock, server_config: ServerConfig) -> None:
        WebTransportH3Engine(quic=mock_quic_server, config=server_config)

        settings_frame_payload = mock_quic_server.send_stream_data.call_args_list[1].kwargs["data"]
        settings_bytes = settings_frame_payload[2:]

        settings = parse_settings(data=settings_bytes)

        assert settings[constants.SETTINGS_WT_MAX_SESSIONS] == 50
        assert settings[constants.SETTINGS_H3_DATAGRAM] == 1
        assert settings[constants.SETTINGS_ENABLE_CONNECT_PROTOCOL] == 1
        assert settings[constants.SETTINGS_WT_INITIAL_MAX_DATA] == 2048
        assert settings[constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI] == 20
        assert settings[constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI] == 15

    def test_init_no_logger(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        mock_quic._quic_logger = None

        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers={":method": "GET"})

        assert engine._quic_logger is None
        mock_quic.send_stream_data.assert_called()

    def test_init_connection_fails(self, mock_quic: MagicMock, client_config: ClientConfig, mocker: MagicMock) -> None:
        mocker.patch.object(
            WebTransportH3Engine, "_create_uni_stream", side_effect=RuntimeError("Failed to create stream")
        )
        with pytest.raises(RuntimeError, match="Failed to create stream"):
            WebTransportH3Engine(quic=mock_quic, config=client_config)


class TestWebTransportH3EngineSending:
    def test_create_webtransport_stream_bidirectional(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)

        stream_id = engine.create_webtransport_stream(session_id=123, is_unidirectional=False)

        assert stream_id == 0
        expected_payload = encode_uint_var(constants.H3_FRAME_TYPE_WEBTRANSPORT_STREAM) + encode_uint_var(123)
        mock_quic.send_stream_data.assert_any_call(stream_id=stream_id, data=expected_payload)

    def test_create_webtransport_stream_unidirectional(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        mock_quic.get_next_available_stream_id.side_effect = [14]

        stream_id = engine.create_webtransport_stream(session_id=456, is_unidirectional=True)

        assert stream_id == 14
        mock_quic.send_stream_data.assert_any_call(stream_id=stream_id, data=encode_uint_var(456))

    def test_send_headers(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        headers = {":method": "CONNECT", ":protocol": "webtransport"}

        engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers=headers, end_stream=True)

        expected_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"headers-payload")
        mock_quic.send_stream_data.assert_any_call(
            stream_id=CLIENT_BIDI_STREAM_ID, data=expected_frame, end_stream=True
        )

    def test_send_data_with_end_stream(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)

        engine.send_data(stream_id=CLIENT_BIDI_STREAM_ID, data=b"", end_stream=True)

        mock_quic.send_stream_data.assert_any_call(stream_id=CLIENT_BIDI_STREAM_ID, data=b"", end_stream=True)

    def test_send_datagram_success(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)

        engine.send_datagram(stream_id=CLIENT_BIDI_STREAM_ID, data=b"hello")

        expected_payload = encode_uint_var(0) + b"hello"
        mock_quic.send_datagram_frame.assert_called_with(data=expected_payload)

    def test_send_capsule(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        capsule_data = b"\x41\x04test"

        engine.send_capsule(stream_id=CLIENT_BIDI_STREAM_ID, capsule_data=capsule_data)

        mock_quic.send_stream_data.assert_any_call(stream_id=CLIENT_BIDI_STREAM_ID, data=capsule_data)

    def test_send_headers_twice_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers={":method": "GET"})

        with pytest.raises(ProtocolError, match="HEADERS frame is not allowed after initial headers") as excinfo:
            engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers={":method": "POST"})

        assert excinfo.value.error_code == ErrorCodes.H3_FRAME_UNEXPECTED

    def test_send_datagram_on_uni_stream_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)

        with pytest.raises(
            ProtocolError, match="Datagrams can only be sent for client-initiated bidirectional streams"
        ) as excinfo:
            engine.send_datagram(stream_id=CLIENT_UNI_STREAM_ID, data=b"fail")

        assert excinfo.value.error_code == ErrorCodes.H3_STREAM_CREATION_ERROR


@pytest.mark.asyncio
class TestWebTransportH3EngineEventHandling:
    async def test_handle_datagram_received(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        event = DatagramFrameReceived(data=encode_uint_var(0) + b"datagram content")

        h3_events = await engine.handle_event(event=event)

        assert len(h3_events) == 1
        assert isinstance(h3_events[0], DatagramReceived)
        assert h3_events[0].data == b"datagram content"

    async def test_handle_bidi_webtransport_setup_and_data(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        setup_frame = encode_uint_var(constants.H3_FRAME_TYPE_WEBTRANSPORT_STREAM) + encode_uint_var(789)
        event1 = StreamDataReceived(data=setup_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event1)
        event2 = StreamDataReceived(data=b"some stream data", stream_id=CLIENT_BIDI_STREAM_ID, end_stream=True)

        h3_events = await engine.handle_event(event=event2)

        assert len(h3_events) == 1
        assert isinstance(h3_events[0], WebTransportStreamDataReceived)
        assert h3_events[0].session_id == 789

    async def test_handle_uni_webtransport_setup_and_data(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        setup_and_data = encode_uint_var(constants.H3_STREAM_TYPE_WEBTRANSPORT) + encode_uint_var(101) + b"uni data"
        event = StreamDataReceived(data=setup_and_data, stream_id=CLIENT_UNI_STREAM_ID, end_stream=True)

        h3_events = await engine.handle_event(event=event)

        assert len(h3_events) == 1
        assert isinstance(h3_events[0], WebTransportStreamDataReceived)
        assert h3_events[0].session_id == 101

    async def test_handle_bidi_stream_parses_capsules_after_headers(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)

        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"encoded-headers")
        event1 = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)
        h3_events_headers = await engine.handle_event(event=event1)

        assert len(h3_events_headers) == 1
        assert isinstance(h3_events_headers[0], HeadersReceived)

        capsule_payload = encode_uint_var(999)
        capsule_header = encode_uint_var(constants.WT_MAX_DATA_TYPE) + encode_uint_var(len(capsule_payload))
        capsule_bytes = capsule_header + capsule_payload
        event2 = StreamDataReceived(data=capsule_bytes, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)
        h3_events_capsule = await engine.handle_event(event=event2)

        assert len(h3_events_capsule) == 1
        assert isinstance(h3_events_capsule[0], CapsuleReceived)
        assert h3_events_capsule[0].capsule_type == constants.WT_MAX_DATA_TYPE
        assert h3_events_capsule[0].capsule_data == capsule_payload

    async def test_handle_control_stream_settings(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings = {constants.SETTINGS_H3_DATAGRAM: 1, constants.SETTINGS_WT_MAX_SESSIONS: 10}
        settings_frame = encode_frame(
            frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=encode_settings(settings=settings)
        )
        data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        assert engine._settings_received is True

    async def test_handle_control_stream_emits_settings_event(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings = {constants.SETTINGS_H3_DATAGRAM: 1, constants.SETTINGS_WT_MAX_SESSIONS: 50}
        settings_frame = encode_frame(
            frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=encode_settings(settings=settings)
        )
        data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        event_future: asyncio.Future[Event] = asyncio.Future()

        async def on_event(e: Event) -> None:
            event_future.set_result(e)

        engine.once(event_type=EventType.SETTINGS_RECEIVED, handler=on_event)

        await engine.handle_event(event=event)

        received_event = await asyncio.wait_for(event_future, timeout=1.0)
        assert received_event.data == {"settings": settings}

    async def test_handle_qpack_streams(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        encoder_data = encode_uint_var(constants.H3_STREAM_TYPE_QPACK_ENCODER) + b"encoder-data"
        event1 = StreamDataReceived(data=encoder_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event1)

        mock_pylsqpack["decoder_instance"].feed_encoder.assert_called_with(b"encoder-data")

    async def test_handle_qpack_stream_blocked_and_resumed(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        mock_pylsqpack["decoder_instance"].feed_header.side_effect = pylsqpack.StreamBlocked
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"blocked-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events_blocked = await engine.handle_event(event=event)
        assert not h3_events_blocked

        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        assert stream.blocked is True
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        qpack_data = encode_uint_var(constants.H3_STREAM_TYPE_QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        h3_events_resumed = await engine.handle_event(event=qpack_event)

        assert len(h3_events_resumed) == 1
        assert isinstance(h3_events_resumed[0], HeadersReceived)
        assert h3_events_resumed[0].headers == {":status": "201"}
        assert stream.blocked is False

    async def test_unblocked_stream_reblocks(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        mock_pylsqpack["decoder_instance"].resume_header.side_effect = pylsqpack.StreamBlocked
        qpack_data = encode_uint_var(constants.H3_STREAM_TYPE_QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=qpack_event)

        assert not h3_events
        assert stream.blocked is True

    @pytest.mark.parametrize(
        "partial_data", [b"\x41", encode_uint_var(constants.H3_FRAME_TYPE_WEBTRANSPORT_STREAM) + b"\x9f"]
    )
    async def test_partial_bidi_webtransport_frame(
        self, mock_quic: MagicMock, client_config: ClientConfig, partial_data: bytes
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        event = StreamDataReceived(data=partial_data, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        assert engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID).buffer == partial_data

    @pytest.mark.parametrize(
        "partial_data, expected_buffer",
        [(b"\x54", b"\x54"), (encode_uint_var(constants.H3_STREAM_TYPE_WEBTRANSPORT) + b"\x9f", b"\x9f")],
    )
    async def test_partial_uni_webtransport_frame(
        self, mock_quic: MagicMock, client_config: ClientConfig, partial_data: bytes, expected_buffer: bytes
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        event = StreamDataReceived(data=partial_data, stream_id=CLIENT_UNI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        assert engine._get_or_create_stream(stream_id=CLIENT_UNI_STREAM_ID).buffer == expected_buffer

    async def test_partial_non_data_frame(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"some-header-payload")
        event = StreamDataReceived(data=headers_frame[:-1], stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        assert engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID).buffer == b"some-header-payloa"

    async def test_receive_data_on_blocked_stream(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        event = StreamDataReceived(data=b"some data", stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        assert stream.buffer == b"some data"

    async def test_unblocked_stream_resume_fails_with_protocol_error(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        mock_pylsqpack["decoder_instance"].resume_header.side_effect = ProtocolError(
            message="Resumption failed", error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR
        )
        qpack_data = encode_uint_var(constants.H3_STREAM_TYPE_QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=qpack_event)

        expected_reason = str(
            ProtocolError(message="Resumption failed", error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR, reason_phrase=expected_reason
        )

    async def test_handle_event_protocol_error(
        self, mock_quic: MagicMock, client_config: ClientConfig, mocker: MagicMock
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        error = ProtocolError(message="Test error", error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR)
        mocker.patch.object(engine, "_get_or_create_stream", side_effect=error)
        event = StreamDataReceived(data=b"some data", stream_id=CLIENT_UNI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR, reason_phrase=str(error)
        )

    async def test_partial_uni_webtransport_data(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        event1 = StreamDataReceived(
            data=encode_uint_var(constants.H3_STREAM_TYPE_WEBTRANSPORT),
            stream_id=CLIENT_UNI_STREAM_ID,
            end_stream=False,
        )
        h3_events1 = await engine.handle_event(event=event1)
        assert not h3_events1

        event2 = StreamDataReceived(data=encode_uint_var(101), stream_id=CLIENT_UNI_STREAM_ID, end_stream=False)
        h3_events2 = await engine.handle_event(event=event2)
        assert not h3_events2

        event3 = StreamDataReceived(data=b"uni data", stream_id=CLIENT_UNI_STREAM_ID, end_stream=True)
        h3_events3 = await engine.handle_event(event=event3)
        assert len(h3_events3) == 1
        assert isinstance(h3_events3[0], WebTransportStreamDataReceived)
        assert h3_events3[0].session_id == 101
        assert h3_events3[0].data == b"uni data"
        assert h3_events3[0].stream_ended is True

    async def test_unblocked_stream_with_no_blocked_frame_size(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        stream.blocked_frame_size = None
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        qpack_data = encode_uint_var(constants.H3_STREAM_TYPE_QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        with pytest.raises(AssertionError, match="Frame length for logging cannot be None"):
            await engine.handle_event(event=qpack_event)

    async def test_unhandled_quic_event_is_ignored(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        event = QuicEvent()

        h3_events = await engine.handle_event(event=event)

        assert h3_events == []
        assert not mock_quic.close.called

    async def test_handle_unknown_uni_stream_type_is_ignored(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        unknown_stream_type = 0xFF
        data = encode_uint_var(unknown_stream_type) + b"some data"
        event = StreamDataReceived(data=data, stream_id=SERVER_UNI_STREAM_ID, end_stream=True)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        mock_quic.close.assert_not_called()


@pytest.mark.asyncio
class TestWebTransportH3EngineProtocolErrors:
    @pytest.mark.parametrize(
        "frame_type, error_phrase",
        [
            (constants.H3_FRAME_TYPE_SETTINGS, "Invalid frame type on request stream"),
            (constants.H3_FRAME_TYPE_GOAWAY, "Invalid frame type on request stream"),
        ],
    )
    async def test_invalid_frame_on_request_stream(
        self, mock_quic: MagicMock, client_config: ClientConfig, frame_type: int, error_phrase: str
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.headers_recv_state = HeadersState.AFTER_HEADERS
        frame = encode_frame(frame_type=frame_type, frame_data=b"")
        event = StreamDataReceived(data=frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message=f"Invalid H3 frame type ({hex(frame_type)}) received on Capsule stream",
                error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
            )
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    async def test_data_before_headers_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        data_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_DATA, frame_data=b"some data")
        event = StreamDataReceived(data=data_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="DATA frame received before HEADERS", error_code=ErrorCodes.H3_FRAME_UNEXPECTED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    async def test_second_settings_frame_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings = {constants.SETTINGS_H3_DATAGRAM: 1}
        settings_frame = encode_frame(
            frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=encode_settings(settings=settings)
        )
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event1 = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event1)
        event2 = StreamDataReceived(data=settings_frame, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event2)

        expected_reason = str(
            ProtocolError(message="SETTINGS frame received twice", error_code=ErrorCodes.H3_FRAME_UNEXPECTED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    async def test_invalid_settings_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings = {constants.SETTINGS_WT_MAX_SESSIONS: 1, constants.SETTINGS_H3_DATAGRAM: 0}
        settings_frame = encode_frame(
            frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=encode_settings(settings=settings)
        )
        data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="WT_MAX_SESSIONS requires H3_DATAGRAM", error_code=ErrorCodes.H3_SETTINGS_ERROR)
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_SETTINGS_ERROR, reason_phrase=expected_reason)

    async def test_qpack_decompression_failed(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        mock_pylsqpack["decoder_instance"].feed_header.side_effect = pylsqpack.DecompressionFailed("error")
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"bad-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="QPACK decompression failed", error_code=ErrorCodes.QPACK_DECOMPRESSION_FAILED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.QPACK_DECOMPRESSION_FAILED, reason_phrase=expected_reason
        )

    async def test_first_control_frame_not_settings_fails(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        data_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_DATA, frame_data=b"wrong frame")
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + data_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message="First frame on control stream must be SETTINGS", error_code=ErrorCodes.H3_MISSING_SETTINGS
            )
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_MISSING_SETTINGS, reason_phrase=expected_reason
        )

    @pytest.mark.parametrize(
        "stream_type",
        [
            constants.H3_STREAM_TYPE_CONTROL,
            constants.H3_STREAM_TYPE_QPACK_DECODER,
            constants.H3_STREAM_TYPE_QPACK_ENCODER,
        ],
    )
    async def test_duplicate_uni_streams_fail(
        self, mock_quic: MagicMock, client_config: ClientConfig, stream_type: int
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream_data = encode_uint_var(stream_type)
        event1 = StreamDataReceived(data=stream_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event1)
        assert not mock_quic.close.called
        event2 = StreamDataReceived(data=stream_data, stream_id=SERVER_UNI_STREAM_ID + 4, end_stream=False)

        await engine.handle_event(event=event2)

        mock_quic.close.assert_called_once()
        assert "Only one" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_STREAM_CREATION_ERROR

    async def test_h3_datagram_without_transport_param_fails(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        mock_quic._remote_max_datagram_frame_size = None
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings = {constants.SETTINGS_H3_DATAGRAM: 1}
        settings_frame = encode_frame(
            frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=encode_settings(settings=settings)
        )
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message="H3_DATAGRAM requires max_datagram_frame_size transport parameter",
                error_code=ErrorCodes.H3_SETTINGS_ERROR,
            )
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_SETTINGS_ERROR, reason_phrase=expected_reason)

    async def test_control_stream_closed_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL)
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=True)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message="Closing control stream is not allowed", error_code=ErrorCodes.H3_CLOSED_CRITICAL_STREAM
            )
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_CLOSED_CRITICAL_STREAM, reason_phrase=expected_reason
        )

    @pytest.mark.parametrize(
        "error_fixture, stream_type, reason, error_code",
        [
            (
                pylsqpack.EncoderStreamError("encoder error"),
                constants.H3_STREAM_TYPE_QPACK_ENCODER,
                "QPACK encoder stream error",
                ErrorCodes.QPACK_ENCODER_STREAM_ERROR,
            ),
            (
                pylsqpack.DecoderStreamError("decoder error"),
                constants.H3_STREAM_TYPE_QPACK_DECODER,
                "QPACK decoder stream error",
                ErrorCodes.QPACK_DECODER_STREAM_ERROR,
            ),
        ],
    )
    async def test_qpack_stream_errors(
        self,
        mock_quic: MagicMock,
        mock_pylsqpack: dict[str, MagicMock],
        client_config: ClientConfig,
        error_fixture: Exception,
        stream_type: int,
        reason: str,
        error_code: int,
    ) -> None:
        if isinstance(error_fixture, pylsqpack.EncoderStreamError):
            mock_pylsqpack["decoder_instance"].feed_encoder.side_effect = error_fixture
        else:
            mock_pylsqpack["encoder_instance"].feed_decoder.side_effect = error_fixture
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream_data = encode_uint_var(stream_type) + b"some-qpack-data"
        event = StreamDataReceived(data=stream_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(ProtocolError(message=reason, error_code=error_code))
        mock_quic.close.assert_called_once_with(error_code=error_code, reason_phrase=expected_reason)

    async def test_handle_malformed_datagram(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        event = DatagramFrameReceived(data=b"\xc0")

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message="Could not parse quarter stream ID from datagram",
                error_code=ErrorCodes.H3_DATAGRAM_ERROR,
            )
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_DATAGRAM_ERROR, reason_phrase=expected_reason)

    async def test_push_promise_frame_is_ignored(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_PUSH_PROMISE, frame_data=b"\x01\x00")
        event = StreamDataReceived(data=frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        mock_quic.close.assert_not_called()

    async def test_headers_on_control_stream_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=b"")
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event1 = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event1)

        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"")
        event2 = StreamDataReceived(data=headers_frame, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event2)

        expected_reason = str(
            ProtocolError(message="Invalid frame type on control stream", error_code=ErrorCodes.H3_FRAME_UNEXPECTED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    async def test_unknown_frame_on_control_stream_is_ignored(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=b"")
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event1 = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event1)

        unknown_frame = encode_frame(frame_type=0x20, frame_data=b"test data")
        event2 = StreamDataReceived(data=unknown_frame, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        h3_events = await engine.handle_event(event=event2)

        assert not h3_events
        mock_quic.close.assert_not_called()


@pytest.mark.asyncio
class TestWebTransportH3EngineHeaderValidation:
    @pytest.mark.parametrize(
        "headers, error_match",
        [
            ([(b":method", b"GET")], "Pseudo-headers.*are missing"),
            ([(b":authority", b"test.com")], "Pseudo-headers.*are missing"),
            ([(b"regular", b"header"), (b":method", b"GET")], "is not allowed after regular headers"),
            ([(b":method", b"GET"), (b":method", b"POST")], "is included twice"),
            ([(b":invalid", b"pseudo")], "is not valid"),
            ([(b"invalid name ", b"value")], "contains invalid characters"),
            ([(b"key:other", b"value")], "contains a non-initial colon"),
            ([(b"key", b"invalid\nvalue")], "has forbidden characters"),
            ([(b":method", b"GET"), (b":scheme", b"http"), (b":authority", b"")], "cannot be empty"),
            (
                [(b":method", b"GET"), (b":scheme", b"https"), (b":authority", b"test.com"), (b":path", b"")],
                "cannot be empty",
            ),
            ([(b"key", b" value")], "starts with whitespace"),
            ([(b"key", b"value ")], "ends with whitespace"),
        ],
    )
    async def test_invalid_request_headers(
        self,
        mock_quic: MagicMock,
        mock_pylsqpack: dict[str, MagicMock],
        client_config: ClientConfig,
        headers: list,
        error_match: str,
    ) -> None:
        mock_quic.configuration.is_client = False
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        mock_pylsqpack["decoder_instance"].feed_header.return_value = (b"", headers)
        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"bad-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        reason_phrase = mock_quic.close.call_args.kwargs["reason_phrase"]
        assert re.search(error_match, reason_phrase)
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_MESSAGE_ERROR

    async def test_invalid_response_headers(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], client_config: ClientConfig
    ) -> None:
        mock_quic.configuration.is_client = True
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        mock_pylsqpack["decoder_instance"].feed_header.return_value = (b"", [(b"some", b"header")])
        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"bad-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=SERVER_BIDI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        reason_phrase = mock_quic.close.call_args.kwargs["reason_phrase"]
        assert re.search("Pseudo-headers.*:status.*are missing", reason_phrase)
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_MESSAGE_ERROR


@pytest.mark.asyncio
class TestWebTransportH3EngineMiscErrors:
    async def test_malformed_settings_frame_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=b"\x06")
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="Malformed SETTINGS frame payload", error_code=ErrorCodes.H3_FRAME_ERROR)
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_FRAME_ERROR, reason_phrase=expected_reason)

    async def test_data_frame_on_capsule_stream_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.headers_recv_state = HeadersState.AFTER_HEADERS
        event = StreamDataReceived(data=b"\x00", stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        expected_reason = str(
            ProtocolError(
                message="Invalid H3 frame type (0x0) received on Capsule stream",
                error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
            )
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    async def test_invalid_boolean_setting_value(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings = {constants.SETTINGS_ENABLE_CONNECT_PROTOCOL: 2}
        settings_frame = encode_frame(
            frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=encode_settings(settings=settings)
        )
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        assert "setting must be 1 if present" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_SETTINGS_ERROR

    async def test_reserved_setting_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings = {0x02: 1}
        settings_frame = encode_frame(
            frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=encode_settings(settings=settings)
        )
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        assert "Setting identifier 0x2 is reserved" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_SETTINGS_ERROR

    async def test_handle_event_after_done(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        engine._is_done = True
        event = DatagramFrameReceived(data=b"some data")

        h3_events = await engine.handle_event(event=event)

        assert not h3_events
        assert not mock_quic.close.called

    async def test_headers_on_control_stream_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=b"")
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event1 = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event1)

        headers_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=b"")
        event2 = StreamDataReceived(data=headers_frame, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event2)

        expected_reason = str(
            ProtocolError(message="Invalid frame type on control stream", error_code=ErrorCodes.H3_FRAME_UNEXPECTED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    async def test_unknown_frame_on_control_stream_is_ignored(
        self, mock_quic: MagicMock, client_config: ClientConfig
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        settings_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=b"")
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event1 = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        await engine.handle_event(event=event1)

        unknown_frame = encode_frame(frame_type=0x20, frame_data=b"test data")
        event2 = StreamDataReceived(data=unknown_frame, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        h3_events = await engine.handle_event(event=event2)

        assert not h3_events
        mock_quic.close.assert_not_called()

    async def test_duplicate_setting_fails(self, mock_quic: MagicMock, client_config: ClientConfig) -> None:
        engine = WebTransportH3Engine(quic=mock_quic, config=client_config)
        buf = encode_uint_var(constants.SETTINGS_H3_DATAGRAM) + encode_uint_var(1)
        buf += encode_uint_var(constants.SETTINGS_H3_DATAGRAM) + encode_uint_var(1)
        settings_frame = encode_frame(frame_type=constants.H3_FRAME_TYPE_SETTINGS, frame_data=buf)
        control_data = encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        await engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        assert "is included twice" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_SETTINGS_ERROR
