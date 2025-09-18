"""
A specialized HTTP/3 protocol engine for WebTransport.
"""

from __future__ import annotations

from enum import Enum

import pylsqpack
from aioquic.buffer import UINT_VAR_MAX_SIZE, Buffer, BufferReadError, encode_uint_var
from aioquic.quic.connection import QuicConnection, stream_is_unidirectional
from aioquic.quic.events import DatagramFrameReceived, QuicEvent, StreamDataReceived
from aioquic.quic.logger import QuicLoggerTrace

from pywebtransport import constants
from pywebtransport.config import ClientConfig, ServerConfig
from pywebtransport.constants import ErrorCodes
from pywebtransport.events import EventEmitter
from pywebtransport.exceptions import ProtocolError
from pywebtransport.protocol.events import (
    CapsuleReceived,
    DatagramReceived,
    H3Event,
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from pywebtransport.types import EventType, Headers, StreamId
from pywebtransport.utils import get_logger

__all__ = ["WebTransportH3Engine"]

COLON = 0x3A
CR = 0x0D
HTAB = 0x09
LF = 0x0A
NUL = 0x0
RESERVED_SETTINGS = (0x0, 0x2, 0x3, 0x4, 0x5)
SP = 0x20
WHITESPACE = (SP, HTAB)

logger = get_logger(name="protocol.h3_engine")

_RawHeaders = list[tuple[bytes, bytes]]


class HeadersState(Enum):
    """The state for tracking header frames on a stream."""

    INITIAL = 0
    AFTER_HEADERS = 1


class H3Stream:
    """The state of a single HTTP/3 stream."""

    def __init__(self, *, stream_id: int) -> None:
        """Initialize an H3Stream."""
        self.blocked = False
        self.blocked_frame_size: int | None = None
        self.buffer = b""
        self.ended = False
        self.frame_size: int | None = None
        self.frame_type: int | None = None
        self.headers_recv_state: HeadersState = HeadersState.INITIAL
        self.headers_send_state: HeadersState = HeadersState.INITIAL
        self.session_id: int | None = None
        self.stream_id = stream_id
        self.stream_type: int | None = None
        self.is_draining = False


class WebTransportH3Engine(EventEmitter):
    """A protocol engine for handling WebTransport over HTTP/3."""

    def __init__(self, quic: QuicConnection, *, config: ClientConfig | ServerConfig) -> None:
        """Initialize the WebTransportH3Engine."""
        super().__init__()
        self._config = config
        self._max_table_capacity = 4096
        self._blocked_streams = 16
        self._is_client = quic.configuration.is_client
        self._is_done = False
        self._quic = quic
        self._quic_logger: QuicLoggerTrace | None = quic._quic_logger
        self._decoder = pylsqpack.Decoder(self._max_table_capacity, self._blocked_streams)
        self._encoder = pylsqpack.Encoder()
        self._settings_received = False
        self._stream: dict[int, H3Stream] = {}
        self._local_control_stream_id: int | None = None
        self._local_decoder_stream_id: int | None = None
        self._local_encoder_stream_id: int | None = None
        self._peer_control_stream_id: int | None = None
        self._peer_decoder_stream_id: int | None = None
        self._peer_encoder_stream_id: int | None = None

        self._init_connection()

    def create_webtransport_stream(self, *, session_id: int, is_unidirectional: bool = False) -> int:
        """Create a new WebTransport stream."""
        if is_unidirectional:
            stream_id = self._create_uni_stream(stream_type=constants.H3_STREAM_TYPE_WEBTRANSPORT)
            stream = self._get_or_create_stream(stream_id=stream_id)
            stream.session_id = session_id
            stream.stream_type = constants.H3_STREAM_TYPE_WEBTRANSPORT
            self._quic.send_stream_data(stream_id=stream_id, data=encode_uint_var(session_id))
        else:
            stream_id = self._quic.get_next_available_stream_id()
            stream = self._get_or_create_stream(stream_id=stream_id)
            stream.session_id = session_id
            stream.stream_type = constants.H3_STREAM_TYPE_WEBTRANSPORT
            self._log_stream_type(stream_id=stream_id, stream_type=constants.H3_STREAM_TYPE_WEBTRANSPORT)
            self._quic.send_stream_data(
                stream_id=stream_id,
                data=encode_uint_var(constants.H3_FRAME_TYPE_WEBTRANSPORT_STREAM) + encode_uint_var(session_id),
            )
        return stream_id

    async def handle_event(self, *, event: QuicEvent) -> list[H3Event]:
        """Handle a QUIC event and return a list of H3 events."""
        if self._is_done:
            return []

        try:
            match event:
                case StreamDataReceived(data=data, end_stream=end_stream, stream_id=stream_id):
                    stream = self._get_or_create_stream(stream_id=stream_id)
                    if stream_is_unidirectional(stream_id):
                        return await self._receive_stream_data_uni(stream=stream, data=data, stream_ended=end_stream)
                    else:
                        return self._receive_request_data(stream=stream, data=data, stream_ended=end_stream)
                case DatagramFrameReceived(data=data):
                    return self._receive_datagram(data=data)
                case _:
                    return []
        except ProtocolError as exc:
            self._is_done = True
            self._quic.close(error_code=exc.error_code, reason_phrase=str(exc))
        return []

    def send_capsule(self, *, stream_id: StreamId, capsule_data: bytes) -> None:
        """Send a capsule on a stream."""
        if not stream_is_request_response(stream_id=stream_id):
            raise ProtocolError(
                message="Capsules can only be sent on client-initiated bidirectional streams.",
                error_code=ErrorCodes.H3_STREAM_CREATION_ERROR,
            )

        self._quic.send_stream_data(stream_id=stream_id, data=capsule_data)

    def send_data(self, *, stream_id: int, data: bytes, end_stream: bool) -> None:
        """Send data on a stream."""
        if data or end_stream:
            self._quic.send_stream_data(stream_id=stream_id, data=data, end_stream=end_stream)

    def send_datagram(self, *, stream_id: int, data: bytes) -> None:
        """Send a datagram."""
        if not stream_is_request_response(stream_id=stream_id):
            raise ProtocolError(
                message="Datagrams can only be sent for client-initiated bidirectional streams",
                error_code=ErrorCodes.H3_STREAM_CREATION_ERROR,
            )

        self._quic.send_datagram_frame(data=encode_uint_var(stream_id // 4) + data)

    def send_headers(self, *, stream_id: StreamId, headers: Headers, end_stream: bool = False) -> None:
        """Send headers on a stream."""
        stream = self._get_or_create_stream(stream_id=stream_id)
        if stream.headers_send_state == HeadersState.AFTER_HEADERS:
            raise ProtocolError(
                message="HEADERS frame is not allowed after initial headers",
                error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
            )

        raw_headers: _RawHeaders = [(k.encode("utf-8"), v.encode("utf-8")) for k, v in headers.items()]
        frame_data = self._encode_headers(stream_id=stream_id, headers=raw_headers)

        if self._quic_logger is not None:
            self._quic_logger.log_event(
                category="http",
                event="frame_created",
                data=self._quic_logger.encode_http3_headers_frame(
                    length=len(frame_data), headers=raw_headers, stream_id=stream_id
                ),
            )

        stream.headers_send_state = HeadersState.AFTER_HEADERS
        self._quic.send_stream_data(
            stream_id=stream_id,
            data=encode_frame(frame_type=constants.H3_FRAME_TYPE_HEADERS, frame_data=frame_data),
            end_stream=end_stream,
        )

    def _create_uni_stream(self, *, stream_type: int) -> int:
        """Create a unidirectional stream of a given type."""
        stream_id = self._quic.get_next_available_stream_id(is_unidirectional=True)

        self._log_stream_type(stream_id=stream_id, stream_type=stream_type)
        self._quic.send_stream_data(stream_id=stream_id, data=encode_uint_var(stream_type))

        return stream_id

    def _decode_headers(self, *, stream_id: int, frame_data: bytes | None) -> tuple[_RawHeaders, Headers]:
        """Decode a HEADERS frame."""
        try:
            if frame_data is None:
                decoder, raw_headers = self._decoder.resume_header(stream_id)
            else:
                decoder, raw_headers = self._decoder.feed_header(stream_id, frame_data)

            if self._local_decoder_stream_id is not None:
                self._quic.send_stream_data(stream_id=self._local_decoder_stream_id, data=decoder)
        except pylsqpack.DecompressionFailed as exc:
            raise ProtocolError(
                message="QPACK decompression failed",
                error_code=ErrorCodes.QPACK_DECOMPRESSION_FAILED,
            ) from exc

        app_headers: Headers = {k.decode("utf-8", "ignore"): v.decode("utf-8", "ignore") for k, v in raw_headers}
        return raw_headers, app_headers

    def _encode_headers(self, *, stream_id: int, headers: _RawHeaders) -> bytes:
        """Encode a HEADERS frame."""
        encoder, frame_data = self._encoder.encode(stream_id, headers)
        if self._local_encoder_stream_id is not None:
            self._quic.send_stream_data(stream_id=self._local_encoder_stream_id, data=encoder)
        return frame_data

    def _get_local_settings(self) -> dict[int, int]:
        """Get the local HTTP/3 settings."""
        settings: dict[int, int] = {
            constants.SETTINGS_ENABLE_CONNECT_PROTOCOL: 1,
            constants.SETTINGS_H3_DATAGRAM: 1,
            constants.SETTINGS_QPACK_BLOCKED_STREAMS: self._blocked_streams,
            constants.SETTINGS_QPACK_MAX_TABLE_CAPACITY: self._max_table_capacity,
            constants.SETTINGS_WT_INITIAL_MAX_DATA: self._config.initial_max_data,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI: self._config.initial_max_streams_bidi,
            constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI: self._config.initial_max_streams_uni,
        }
        if isinstance(self._config, ServerConfig):
            settings[constants.SETTINGS_WT_MAX_SESSIONS] = self._config.max_sessions
        else:
            settings[constants.SETTINGS_WT_MAX_SESSIONS] = 1
        return settings

    def _get_or_create_stream(self, *, stream_id: int) -> H3Stream:
        """Get or create an H3Stream instance for a given stream ID."""
        if stream_id not in self._stream:
            self._stream[stream_id] = H3Stream(stream_id=stream_id)
        return self._stream[stream_id]

    async def _handle_control_frame(self, *, frame_type: int, frame_data: bytes) -> None:
        """Handle a frame received on the control stream."""
        if frame_type != constants.H3_FRAME_TYPE_SETTINGS and not self._settings_received:
            raise ProtocolError(
                message="First frame on control stream must be SETTINGS",
                error_code=ErrorCodes.H3_MISSING_SETTINGS,
            )

        match frame_type:
            case constants.H3_FRAME_TYPE_SETTINGS:
                if self._settings_received:
                    raise ProtocolError(
                        message="SETTINGS frame received twice",
                        error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
                    )
                settings = parse_settings(data=frame_data)
                self._validate_settings(settings=settings)
                self._received_settings = settings
                encoder = self._encoder.apply_settings(
                    max_table_capacity=settings.get(constants.SETTINGS_QPACK_MAX_TABLE_CAPACITY, 0),
                    blocked_streams=settings.get(constants.SETTINGS_QPACK_BLOCKED_STREAMS, 0),
                )
                if self._local_encoder_stream_id is not None:
                    self._quic.send_stream_data(stream_id=self._local_encoder_stream_id, data=encoder)
                self._settings_received = True
                await self.emit(event_type=EventType.SETTINGS_RECEIVED, data={"settings": settings})
            case constants.H3_FRAME_TYPE_HEADERS:
                raise ProtocolError(
                    message="Invalid frame type on control stream",
                    error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
                )
            case _:
                pass

    def _handle_request_frame(
        self, *, frame_type: int, frame_data: bytes | None, stream: H3Stream, stream_ended: bool
    ) -> list[H3Event]:
        """Handle a frame received on a request stream."""
        match frame_type:
            case constants.H3_FRAME_TYPE_DATA:
                if stream.headers_recv_state != HeadersState.AFTER_HEADERS:
                    raise ProtocolError(
                        message="DATA frame received before HEADERS",
                        error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
                    )
                pass
            case constants.H3_FRAME_TYPE_HEADERS:
                if stream.headers_recv_state == HeadersState.AFTER_HEADERS:
                    if stream.is_draining:
                        return []
                    raise ProtocolError(
                        message="HEADERS frame received after initial headers",
                        error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
                    )

                raw_headers, app_headers = self._decode_headers(stream_id=stream.stream_id, frame_data=frame_data)

                if self._is_client:
                    validate_response_headers(headers=raw_headers)
                else:
                    validate_request_headers(headers=raw_headers)

                if self._quic_logger is not None:
                    length = len(frame_data) if frame_data is not None else stream.blocked_frame_size
                    assert length is not None, "Frame length for logging cannot be None"
                    self._quic_logger.log_event(
                        category="http",
                        event="frame_parsed",
                        data=self._quic_logger.encode_http3_headers_frame(
                            length=length,
                            headers=raw_headers,
                            stream_id=stream.stream_id,
                        ),
                    )
                stream.headers_recv_state = HeadersState.AFTER_HEADERS
                return [
                    HeadersReceived(
                        headers=app_headers,
                        stream_id=stream.stream_id,
                        stream_ended=stream_ended,
                    )
                ]
            case constants.H3_FRAME_TYPE_SETTINGS | constants.H3_FRAME_TYPE_GOAWAY:
                raise ProtocolError(
                    message="Invalid frame type on request stream",
                    error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
                )
            case (
                constants.H3_FRAME_TYPE_CANCEL_PUSH
                | constants.H3_FRAME_TYPE_MAX_PUSH_ID
                | constants.H3_FRAME_TYPE_PUSH_PROMISE
            ):
                pass

        return []

    def _init_connection(self) -> None:
        """Initialize the HTTP/3 connection by creating unidirectional streams."""
        self._local_control_stream_id = self._create_uni_stream(stream_type=constants.H3_STREAM_TYPE_CONTROL)
        self._sent_settings = self._get_local_settings()
        self._quic.send_stream_data(
            stream_id=self._local_control_stream_id,
            data=encode_frame(
                frame_type=constants.H3_FRAME_TYPE_SETTINGS,
                frame_data=encode_settings(settings=self._sent_settings),
            ),
        )
        self._local_encoder_stream_id = self._create_uni_stream(stream_type=constants.H3_STREAM_TYPE_QPACK_ENCODER)
        self._local_decoder_stream_id = self._create_uni_stream(stream_type=constants.H3_STREAM_TYPE_QPACK_DECODER)

    def _log_stream_type(self, *, stream_id: int, stream_type: int) -> None:
        """Log the unidirectional stream type for debugging."""
        if self._quic_logger is not None:
            type_name = {
                constants.H3_STREAM_TYPE_CONTROL: "control",
                constants.H3_STREAM_TYPE_PUSH: "push",
                constants.H3_STREAM_TYPE_QPACK_ENCODER: "qpack_encoder",
                constants.H3_STREAM_TYPE_QPACK_DECODER: "qpack_decoder",
                constants.H3_STREAM_TYPE_WEBTRANSPORT: "webtransport",
            }.get(stream_type, "unknown")
            data = {"new": type_name, "stream_id": stream_id}
            self._quic_logger.log_event(category="http", event="stream_type_set", data=data)

    def _receive_datagram(self, *, data: bytes) -> list[H3Event]:
        """Parse an incoming datagram."""
        buf = Buffer(data=data)

        try:
            quarter_stream_id = buf.pull_uint_var()
        except BufferReadError:
            raise ProtocolError(
                message="Could not parse quarter stream ID from datagram",
                error_code=ErrorCodes.H3_DATAGRAM_ERROR,
            )

        return [DatagramReceived(data=data[buf.tell() :], stream_id=quarter_stream_id * 4)]

    def _receive_request_data(self, *, stream: H3Stream, data: bytes, stream_ended: bool) -> list[H3Event]:
        """Handle incoming data on a bidirectional request stream."""
        http_events: list[H3Event] = []
        stream.buffer += data
        if stream_ended:
            stream.ended = True
        if stream.blocked:
            return http_events

        if stream.session_id is None:
            buf = Buffer(data=stream.buffer)
            try:
                frame_type = buf.pull_uint_var()
                if frame_type == constants.H3_FRAME_TYPE_WEBTRANSPORT_STREAM:
                    session_id_int = buf.pull_uint_var()
                    stream.session_id = session_id_int
                    stream.stream_type = constants.H3_STREAM_TYPE_WEBTRANSPORT
                    consumed = buf.tell()
                    stream.buffer = stream.buffer[consumed:]
                    self._log_stream_type(stream_id=stream.stream_id, stream_type=constants.H3_STREAM_TYPE_WEBTRANSPORT)
            except BufferReadError:
                return http_events

        if stream.stream_type == constants.H3_STREAM_TYPE_WEBTRANSPORT:
            if stream.buffer or stream_ended:
                assert stream.session_id is not None
                http_events.append(
                    WebTransportStreamDataReceived(
                        data=stream.buffer,
                        session_id=stream.session_id,
                        stream_id=stream.stream_id,
                        stream_ended=stream_ended,
                    )
                )
                stream.buffer = b""
            return http_events

        buf = Buffer(data=stream.buffer)
        consumed = 0
        while not buf.eof():
            if stream.headers_recv_state == HeadersState.AFTER_HEADERS:
                try:
                    capsule_type = buf.pull_uint_var()
                    if capsule_type in (
                        constants.H3_FRAME_TYPE_DATA,
                        constants.H3_FRAME_TYPE_HEADERS,
                        constants.H3_FRAME_TYPE_SETTINGS,
                        constants.H3_FRAME_TYPE_GOAWAY,
                        constants.H3_FRAME_TYPE_CANCEL_PUSH,
                        constants.H3_FRAME_TYPE_PUSH_PROMISE,
                        constants.H3_FRAME_TYPE_MAX_PUSH_ID,
                    ):
                        raise ProtocolError(
                            message=f"Invalid H3 frame type ({hex(capsule_type)}) received on Capsule stream",
                            error_code=ErrorCodes.H3_FRAME_UNEXPECTED,
                        )
                    capsule_length = buf.pull_uint_var()
                    if buf.tell() + capsule_length > len(stream.buffer):
                        break
                    capsule_value = buf.pull_bytes(capsule_length)
                    consumed = buf.tell()
                    http_events.append(
                        CapsuleReceived(
                            stream_id=stream.stream_id,
                            capsule_type=capsule_type,
                            capsule_data=capsule_value,
                        )
                    )
                except BufferReadError:
                    break
            else:
                if stream.frame_size is None:
                    try:
                        stream.frame_type = buf.pull_uint_var()
                        stream.frame_size = buf.pull_uint_var()
                    except BufferReadError:
                        break
                    consumed = buf.tell()
                    if self._quic_logger is not None and stream.frame_type == constants.H3_FRAME_TYPE_DATA:
                        self._quic_logger.log_event(
                            category="http",
                            event="frame_parsed",
                            data=self._quic_logger.encode_http3_data_frame(
                                length=stream.frame_size, stream_id=stream.stream_id
                            ),
                        )

                if stream.frame_type is None:
                    break
                chunk_size = min(stream.frame_size, buf.capacity - consumed)
                if stream.frame_type != constants.H3_FRAME_TYPE_DATA and chunk_size < stream.frame_size:
                    break

                frame_data = buf.pull_bytes(chunk_size)
                frame_type = stream.frame_type
                consumed = buf.tell()
                stream.frame_size -= chunk_size
                if not stream.frame_size:
                    stream.frame_size = None
                    stream.frame_type = None

                try:
                    http_events.extend(
                        self._handle_request_frame(
                            frame_type=frame_type,
                            frame_data=frame_data,
                            stream=stream,
                            stream_ended=stream.ended and buf.eof(),
                        )
                    )
                except pylsqpack.StreamBlocked:
                    stream.blocked = True
                    stream.blocked_frame_size = len(frame_data)
                    break
        stream.buffer = stream.buffer[consumed:]
        return http_events

    async def _receive_stream_data_uni(self, *, stream: H3Stream, data: bytes, stream_ended: bool) -> list[H3Event]:
        """Handle incoming data on a unidirectional stream."""
        http_events: list[H3Event] = []
        stream.buffer += data
        if stream_ended:
            stream.ended = True

        if stream.stream_type is None:
            buf = Buffer(data=stream.buffer)
            try:
                stream.stream_type = buf.pull_uint_var()
                consumed = buf.tell()
                if stream.stream_type not in (
                    constants.H3_STREAM_TYPE_CONTROL,
                    constants.H3_STREAM_TYPE_PUSH,
                    constants.H3_STREAM_TYPE_QPACK_DECODER,
                    constants.H3_STREAM_TYPE_QPACK_ENCODER,
                    constants.H3_STREAM_TYPE_WEBTRANSPORT,
                ):
                    stream.buffer = b""
                    return http_events

                if stream.stream_type == constants.H3_STREAM_TYPE_CONTROL:
                    if self._peer_control_stream_id is not None:
                        raise ProtocolError(
                            message="Only one control stream is allowed",
                            error_code=ErrorCodes.H3_STREAM_CREATION_ERROR,
                        )
                    self._peer_control_stream_id = stream.stream_id
                elif stream.stream_type == constants.H3_STREAM_TYPE_QPACK_DECODER:
                    if self._peer_decoder_stream_id is not None:
                        raise ProtocolError(
                            message="Only one QPACK decoder stream is allowed",
                            error_code=ErrorCodes.H3_STREAM_CREATION_ERROR,
                        )
                    self._peer_decoder_stream_id = stream.stream_id
                elif stream.stream_type == constants.H3_STREAM_TYPE_QPACK_ENCODER:
                    if self._peer_encoder_stream_id is not None:
                        raise ProtocolError(
                            message="Only one QPACK encoder stream is allowed",
                            error_code=ErrorCodes.H3_STREAM_CREATION_ERROR,
                        )
                    self._peer_encoder_stream_id = stream.stream_id
                self._log_stream_type(stream_id=stream.stream_id, stream_type=stream.stream_type)
                stream.buffer = stream.buffer[consumed:]
            except BufferReadError:
                return http_events

        if stream.stream_type == constants.H3_STREAM_TYPE_WEBTRANSPORT:
            buf = Buffer(data=stream.buffer)
            consumed = 0
            if stream.session_id is None:
                try:
                    stream.session_id = buf.pull_uint_var()
                    consumed = buf.tell()
                except BufferReadError:
                    return http_events

            payload = stream.buffer[consumed:]
            stream.buffer = b""
            if payload or stream_ended:
                assert stream.session_id is not None
                http_events.append(
                    WebTransportStreamDataReceived(
                        data=payload,
                        session_id=stream.session_id,
                        stream_ended=stream.ended,
                        stream_id=stream.stream_id,
                    )
                )
            return http_events

        if stream.stream_type == constants.H3_STREAM_TYPE_CONTROL and stream.ended:
            raise ProtocolError(
                message="Closing control stream is not allowed",
                error_code=ErrorCodes.H3_CLOSED_CRITICAL_STREAM,
            )

        buf = Buffer(data=stream.buffer)
        consumed = 0
        unblocked_streams: set[int] = set()
        while not buf.eof():
            match stream.stream_type:
                case constants.H3_STREAM_TYPE_CONTROL:
                    try:
                        frame_type = buf.pull_uint_var()
                        frame_length = buf.pull_uint_var()
                        frame_data = buf.pull_bytes(frame_length)
                    except BufferReadError:
                        break
                    consumed = buf.tell()
                    await self._handle_control_frame(frame_type=frame_type, frame_data=frame_data)
                case constants.H3_STREAM_TYPE_QPACK_DECODER:
                    data = buf.pull_bytes(buf.capacity - buf.tell())
                    consumed = buf.tell()
                    try:
                        self._encoder.feed_decoder(data)
                    except pylsqpack.DecoderStreamError as exc:
                        raise ProtocolError(
                            message="QPACK decoder stream error",
                            error_code=ErrorCodes.QPACK_DECODER_STREAM_ERROR,
                        ) from exc
                case constants.H3_STREAM_TYPE_QPACK_ENCODER:
                    data = buf.pull_bytes(buf.capacity - buf.tell())
                    consumed = buf.tell()
                    try:
                        unblocked_streams.update(self._decoder.feed_encoder(data))
                    except pylsqpack.EncoderStreamError as exc:
                        raise ProtocolError(
                            message="QPACK encoder stream error",
                            error_code=ErrorCodes.QPACK_ENCODER_STREAM_ERROR,
                        ) from exc
                case _:
                    break
        stream.buffer = stream.buffer[consumed:]

        for stream_id in unblocked_streams:
            stream = self._stream[stream_id]
            try:
                http_events.extend(
                    self._handle_request_frame(
                        frame_type=constants.H3_FRAME_TYPE_HEADERS,
                        frame_data=None,
                        stream=stream,
                        stream_ended=stream.ended and not stream.buffer,
                    )
                )
            except pylsqpack.StreamBlocked:
                stream.blocked = True
                stream.blocked_frame_size = 0
                continue

            stream.blocked = False
            stream.blocked_frame_size = None
            if stream.buffer:
                http_events.extend(self._receive_request_data(stream=stream, data=b"", stream_ended=stream.ended))

        return http_events

    def _validate_settings(self, *, settings: dict[int, int]) -> None:
        """Validate the peer's HTTP/3 settings."""
        if settings.get(constants.SETTINGS_ENABLE_CONNECT_PROTOCOL) not in (None, 1):
            raise ProtocolError(
                message="ENABLE_CONNECT_PROTOCOL setting must be 1 if present",
                error_code=ErrorCodes.H3_SETTINGS_ERROR,
            )
        if self._quic._remote_max_datagram_frame_size is None and settings.get(constants.SETTINGS_H3_DATAGRAM) == 1:
            raise ProtocolError(
                message="H3_DATAGRAM requires max_datagram_frame_size transport parameter",
                error_code=ErrorCodes.H3_SETTINGS_ERROR,
            )
        if (
            settings.get(constants.SETTINGS_WT_MAX_SESSIONS, 0) > 0
            and settings.get(constants.SETTINGS_H3_DATAGRAM) != 1
        ):
            raise ProtocolError(
                message="WT_MAX_SESSIONS requires H3_DATAGRAM",
                error_code=ErrorCodes.H3_SETTINGS_ERROR,
            )


def encode_frame(*, frame_type: int, frame_data: bytes) -> bytes:
    """Encode an HTTP/3 frame."""
    frame_length = len(frame_data)
    buf = Buffer(capacity=frame_length + 2 * UINT_VAR_MAX_SIZE)

    buf.push_uint_var(frame_type)
    buf.push_uint_var(frame_length)
    buf.push_bytes(frame_data)

    return buf.data


def encode_settings(*, settings: dict[int, int]) -> bytes:
    """Encode an HTTP/3 SETTINGS frame."""
    buf = Buffer(capacity=1024)
    for setting, value in settings.items():
        buf.push_uint_var(setting)
        buf.push_uint_var(value)
    return buf.data


def parse_settings(*, data: bytes) -> dict[int, int]:
    """Parse an HTTP/3 SETTINGS frame."""
    buf = Buffer(data=data)
    settings: dict[int, int] = {}
    try:
        while not buf.eof():
            setting = buf.pull_uint_var()
            value = buf.pull_uint_var()
            if setting in RESERVED_SETTINGS:
                raise ProtocolError(
                    message=f"Setting identifier 0x{setting:x} is reserved",
                    error_code=ErrorCodes.H3_SETTINGS_ERROR,
                )
            if setting in settings:
                raise ProtocolError(
                    message=f"Setting identifier 0x{setting:x} is included twice",
                    error_code=ErrorCodes.H3_SETTINGS_ERROR,
                )
            settings[setting] = value
    except BufferReadError as exc:
        raise ProtocolError(
            message="Malformed SETTINGS frame payload",
            error_code=ErrorCodes.H3_FRAME_ERROR,
        ) from exc
    return dict(settings)


def stream_is_request_response(*, stream_id: int) -> bool:
    """Check if a stream ID corresponds to a client-initiated bidirectional stream."""
    return stream_id % 4 == 0


def validate_header_name(*, key: bytes) -> None:
    """Validate an HTTP header name."""
    for i, c in enumerate(key):
        if c <= 0x20 or (c >= 0x41 and c <= 0x5A) or c >= 0x7F:
            raise ProtocolError(
                message=f"Header {key!r} contains invalid characters",
                error_code=ErrorCodes.H3_MESSAGE_ERROR,
            )
        if c == COLON and i != 0:
            raise ProtocolError(
                message=f"Header {key!r} contains a non-initial colon",
                error_code=ErrorCodes.H3_MESSAGE_ERROR,
            )


def validate_header_value(*, key: bytes, value: bytes) -> None:
    """Validate an HTTP header value."""
    for c in value:
        if c == NUL or c == LF or c == CR:
            raise ProtocolError(
                message=f"Header {key!r} value has forbidden characters",
                error_code=ErrorCodes.H3_MESSAGE_ERROR,
            )
    if len(value) > 0:
        if value[0] in WHITESPACE:
            raise ProtocolError(
                message=f"Header {key!r} value starts with whitespace",
                error_code=ErrorCodes.H3_MESSAGE_ERROR,
            )
        if len(value) > 1 and value[-1] in WHITESPACE:
            raise ProtocolError(
                message=f"Header {key!r} value ends with whitespace",
                error_code=ErrorCodes.H3_MESSAGE_ERROR,
            )


def validate_headers(
    *,
    headers: _RawHeaders,
    allowed_pseudo_headers: frozenset[bytes],
    required_pseudo_headers: frozenset[bytes],
) -> None:
    """Validate a list of raw HTTP headers."""
    after_pseudo_headers = False
    authority: bytes | None = None
    path: bytes | None = None
    scheme: bytes | None = None
    seen_pseudo_headers: set[bytes] = set()

    for key, value in headers:
        validate_header_name(key=key)
        validate_header_value(key=key, value=value)

        if key.startswith(b":"):
            if after_pseudo_headers:
                raise ProtocolError(
                    message=f"Pseudo-header {key!r} is not allowed after regular headers",
                    error_code=ErrorCodes.H3_MESSAGE_ERROR,
                )
            if key not in allowed_pseudo_headers:
                raise ProtocolError(
                    message=f"Pseudo-header {key!r} is not valid",
                    error_code=ErrorCodes.H3_MESSAGE_ERROR,
                )
            if key in seen_pseudo_headers:
                raise ProtocolError(
                    message=f"Pseudo-header {key!r} is included twice",
                    error_code=ErrorCodes.H3_MESSAGE_ERROR,
                )
            seen_pseudo_headers.add(key)
            if key == b":authority":
                authority = value
            elif key == b":path":
                path = value
            elif key == b":scheme":
                scheme = value
        else:
            after_pseudo_headers = True

    missing = required_pseudo_headers.difference(seen_pseudo_headers)
    if missing:
        raise ProtocolError(
            message=f"Pseudo-headers {sorted(missing)} are missing",
            error_code=ErrorCodes.H3_MESSAGE_ERROR,
        )

    if scheme in (b"http", b"https"):
        if not authority:
            raise ProtocolError(
                message="Pseudo-header b':authority' cannot be empty",
                error_code=ErrorCodes.H3_MESSAGE_ERROR,
            )
        if not path:
            raise ProtocolError(
                message="Pseudo-header b':path' cannot be empty",
                error_code=ErrorCodes.H3_MESSAGE_ERROR,
            )


def validate_request_headers(*, headers: _RawHeaders) -> None:
    """Validate HTTP request headers."""
    validate_headers(
        headers=headers,
        allowed_pseudo_headers=frozenset((b":method", b":scheme", b":authority", b":path", b":protocol")),
        required_pseudo_headers=frozenset((b":method", b":authority")),
    )


def validate_response_headers(*, headers: _RawHeaders) -> None:
    """Validate HTTP response headers."""
    validate_headers(
        headers=headers,
        allowed_pseudo_headers=frozenset((b":status",)),
        required_pseudo_headers=frozenset((b":status",)),
    )
