"""Unit tests for the pywebtransport.protocol.h3_engine module."""

import re
from typing import cast
from unittest.mock import MagicMock

import pylsqpack
import pytest
from aioquic.quic.connection import QuicConfiguration, QuicConnection
from aioquic.quic.events import DatagramFrameReceived, QuicEvent, StreamDataReceived

from pywebtransport import ProtocolError
from pywebtransport.constants import ErrorCodes
from pywebtransport.protocol.events import (
    DatagramReceived,
    DataReceived,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.protocol.h3_engine import (
    FrameType,
    HeadersState,
    Setting,
    StreamType,
    WebTransportH3Engine,
    encode_frame,
    encode_settings,
    encode_uint_var,
)

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
    def test_init_client_mode(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)

        assert mock_quic.send_stream_data.call_count == 4
        assert engine._is_client is True

    def test_init_server_mode(self, mock_quic: MagicMock) -> None:
        mock_quic.configuration.is_client = False

        engine = WebTransportH3Engine(quic=mock_quic)

        assert engine._is_client is False

    def test_init_webtransport_disabled(self, mock_quic: MagicMock) -> None:
        WebTransportH3Engine(quic=mock_quic, enable_webtransport=False)

        settings_frame_payload = mock_quic.send_stream_data.call_args_list[1].kwargs["data"]
        settings_bytes = settings_frame_payload[2:]

        assert Setting.H3_DATAGRAM.to_bytes(1, "big") not in settings_bytes
        assert Setting.ENABLE_WEBTRANSPORT.to_bytes(4, "big") not in settings_bytes

    def test_init_no_logger(self, mock_quic: MagicMock) -> None:
        mock_quic._quic_logger = None

        engine = WebTransportH3Engine(quic=mock_quic)
        engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers={":method": "GET"})

        assert engine._quic_logger is None
        mock_quic.send_stream_data.assert_called()

    def test_init_connection_fails(self, mock_quic: MagicMock, mocker: MagicMock) -> None:
        mocker.patch.object(
            WebTransportH3Engine, "_create_uni_stream", side_effect=RuntimeError("Failed to create stream")
        )
        with pytest.raises(RuntimeError, match="Failed to create stream"):
            WebTransportH3Engine(quic=mock_quic)


class TestWebTransportH3EngineSending:
    def test_create_webtransport_stream_bidirectional(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)

        stream_id = engine.create_webtransport_stream(session_id=123, is_unidirectional=False)

        assert stream_id == 0
        expected_payload = encode_uint_var(FrameType.WEBTRANSPORT_STREAM) + encode_uint_var(123)
        mock_quic.send_stream_data.assert_any_call(stream_id=stream_id, data=expected_payload)

    def test_create_webtransport_stream_unidirectional(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        mock_quic.get_next_available_stream_id.side_effect = [14]

        stream_id = engine.create_webtransport_stream(session_id=456, is_unidirectional=True)

        assert stream_id == 14
        mock_quic.send_stream_data.assert_any_call(stream_id=stream_id, data=encode_uint_var(456))

    def test_send_headers(self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        headers = {":method": "CONNECT", ":protocol": "webtransport"}

        engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers=headers, end_stream=True)

        expected_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"headers-payload")
        mock_quic.send_stream_data.assert_any_call(
            stream_id=CLIENT_BIDI_STREAM_ID, data=expected_frame, end_stream=True
        )

    def test_send_data_with_end_stream(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)

        engine.send_data(stream_id=CLIENT_BIDI_STREAM_ID, data=b"", end_stream=True)

        mock_quic.send_stream_data.assert_any_call(stream_id=CLIENT_BIDI_STREAM_ID, data=b"", end_stream=True)

    def test_send_datagram_success(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)

        engine.send_datagram(stream_id=CLIENT_BIDI_STREAM_ID, data=b"hello")

        expected_payload = encode_uint_var(0) + b"hello"
        mock_quic.send_datagram_frame.assert_called_with(data=expected_payload)

    def test_send_headers_twice_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers={":method": "GET"})

        with pytest.raises(ProtocolError, match="HEADERS frame is not allowed after initial headers") as excinfo:
            engine.send_headers(stream_id=CLIENT_BIDI_STREAM_ID, headers={":method": "POST"})

        assert excinfo.value.error_code == ErrorCodes.H3_FRAME_UNEXPECTED

    def test_send_datagram_on_uni_stream_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)

        with pytest.raises(
            ProtocolError, match="Datagrams can only be sent for client-initiated bidirectional streams"
        ) as excinfo:
            engine.send_datagram(stream_id=CLIENT_UNI_STREAM_ID, data=b"fail")

        assert excinfo.value.error_code == ErrorCodes.H3_STREAM_CREATION_ERROR


class TestWebTransportH3EngineEventHandling:
    def test_handle_datagram_received(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        event = DatagramFrameReceived(data=encode_uint_var(0) + b"datagram content")

        h3_events = engine.handle_event(event=event)

        assert len(h3_events) == 1
        assert isinstance(h3_events[0], DatagramReceived)
        assert h3_events[0].data == b"datagram content"

    def test_handle_bidi_webtransport_setup_and_data(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        setup_frame = encode_uint_var(FrameType.WEBTRANSPORT_STREAM) + encode_uint_var(789)
        event1 = StreamDataReceived(data=setup_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)
        engine.handle_event(event=event1)
        event2 = StreamDataReceived(data=b"some stream data", stream_id=CLIENT_BIDI_STREAM_ID, end_stream=True)

        h3_events = engine.handle_event(event=event2)

        assert len(h3_events) == 1
        assert isinstance(h3_events[0], WebTransportStreamDataReceived)
        assert h3_events[0].session_id == 789

    def test_handle_uni_webtransport_setup_and_data(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        setup_and_data = encode_uint_var(StreamType.WEBTRANSPORT) + encode_uint_var(101) + b"uni data"
        event = StreamDataReceived(data=setup_and_data, stream_id=CLIENT_UNI_STREAM_ID, end_stream=True)

        h3_events = engine.handle_event(event=event)

        assert len(h3_events) == 1
        assert isinstance(h3_events[0], WebTransportStreamDataReceived)
        assert h3_events[0].session_id == 101

    def test_handle_request_headers_and_data(self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]) -> None:
        mock_quic.configuration.is_client = False
        engine = WebTransportH3Engine(quic=mock_quic)
        mock_pylsqpack["decoder_instance"].feed_header.return_value = (
            b"decoder-stream-bytes",
            [(b":method", b"GET"), (b":path", b"/"), (b":authority", b"test.com")],
        )
        headers_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"encoded-headers")
        event1 = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)
        data_frame = encode_frame(frame_type=FrameType.DATA, frame_data=b"request body")
        event2 = StreamDataReceived(data=data_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=True)

        h3_events1 = engine.handle_event(event=event1)
        h3_events2 = engine.handle_event(event=event2)

        assert len(h3_events1) == 1
        assert isinstance(h3_events1[0], HeadersReceived)
        assert len(h3_events2) == 1
        assert isinstance(h3_events2[0], DataReceived)

    def test_handle_control_stream_settings(self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        settings = {Setting.H3_DATAGRAM: 1, Setting.ENABLE_WEBTRANSPORT: 1}
        settings_frame = encode_frame(
            frame_type=FrameType.SETTINGS, frame_data=encode_settings(settings={int(k): v for k, v in settings.items()})
        )
        data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event = StreamDataReceived(data=data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        assert engine._settings_received is True

    def test_handle_qpack_streams(self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        encoder_data = encode_uint_var(StreamType.QPACK_ENCODER) + b"encoder-data"
        event1 = StreamDataReceived(data=encoder_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event1)

        mock_pylsqpack["decoder_instance"].feed_encoder.assert_called_with(b"encoder-data")

    def test_handle_partial_frame_data(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.headers_recv_state = HeadersState.AFTER_HEADERS
        data_frame = encode_frame(frame_type=FrameType.DATA, frame_data=b"1234567890")
        event1 = StreamDataReceived(data=data_frame[:5], stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)
        event2 = StreamDataReceived(data=data_frame[5:], stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events1 = engine.handle_event(event=event1)
        h3_events2 = engine.handle_event(event=event2)

        assert len(h3_events1) == 1
        assert isinstance(h3_events1[0], DataReceived)
        assert h3_events1[0].data == b"123"
        assert len(h3_events2) == 1
        assert isinstance(h3_events2[0], DataReceived)
        assert h3_events2[0].data == b"4567890"

    def test_empty_data_frame_with_end_stream(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.headers_recv_state = HeadersState.AFTER_HEADERS
        data_frame = encode_frame(frame_type=FrameType.DATA, frame_data=b"")
        event = StreamDataReceived(data=data_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=True)

        h3_events = engine.handle_event(event=event)

        assert len(h3_events) == 1
        assert isinstance(h3_events[0], DataReceived)
        assert h3_events[0].data == b""
        assert h3_events[0].stream_ended is True

    def test_empty_data_frame_without_end_stream(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.headers_recv_state = HeadersState.AFTER_HEADERS
        data_frame = encode_frame(frame_type=FrameType.DATA, frame_data=b"")
        event = StreamDataReceived(data=data_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=event)

        assert not h3_events

    def test_handle_qpack_stream_blocked_and_resumed(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]
    ) -> None:
        mock_pylsqpack["decoder_instance"].feed_header.side_effect = pylsqpack.StreamBlocked
        engine = WebTransportH3Engine(quic=mock_quic)
        headers_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"blocked-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events_blocked = engine.handle_event(event=event)
        assert not h3_events_blocked

        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        assert stream.blocked is True
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        qpack_data = encode_uint_var(StreamType.QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        h3_events_resumed = engine.handle_event(event=qpack_event)

        assert len(h3_events_resumed) == 1
        assert isinstance(h3_events_resumed[0], HeadersReceived)
        assert h3_events_resumed[0].headers == {":status": "201"}
        assert stream.blocked is False

    def test_unblocked_stream_reblocks(self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        mock_pylsqpack["decoder_instance"].resume_header.side_effect = pylsqpack.StreamBlocked
        qpack_data = encode_uint_var(StreamType.QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=qpack_event)

        assert not h3_events
        assert stream.blocked is True

    def test_unblocked_stream_with_buffered_data(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        stream.blocked_frame_size = 10
        stream.buffer = encode_frame(frame_type=FrameType.DATA, frame_data=b"buffered")
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        qpack_data = encode_uint_var(StreamType.QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=qpack_event)

        assert len(h3_events) == 2
        assert isinstance(h3_events[0], HeadersReceived)
        assert isinstance(h3_events[1], DataReceived)
        assert h3_events[1].data == b"buffered"

    @pytest.mark.parametrize("partial_data", [b"\x41", encode_uint_var(FrameType.WEBTRANSPORT_STREAM) + b"\x9f"])
    def test_partial_bidi_webtransport_frame(self, mock_quic: MagicMock, partial_data: bytes) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        event = StreamDataReceived(data=partial_data, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=event)

        assert not h3_events
        assert engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID).buffer == partial_data

    @pytest.mark.parametrize(
        "partial_data, expected_buffer",
        [(b"\x54", b"\x54"), (encode_uint_var(StreamType.WEBTRANSPORT) + b"\x9f", b"\x9f")],
    )
    def test_partial_uni_webtransport_frame(
        self, mock_quic: MagicMock, partial_data: bytes, expected_buffer: bytes
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        event = StreamDataReceived(data=partial_data, stream_id=CLIENT_UNI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=event)

        assert not h3_events
        assert engine._get_or_create_stream(stream_id=CLIENT_UNI_STREAM_ID).buffer == expected_buffer

    def test_partial_non_data_frame(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        headers_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"some-header-payload")
        event = StreamDataReceived(data=headers_frame[:-1], stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=event)

        assert not h3_events
        assert engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID).buffer == b"some-header-payloa"

    def test_receive_data_on_blocked_stream(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        event = StreamDataReceived(data=b"some data", stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=event)

        assert not h3_events
        assert stream.buffer == b"some data"

    def test_unblocked_stream_resume_fails_with_protocol_error(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        mock_pylsqpack["decoder_instance"].resume_header.side_effect = ProtocolError(
            message="Resumption failed", error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR
        )
        qpack_data = encode_uint_var(StreamType.QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=qpack_event)

        expected_reason = str(
            ProtocolError(message="Resumption failed", error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR, reason_phrase=expected_reason
        )

    def test_handle_event_protocol_error(self, mock_quic: MagicMock, mocker: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        error = ProtocolError(message="Test error", error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR)
        mocker.patch.object(engine, "_get_or_create_stream", side_effect=error)
        event = StreamDataReceived(data=b"some data", stream_id=CLIENT_UNI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=event)

        assert not h3_events
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_GENERAL_PROTOCOL_ERROR, reason_phrase=str(error)
        )

    def test_handle_partial_uni_webtransport_data(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        event1 = StreamDataReceived(
            data=encode_uint_var(StreamType.WEBTRANSPORT), stream_id=CLIENT_UNI_STREAM_ID, end_stream=False
        )
        h3_events1 = engine.handle_event(event=event1)
        assert not h3_events1

        event2 = StreamDataReceived(data=encode_uint_var(101), stream_id=CLIENT_UNI_STREAM_ID, end_stream=False)
        h3_events2 = engine.handle_event(event=event2)
        assert not h3_events2

        event3 = StreamDataReceived(data=b"uni data", stream_id=CLIENT_UNI_STREAM_ID, end_stream=True)
        h3_events3 = engine.handle_event(event=event3)
        assert len(h3_events3) == 1
        assert isinstance(h3_events3[0], WebTransportStreamDataReceived)
        assert h3_events3[0].session_id == 101
        assert h3_events3[0].data == b"uni data"
        assert h3_events3[0].stream_ended is True

    def test_unblocked_stream_with_no_blocked_frame_size(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]
    ) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.blocked = True
        stream.blocked_frame_size = None
        mock_pylsqpack["decoder_instance"].feed_encoder.return_value = [CLIENT_BIDI_STREAM_ID]
        qpack_data = encode_uint_var(StreamType.QPACK_ENCODER) + b"qpack-unblock-data"
        qpack_event = StreamDataReceived(data=qpack_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        with pytest.raises(AssertionError, match="Frame length for logging cannot be None"):
            engine.handle_event(event=qpack_event)

    def test_unhandled_quic_event_is_ignored(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        event = QuicEvent()

        h3_events = engine.handle_event(event=event)

        assert h3_events == []
        assert not mock_quic.close.called


class TestWebTransportH3EngineProtocolErrors:
    @pytest.mark.parametrize(
        "frame_type, error_phrase",
        [
            (FrameType.SETTINGS, "Invalid frame type on request stream"),
            (FrameType.GOAWAY, "Invalid frame type on request stream"),
        ],
    )
    def test_invalid_frame_on_request_stream(self, mock_quic: MagicMock, frame_type: int, error_phrase: str) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.headers_recv_state = HeadersState.AFTER_HEADERS
        frame = encode_frame(frame_type=frame_type, frame_data=b"")
        event = StreamDataReceived(data=frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(ProtocolError(message=error_phrase, error_code=ErrorCodes.H3_FRAME_UNEXPECTED))
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    def test_data_before_headers_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        data_frame = encode_frame(frame_type=FrameType.DATA, frame_data=b"some data")
        event = StreamDataReceived(data=data_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="DATA frame received before HEADERS", error_code=ErrorCodes.H3_FRAME_UNEXPECTED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    def test_second_settings_frame_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        settings = {Setting.H3_DATAGRAM: 1}
        settings_frame = encode_frame(
            frame_type=FrameType.SETTINGS, frame_data=encode_settings(settings={int(k): v for k, v in settings.items()})
        )
        control_data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event1 = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        engine.handle_event(event=event1)
        event2 = StreamDataReceived(data=settings_frame, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event2)

        expected_reason = str(
            ProtocolError(message="SETTINGS frame received twice", error_code=ErrorCodes.H3_FRAME_UNEXPECTED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    def test_invalid_settings_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        settings = {Setting.ENABLE_WEBTRANSPORT: 1, Setting.H3_DATAGRAM: 0}
        settings_frame = encode_frame(
            frame_type=FrameType.SETTINGS, frame_data=encode_settings(settings={int(k): v for k, v in settings.items()})
        )
        data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event = StreamDataReceived(data=data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="ENABLE_WEBTRANSPORT requires H3_DATAGRAM", error_code=ErrorCodes.H3_SETTINGS_ERROR)
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_SETTINGS_ERROR, reason_phrase=expected_reason)

    def test_qpack_decompression_failed(self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]) -> None:
        mock_pylsqpack["decoder_instance"].feed_header.side_effect = pylsqpack.DecompressionFailed("error")
        engine = WebTransportH3Engine(quic=mock_quic)
        headers_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"bad-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="QPACK decompression failed", error_code=ErrorCodes.QPACK_DECOMPRESSION_FAILED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.QPACK_DECOMPRESSION_FAILED, reason_phrase=expected_reason
        )

    def test_first_control_frame_not_settings_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        data_frame = encode_frame(frame_type=FrameType.DATA, frame_data=b"wrong frame")
        control_data = encode_uint_var(StreamType.CONTROL) + data_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message="First frame on control stream must be SETTINGS", error_code=ErrorCodes.H3_MISSING_SETTINGS
            )
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_MISSING_SETTINGS, reason_phrase=expected_reason
        )

    @pytest.mark.parametrize("stream_type", [StreamType.CONTROL, StreamType.QPACK_DECODER, StreamType.QPACK_ENCODER])
    def test_duplicate_uni_streams_fail(self, mock_quic: MagicMock, stream_type: StreamType) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream_data = encode_uint_var(stream_type)
        event1 = StreamDataReceived(data=stream_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        engine.handle_event(event=event1)
        assert not mock_quic.close.called
        event2 = StreamDataReceived(data=stream_data, stream_id=SERVER_UNI_STREAM_ID + 4, end_stream=False)

        engine.handle_event(event=event2)

        mock_quic.close.assert_called_once()
        assert "Only one" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_STREAM_CREATION_ERROR

    def test_h3_datagram_without_transport_param_fails(self, mock_quic: MagicMock) -> None:
        mock_quic._remote_max_datagram_frame_size = None
        engine = WebTransportH3Engine(quic=mock_quic)
        settings = {Setting.H3_DATAGRAM: 1}
        settings_frame = encode_frame(
            frame_type=FrameType.SETTINGS, frame_data=encode_settings(settings={int(k): v for k, v in settings.items()})
        )
        control_data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message="H3_DATAGRAM requires max_datagram_frame_size transport parameter",
                error_code=ErrorCodes.H3_SETTINGS_ERROR,
            )
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_SETTINGS_ERROR, reason_phrase=expected_reason)

    def test_control_stream_closed_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        control_data = encode_uint_var(StreamType.CONTROL)
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=True)

        engine.handle_event(event=event)

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
                StreamType.QPACK_ENCODER,
                "QPACK encoder stream error",
                ErrorCodes.QPACK_ENCODER_STREAM_ERROR,
            ),
            (
                pylsqpack.DecoderStreamError("decoder error"),
                StreamType.QPACK_DECODER,
                "QPACK decoder stream error",
                ErrorCodes.QPACK_DECODER_STREAM_ERROR,
            ),
        ],
    )
    def test_qpack_stream_errors(
        self,
        mock_quic: MagicMock,
        mock_pylsqpack: dict[str, MagicMock],
        error_fixture: Exception,
        stream_type: StreamType,
        reason: str,
        error_code: int,
    ) -> None:
        if isinstance(error_fixture, pylsqpack.EncoderStreamError):
            mock_pylsqpack["decoder_instance"].feed_encoder.side_effect = error_fixture
        else:
            mock_pylsqpack["encoder_instance"].feed_decoder.side_effect = error_fixture
        engine = WebTransportH3Engine(quic=mock_quic)
        stream_data = encode_uint_var(stream_type) + b"some-qpack-data"
        event = StreamDataReceived(data=stream_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(ProtocolError(message=reason, error_code=error_code))
        mock_quic.close.assert_called_once_with(error_code=error_code, reason_phrase=expected_reason)

    def test_handle_malformed_datagram(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        event = DatagramFrameReceived(data=b"\xc0")

        engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(
                message="Could not parse quarter stream ID from datagram",
                error_code=ErrorCodes.H3_DATAGRAM_ERROR,
            )
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_DATAGRAM_ERROR, reason_phrase=expected_reason)


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
    def test_invalid_request_headers(
        self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock], headers: list, error_match: str
    ) -> None:
        mock_quic.configuration.is_client = False
        engine = WebTransportH3Engine(quic=mock_quic)
        mock_pylsqpack["decoder_instance"].feed_header.return_value = (b"", headers)
        headers_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"bad-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        reason_phrase = mock_quic.close.call_args.kwargs["reason_phrase"]
        assert re.search(error_match, reason_phrase)
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_MESSAGE_ERROR

    def test_invalid_response_headers(self, mock_quic: MagicMock, mock_pylsqpack: dict[str, MagicMock]) -> None:
        mock_quic.configuration.is_client = True
        engine = WebTransportH3Engine(quic=mock_quic)
        mock_pylsqpack["decoder_instance"].feed_header.return_value = (b"", [(b"some", b"header")])
        headers_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"bad-headers")
        event = StreamDataReceived(data=headers_frame, stream_id=SERVER_BIDI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        reason_phrase = mock_quic.close.call_args.kwargs["reason_phrase"]
        assert re.search("Pseudo-headers.*:status.*are missing", reason_phrase)
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_MESSAGE_ERROR


class TestWebTransportH3EngineMiscErrors:
    def test_malformed_settings_frame_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        settings_frame = encode_frame(frame_type=FrameType.SETTINGS, frame_data=b"\x06")
        control_data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        expected_reason = str(
            ProtocolError(message="Malformed SETTINGS frame payload", error_code=ErrorCodes.H3_FRAME_ERROR)
        )
        mock_quic.close.assert_called_once_with(error_code=ErrorCodes.H3_FRAME_ERROR, reason_phrase=expected_reason)

    def test_buffer_read_error_on_frame_header(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        stream = engine._get_or_create_stream(stream_id=CLIENT_BIDI_STREAM_ID)
        stream.headers_recv_state = HeadersState.AFTER_HEADERS
        event = StreamDataReceived(data=b"\x00", stream_id=CLIENT_BIDI_STREAM_ID, end_stream=False)

        h3_events = engine.handle_event(event=event)

        assert not h3_events
        assert not mock_quic.close.called
        assert stream.buffer == b"\x00"

    def test_invalid_boolean_setting_value(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        settings = {Setting.ENABLE_WEBTRANSPORT: 2}
        settings_frame = encode_frame(
            frame_type=FrameType.SETTINGS, frame_data=encode_settings(settings={int(k): v for k, v in settings.items()})
        )
        control_data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        assert "setting must be 0 or 1" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_SETTINGS_ERROR

    def test_reserved_setting_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        settings = {0x02: 1}
        settings_frame = encode_frame(frame_type=FrameType.SETTINGS, frame_data=encode_settings(settings=settings))
        control_data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        assert "Setting identifier 0x2 is reserved" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_SETTINGS_ERROR

    def test_handle_event_after_done(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        engine._is_done = True
        event = DatagramFrameReceived(data=b"some data")

        h3_events = engine.handle_event(event=event)

        assert not h3_events
        assert not mock_quic.close.called

    def test_headers_on_control_stream_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        settings = {Setting.H3_DATAGRAM: 1}
        settings_frame = encode_frame(
            frame_type=FrameType.SETTINGS, frame_data=encode_settings(settings={int(k): v for k, v in settings.items()})
        )
        control_data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event1 = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)
        engine.handle_event(event=event1)
        headers_frame = encode_frame(frame_type=FrameType.HEADERS, frame_data=b"")
        event2 = StreamDataReceived(data=headers_frame, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event2)

        expected_reason = str(
            ProtocolError(message="Invalid frame type on control stream", error_code=ErrorCodes.H3_FRAME_UNEXPECTED)
        )
        mock_quic.close.assert_called_once_with(
            error_code=ErrorCodes.H3_FRAME_UNEXPECTED, reason_phrase=expected_reason
        )

    def test_duplicate_setting_fails(self, mock_quic: MagicMock) -> None:
        engine = WebTransportH3Engine(quic=mock_quic)
        buf = encode_uint_var(Setting.H3_DATAGRAM) + encode_uint_var(1)
        buf += encode_uint_var(Setting.H3_DATAGRAM) + encode_uint_var(1)
        settings_frame = encode_frame(frame_type=FrameType.SETTINGS, frame_data=buf)
        control_data = encode_uint_var(StreamType.CONTROL) + settings_frame
        event = StreamDataReceived(data=control_data, stream_id=SERVER_UNI_STREAM_ID, end_stream=False)

        engine.handle_event(event=event)

        mock_quic.close.assert_called_once()
        assert "is included twice" in mock_quic.close.call_args.kwargs["reason_phrase"]
        assert mock_quic.close.call_args.kwargs["error_code"] == ErrorCodes.H3_SETTINGS_ERROR
