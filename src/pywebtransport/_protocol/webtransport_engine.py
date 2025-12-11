"""Internal protocol engine for driving the WebTransport state machine."""

from __future__ import annotations

import asyncio
import weakref
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from aioquic.buffer import encode_uint_var

from pywebtransport import constants
from pywebtransport._protocol.connection_processor import ConnectionProcessor
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
from pywebtransport._protocol.h3_engine import WebTransportH3Engine
from pywebtransport._protocol.session_processor import SessionProcessor
from pywebtransport._protocol.state import ProtocolState
from pywebtransport._protocol.stream_processor import StreamProcessor
from pywebtransport.constants import ErrorCodes
from pywebtransport.exceptions import ConnectionError, ProtocolError
from pywebtransport.types import Buffer, ConnectionId, ConnectionState, EventType, Headers, SessionId
from pywebtransport.utils import get_logger, get_timestamp, merge_headers

if TYPE_CHECKING:
    from pywebtransport._adapter.client import WebTransportClientProtocol
    from pywebtransport._adapter.server import WebTransportServerProtocol
    from pywebtransport.config import ClientConfig, ServerConfig

    type AdapterProtocol = WebTransportServerProtocol | WebTransportClientProtocol
    type NotifyCallback = Callable[[Effect], None]


__all__: list[str] = []

logger = get_logger(name=__name__)


class WebTransportEngine:
    """Orchestrates the unified protocol state machine."""

    def __init__(
        self,
        *,
        connection_id: ConnectionId,
        config: ClientConfig | ServerConfig,
        is_client: bool,
        protocol_handler: AdapterProtocol,
        owner_notify_callback: NotifyCallback,
    ) -> None:
        """Initialize the WebTransport engine."""
        self._connection_id = connection_id
        self._is_client = is_client
        self._protocol_handler = weakref.ref(protocol_handler)
        self._owner_notify_callback = owner_notify_callback
        self._event_queue: asyncio.Queue[ProtocolEvent] | None = None
        self._driver_task: asyncio.Task[None] | None = None
        self._early_event_cleanup_task: asyncio.Task[None] | None = None
        self._resource_gc_timer_task: asyncio.Task[None] | None = None

        self._internal_error: tuple[int, str] | None = None

        self._pending_event_ttl = config.pending_event_ttl
        self._resource_cleanup_interval = config.resource_cleanup_interval
        self._next_early_event_cleanup_at: float = 0.0
        self._config = config

        self._state = ProtocolState(
            is_client=is_client, connection_state=ConnectionState.IDLE, max_datagram_size=config.max_datagram_size
        )

        self._connection_processor = ConnectionProcessor(
            is_client=is_client, config=config, connection_id=connection_id
        )
        self._session_processor = SessionProcessor(is_client=is_client, config=config)
        self._stream_processor = StreamProcessor(is_client=is_client, config=config)
        self._h3_engine = WebTransportH3Engine(is_client=is_client, config=config)

        self._pending_user_actions: deque[UserEvent[Any]] = deque()

    async def put_event(self, *, event: ProtocolEvent) -> None:
        """Place a new event into the engine's processing queue."""
        if self._driver_task is not None and not self._driver_task.done() and self._event_queue is not None:
            try:
                self._event_queue.put_nowait(event)
            except asyncio.QueueFull:
                if isinstance(event, UserEvent):
                    if not event.future.done():
                        try:
                            event.future.set_exception(
                                ConnectionError("Event queue full", error_code=ErrorCodes.APP_RESOURCE_EXHAUSTED)
                            )
                        except asyncio.InvalidStateError:
                            pass
                elif isinstance(event, TransportDatagramFrameReceived):
                    logger.warning(
                        "Event queue full (%d), dropping datagram event: %s", self._event_queue.maxsize, event
                    )
                else:
                    error_msg = f"Event queue full ({self._event_queue.maxsize}), critical event lost: {event}"
                    logger.critical("%s. Triggering emergency shutdown.", error_msg)

                    self._internal_error = (ErrorCodes.INTERNAL_ERROR, error_msg)

                    if self._driver_task and not self._driver_task.done():
                        self._driver_task.cancel()
        else:
            if isinstance(event, UserEvent) and not event.future.done():
                error = ConnectionError("Engine is not running.")
                try:
                    event.future.set_exception(error)
                except asyncio.InvalidStateError:
                    pass
            logger.warning("Engine not running, discarding event: %s", type(event).__name__)

    def start_driver_loop(self) -> None:
        """Start the main event processing loop as a background task."""
        if self._state.connection_state == ConnectionState.IDLE:
            self._state.connection_state = ConnectionState.CONNECTING
        if self._event_queue is None:
            self._event_queue = asyncio.Queue(maxsize=self._config.max_event_queue_size)

        if self._driver_task is None:
            self._driver_task = asyncio.create_task(coro=self._driver_loop())
            logger.debug("WebTransportEngine driver loop started.")

        if self._early_event_cleanup_task is None and self._pending_event_ttl > 0:
            self._early_event_cleanup_task = asyncio.create_task(coro=self._early_event_cleanup_loop())

        if self._resource_gc_timer_task is None and self._resource_cleanup_interval > 0:
            self._resource_gc_timer_task = asyncio.create_task(coro=self._resource_gc_timer_loop())

    async def stop_driver_loop(self) -> None:
        """Stop the main event processing loop."""
        if self._early_event_cleanup_task and not self._early_event_cleanup_task.done():
            self._early_event_cleanup_task.cancel()
            try:
                await self._early_event_cleanup_task
            except asyncio.CancelledError:
                pass
        self._early_event_cleanup_task = None

        if self._resource_gc_timer_task and not self._resource_gc_timer_task.done():
            self._resource_gc_timer_task.cancel()
            try:
                await self._resource_gc_timer_task
            except asyncio.CancelledError:
                pass
        self._resource_gc_timer_task = None

        if self._driver_task and not self._driver_task.done():
            self._driver_task.cancel()
            try:
                await asyncio.wait_for(self._driver_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            logger.debug("WebTransportEngine driver loop stopped.")
        self._driver_task = None

        if self._event_queue:
            while not self._event_queue.empty():
                try:
                    event = self._event_queue.get_nowait()
                    if isinstance(event, UserEvent) and not event.future.done():
                        error = ConnectionError("Engine stopped")
                        try:
                            event.future.set_exception(error)
                        except asyncio.InvalidStateError:
                            pass
                    self._event_queue.task_done()
                except asyncio.QueueEmpty:
                    break

    def _check_client_connection_ready(self) -> tuple[list[Effect], bool]:
        """Check if the client connection is fully ready (QUIC + H3)."""
        if (
            self._state.connection_state == ConnectionState.CONNECTING
            and self._state.handshake_complete
            and self._state.peer_settings_received
        ):
            logger.debug("Client connection fully ready (QUIC + H3 SETTINGS).")
            self._state.connection_state = ConnectionState.CONNECTED
            self._state.connected_at = get_timestamp()
            effects: list[Effect] = [
                EmitConnectionEvent(
                    event_type=EventType.CONNECTION_ESTABLISHED, data={"connection_id": self._connection_id}
                )
            ]
            return effects, True

        return [], False

    async def _driver_loop(self) -> None:
        """The main event processing loop."""
        final_reason: str | None = "Driver loop ended unexpectedly"
        final_error_code: int = ErrorCodes.INTERNAL_ERROR
        last_effects: list[Effect] = []
        try:
            if self._event_queue is None:
                logger.critical("Driver loop started without an event queue.")
                return

            while self._state.connection_state != ConnectionState.CLOSED:
                event = await self._event_queue.get()
                current_effects: list[Effect] = []
                try:
                    current_effects = self._handle_event(event=event)
                    last_effects = current_effects

                except ProtocolError as pe:
                    logger.debug("Protocol error occurred: %s (Code: %#x)", pe.message, pe.error_code)
                    final_reason = f"Protocol error: {pe.message}"
                    final_error_code = pe.error_code
                    if self._state.connection_state != ConnectionState.CLOSING:
                        self._state.connection_state = ConnectionState.CLOSING
                        current_effects.append(CloseQuicConnection(error_code=final_error_code, reason=final_reason))

                except Exception as e:
                    logger.error("Unexpected internal error in event loop: %s", e, exc_info=True)
                    final_reason = f"Unexpected internal error: {e}"
                    final_error_code = ErrorCodes.INTERNAL_ERROR
                    if self._state.connection_state != ConnectionState.CLOSING:
                        self._state.connection_state = ConnectionState.CLOSING
                        current_effects.append(CloseQuicConnection(error_code=final_error_code, reason=final_reason))

                await self._execute_effects(effects=current_effects)

                self._event_queue.task_done()

            if self._state.connection_state == ConnectionState.CLOSED:
                for eff in last_effects:
                    if isinstance(eff, CloseQuicConnection):
                        final_reason = eff.reason
                        final_error_code = eff.error_code
                        break
                else:
                    if final_reason == "Driver loop ended unexpectedly":
                        final_reason = "Connection closed"
                        final_error_code = ErrorCodes.NO_ERROR

        except asyncio.CancelledError:
            logger.debug("Engine driver loop cancelled.")
            if self._internal_error:
                final_error_code, final_reason = self._internal_error
            else:
                final_reason = "Driver loop cancelled"
                final_error_code = ErrorCodes.NO_ERROR

        except Exception as e:
            logger.critical("Fatal error in engine driver loop: %s", e, exc_info=True)
            final_reason = "Fatal engine error"
            final_error_code = ErrorCodes.INTERNAL_ERROR
            if self._state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                close_effects_on_error_fatal: list[Effect] = [
                    CloseQuicConnection(error_code=final_error_code, reason=final_reason)
                ]
                try:
                    await self._execute_effects(effects=close_effects_on_error_fatal)
                except Exception:
                    logger.error("Ignoring error during final close attempt in fatal handler.")
        finally:
            if self._early_event_cleanup_task and not self._early_event_cleanup_task.done():
                self._early_event_cleanup_task.cancel()
                try:
                    await self._early_event_cleanup_task
                except asyncio.CancelledError:
                    pass
            self._early_event_cleanup_task = None

            if self._resource_gc_timer_task and not self._resource_gc_timer_task.done():
                self._resource_gc_timer_task.cancel()
                try:
                    await self._resource_gc_timer_task
                except asyncio.CancelledError:
                    pass
            self._resource_gc_timer_task = None

            if self._state.connection_state != ConnectionState.CLOSED:
                self._state.connection_state = ConnectionState.CLOSED
                self._state.closed_at = get_timestamp()
                close_event_effect = EmitConnectionEvent(
                    event_type=EventType.CONNECTION_CLOSED,
                    data={"connection_id": self._connection_id, "reason": final_reason, "error_code": final_error_code},
                )
                try:
                    self._owner_notify_callback(close_event_effect)
                except Exception as cb_err:
                    logger.warning("Error in final owner notification callback: %s", cb_err)

    async def _early_event_cleanup_loop(self) -> None:
        """Periodically trigger cleanup for early (buffered) events."""
        if self._pending_event_ttl <= 0:
            logger.debug("Early event cleanup timer disabled (pending_event_ttl=0).")
            return

        loop = asyncio.get_running_loop()
        self._next_early_event_cleanup_at = loop.time() + self._pending_event_ttl

        try:
            while self._state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                now = loop.time()
                wait_time = self._next_early_event_cleanup_at - now

                if wait_time <= 0:
                    if self._state.early_event_count > 0:
                        await self.put_event(event=InternalCleanupEarlyEvents())
                    self._next_early_event_cleanup_at = now + self._pending_event_ttl
                    await asyncio.sleep(delay=self._pending_event_ttl)
                else:
                    await asyncio.sleep(delay=wait_time)

        except asyncio.CancelledError:
            logger.debug("Engine early event cleanup task cancelled.")
        except Exception as e:
            logger.error("Fatal error in engine early event cleanup loop: %s", e, exc_info=True)
            if self._state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                fut = loop.create_future()
                cleanup_error = ConnectionError(
                    message=f"Early event cleanup loop failed: {e}", error_code=ErrorCodes.INTERNAL_ERROR
                )
                await self.put_event(
                    event=ConnectionClose(error_code=cleanup_error.error_code, reason=cleanup_error.message, future=fut)
                )

    async def _execute_effects(self, *, effects: list[Effect]) -> None:
        """Run the asynchronous side effects returned by the state machine."""
        handler = self._protocol_handler()
        if not handler:
            logger.warning("Protocol handler lost during effect execution, discarding effects.")
            error = ConnectionError("Protocol handler lost")
            for effect in effects:
                match effect:
                    case FailUserFuture(future=fut, exception=err):
                        if not fut.done():
                            try:
                                fut.set_exception(err)
                            except asyncio.InvalidStateError:
                                pass
                    case CompleteUserFuture(future=fut):
                        if not fut.done():
                            try:
                                fut.set_exception(error)
                            except asyncio.InvalidStateError:
                                pass
                    case CreateH3Session(create_future=fut) | CreateQuicStream(create_future=fut):
                        if not fut.done():
                            try:
                                fut.set_exception(error)
                            except asyncio.InvalidStateError:
                                pass
                    case _:
                        pass
            return

        for i, effect in enumerate(effects):
            try:
                match effect:
                    case CleanupH3Stream(stream_id=sid):
                        if hasattr(self, "_h3_engine"):
                            self._h3_engine.cleanup_stream(stream_id=sid)

                    case CloseQuicConnection(error_code=ec, reason=r):
                        previous_state = self._state.connection_state
                        if previous_state != ConnectionState.CLOSED:
                            handler.close_connection(error_code=ec, reason_phrase=r)
                            current_state_after_close = self._state.connection_state
                            if current_state_after_close == ConnectionState.CLOSED:
                                self._state.closed_at = get_timestamp()
                                close_event_effect = EmitConnectionEvent(
                                    event_type=EventType.CONNECTION_CLOSED,
                                    data={"connection_id": self._connection_id, "reason": r, "error_code": ec},
                                )
                                self._owner_notify_callback(close_event_effect)
                            elif (
                                current_state_after_close == ConnectionState.CLOSING
                                and previous_state != ConnectionState.CLOSING
                            ):
                                self._state.closed_at = get_timestamp()

                    case RescheduleQuicTimer():
                        handler.schedule_timer_now()

                    case ResetQuicStream(stream_id=sid, error_code=ec):
                        handler.reset_stream(stream_id=sid, error_code=ec)

                    case SendQuicData(stream_id=sid, data=d, end_stream=es):
                        handler.send_stream_data(stream_id=sid, data=cast(bytes, d), end_stream=es)

                    case SendQuicDatagram(data=d):
                        handler.send_datagram_frame(data=cast(bytes, d))

                    case StopQuicStream(stream_id=sid, error_code=ec):
                        handler.stop_stream(stream_id=sid, error_code=ec)

                    case TriggerQuicTimer():
                        handler.handle_timer_now()

                    case CompleteUserFuture(future=fut, value=v):
                        if fut.cancelled():
                            if isinstance(v, (bytes, memoryview)) and v:
                                stream_id = getattr(fut, "stream_id", None)
                                if stream_id is not None:
                                    logger.warning(
                                        "Read future cancelled, returning %d bytes to stream %d", len(v), stream_id
                                    )
                                    await self.put_event(
                                        event=InternalReturnStreamData(stream_id=stream_id, data=cast(Buffer, v))
                                    )
                                else:
                                    logger.warning("Read future cancelled with data, but stream_id missing. Data lost.")
                        elif not fut.done():
                            fut.set_result(v)

                    case FailUserFuture(future=fut, exception=err):
                        if not fut.done():
                            fut.set_exception(err)

                    case EmitConnectionEvent() | EmitSessionEvent() | EmitStreamEvent() as emit_effect:
                        self._owner_notify_callback(emit_effect)

                    case LogH3Frame(category=c, event=e, data=d):
                        handler.log_event(category=c, event=e, data=d)

                    case CreateH3Session(session_id=sid, path=p, headers=h, create_future=fut):
                        try:
                            control_stream_id = handler.get_next_available_stream_id(is_unidirectional=False)
                        except Exception as e:
                            logger.error("Failed to get next available stream ID for session %s: %s", sid, e)
                            await self.put_event(event=InternalFailH3Session(session_id=sid, exception=e, future=fut))
                            continue

                        server_name = handler.get_server_name()
                        if not server_name:
                            error = ConnectionError("Cannot create session: missing server name (SNI)")
                            logger.error(error)
                            await self.put_event(
                                event=InternalFailH3Session(session_id=sid, exception=error, future=fut)
                            )
                            continue

                        initial_headers: Headers = {
                            ":method": "CONNECT",
                            ":scheme": "https",
                            ":authority": server_name,
                            ":path": p,
                            ":protocol": "webtransport",
                        }

                        final_headers = merge_headers(base=initial_headers, update=h)

                        h3_effects = self._h3_engine.encode_headers(
                            stream_id=control_stream_id, headers=final_headers, end_stream=False
                        )
                        await self._execute_effects(effects=h3_effects)
                        await self.put_event(
                            event=InternalBindH3Session(session_id=sid, control_stream_id=control_stream_id, future=fut)
                        )

                    case CreateQuicStream(session_id=sid, is_unidirectional=is_uni, create_future=fut):
                        try:
                            actual_stream_id = handler.get_next_available_stream_id(is_unidirectional=is_uni)
                            session_data = self._state.sessions.get(sid)
                            control_id = session_data.control_stream_id if session_data else -1

                            (h3_effects) = self._h3_engine.encode_webtransport_stream_creation(
                                stream_id=actual_stream_id,
                                control_stream_id=control_id,
                                is_unidirectional=is_uni,
                            )
                            await self._execute_effects(effects=h3_effects)
                            await self.put_event(
                                event=InternalBindQuicStream(
                                    stream_id=actual_stream_id,
                                    session_id=sid,
                                    is_unidirectional=is_uni,
                                    future=fut,
                                )
                            )
                        except Exception as e:
                            logger.error(
                                "Failed during WebTransport stream creation encoding for session %s: %s", sid, e
                            )
                            await self.put_event(
                                event=InternalFailQuicStream(
                                    session_id=sid, is_unidirectional=is_uni, exception=e, future=fut
                                )
                            )
                            continue

                    case SendH3Capsule(stream_id=sid, capsule_type=ct, capsule_data=cd):
                        encoded_bytes = self._h3_engine.encode_capsule(
                            stream_id=sid, capsule_type=ct, capsule_data=cast(bytes, cd)
                        )
                        await self._execute_effects(
                            effects=[SendQuicData(stream_id=sid, data=encoded_bytes, end_stream=False)]
                        )

                    case SendH3Datagram(stream_id=sid, data=d):
                        encoded_data = self._h3_engine.encode_datagram(stream_id=sid, data=d)
                        await self._execute_effects(effects=[SendQuicDatagram(data=encoded_data)])

                    case SendH3Goaway():
                        h3_control_stream_id = self._h3_engine._local_control_stream_id
                        if h3_control_stream_id is None:
                            logger.critical("Cannot send GOAWAY: H3 local control stream ID is None.")
                        else:
                            goaway_bytes = self._h3_engine.encode_goaway_frame()
                            await self._execute_effects(
                                effects=[
                                    SendQuicData(stream_id=h3_control_stream_id, data=goaway_bytes, end_stream=False)
                                ]
                            )

                    case SendH3Headers(stream_id=sid, status=st, end_stream=es):
                        h3_effects = self._h3_engine.encode_headers(
                            stream_id=sid, headers={":status": str(st)}, end_stream=es
                        )
                        await self._execute_effects(effects=h3_effects)

                    case _:
                        logger.warning("Unhandled effect type in execute_effects: %s", type(effect))

            except Exception as e:
                logger.error("Error executing effect %s: %s", type(effect).__name__, e, exc_info=True)

                self._fail_remaining_futures(remaining_effects=effects[i + 1 :], exception=e)

                if self._state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                    close_effects_on_error: list[Effect] = [
                        CloseQuicConnection(error_code=ErrorCodes.INTERNAL_ERROR, reason="Effect execution error")
                    ]
                    try:
                        await self._execute_effects(effects=close_effects_on_error)
                    except Exception as close_e:
                        logger.critical("Failed even to close connection after effect error: %s", close_e)
                        if self._state.connection_state != ConnectionState.CLOSED:
                            self._state.connection_state = ConnectionState.CLOSED
                            self._state.closed_at = get_timestamp()
                            final_close_event = EmitConnectionEvent(
                                event_type=EventType.CONNECTION_CLOSED,
                                data={
                                    "connection_id": self._connection_id,
                                    "reason": "Effect execution error, close failed",
                                    "error_code": ErrorCodes.INTERNAL_ERROR,
                                },
                            )
                            try:
                                self._owner_notify_callback(final_close_event)
                            except Exception:
                                pass

                break

    def _fail_remaining_futures(self, *, remaining_effects: list[Effect], exception: Exception) -> None:
        """Fail pending futures in unexecuted effects to prevent deadlocks."""
        for effect in remaining_effects:
            match effect:
                case (
                    CompleteUserFuture(future=fut)
                    | FailUserFuture(future=fut)
                    | InternalBindH3Session(future=fut)
                    | InternalFailH3Session(future=fut)
                    | InternalBindQuicStream(future=fut)
                    | InternalFailQuicStream(future=fut)
                ):
                    if not fut.done():
                        try:
                            fut.set_exception(exception)
                        except asyncio.InvalidStateError:
                            pass
                case CreateH3Session(create_future=fut) | CreateQuicStream(create_future=fut):
                    if not fut.done():
                        try:
                            fut.set_exception(exception)
                        except asyncio.InvalidStateError:
                            pass
                case _:
                    pass

    def _handle_event(self, *, event: ProtocolEvent) -> list[Effect]:
        """Process a single event and return resulting effects."""
        all_effects: list[Effect] = []
        events_to_process: deque[ProtocolEvent] = deque([event])

        while events_to_process:
            current_event = events_to_process.popleft()
            new_effects: list[Effect] = []
            re_queue_pending_actions = False

            match current_event:
                case InternalBindH3Session() as ibhs_ev:
                    new_effects.extend(
                        self._connection_processor.handle_internal_bind_h3_session(event=ibhs_ev, state=self._state)
                    )

                case InternalBindQuicStream() as ibqs_ev:
                    new_effects.extend(
                        self._stream_processor.handle_internal_bind_quic_stream(event=ibqs_ev, state=self._state)
                    )

                case InternalCleanupEarlyEvents():
                    if self._state.early_event_count == 0:
                        continue

                    now = get_timestamp()
                    for control_stream_id, events in list(self._state.early_event_buffer.items()):
                        valid_events = []
                        expired_events = []

                        for entry in events:
                            ts, _ = entry
                            if (now - ts) <= self._pending_event_ttl:
                                valid_events.append(entry)
                            else:
                                expired_events.append(entry)

                        if expired_events:
                            self._state.early_event_count -= len(expired_events)
                            logger.warning(
                                "Discarding %d expired early events for unknown session (control stream %d)",
                                len(expired_events),
                                control_stream_id,
                            )
                            for _ts, ev in expired_events:
                                if isinstance(ev, WebTransportStreamDataReceived):
                                    new_effects.append(
                                        ResetQuicStream(
                                            stream_id=ev.stream_id, error_code=ErrorCodes.WT_BUFFERED_STREAM_REJECTED
                                        )
                                    )

                        if valid_events:
                            self._state.early_event_buffer[control_stream_id] = valid_events
                        else:
                            del self._state.early_event_buffer[control_stream_id]

                case InternalCleanupResources() as icr_ev:
                    new_effects.extend(
                        self._connection_processor.handle_cleanup_resources(event=icr_ev, state=self._state)
                    )

                case InternalFailH3Session() as ifhs_ev:
                    new_effects.extend(
                        self._connection_processor.handle_internal_fail_h3_session(event=ifhs_ev, state=self._state)
                    )

                case InternalFailQuicStream() as ifqs_ev:
                    new_effects.extend(
                        self._stream_processor.handle_internal_fail_quic_stream(event=ifqs_ev, state=self._state)
                    )

                case InternalReturnStreamData() as irsd_ev:
                    new_effects.extend(
                        self._stream_processor.handle_return_stream_data(event=irsd_ev, state=self._state)
                    )

                case TransportConnectionTerminated() as tct_ev:
                    new_effects.extend(
                        self._connection_processor.handle_connection_terminated(event=tct_ev, state=self._state)
                    )

                case TransportDatagramFrameReceived() | TransportStreamDataReceived() as tev:
                    was_settings_received = self._h3_engine._settings_received

                    h3_events, h3_effects = self._h3_engine.handle_transport_event(event=tev, state=self._state)
                    new_effects.extend(h3_effects)
                    events_to_process.extendleft(reversed(h3_events))

                    if self._is_client and not was_settings_received and self._h3_engine._settings_received:
                        logger.debug("Client received peer H3 SETTINGS.")
                        self._state.peer_settings_received = True
                        (readiness_effects, is_ready) = self._check_client_connection_ready()
                        new_effects.extend(readiness_effects)
                        if is_ready:
                            re_queue_pending_actions = True

                case TransportHandshakeCompleted():
                    if self._state.connection_state == ConnectionState.CONNECTING:
                        logger.debug("TransportHandshakeCompleted received. Initializing H3.")
                        handler = self._protocol_handler()
                        if not handler:
                            logger.error("Protocol handler lost during H3 initialization.")
                            new_effects.append(
                                CloseQuicConnection(
                                    error_code=ErrorCodes.INTERNAL_ERROR, reason="Protocol handler lost"
                                )
                            )
                            break

                        try:
                            control_stream_id = handler.get_next_available_stream_id(is_unidirectional=True)
                            encoder_stream_id = handler.get_next_available_stream_id(is_unidirectional=True)
                            decoder_stream_id = handler.get_next_available_stream_id(is_unidirectional=True)

                            self._h3_engine.set_local_stream_ids(
                                control_stream_id=control_stream_id,
                                encoder_stream_id=encoder_stream_id,
                                decoder_stream_id=decoder_stream_id,
                            )

                            settings_bytes = self._h3_engine.initialize_connection()

                            new_effects = [
                                SendQuicData(
                                    stream_id=control_stream_id,
                                    data=encode_uint_var(constants.H3_STREAM_TYPE_CONTROL) + settings_bytes,
                                    end_stream=False,
                                ),
                                SendQuicData(
                                    stream_id=encoder_stream_id,
                                    data=encode_uint_var(constants.H3_STREAM_TYPE_QPACK_ENCODER),
                                    end_stream=False,
                                ),
                                SendQuicData(
                                    stream_id=decoder_stream_id,
                                    data=encode_uint_var(constants.H3_STREAM_TYPE_QPACK_DECODER),
                                    end_stream=False,
                                ),
                                LogH3Frame(
                                    category="http",
                                    event="stream_type_set",
                                    data={"new": "control", "stream_id": control_stream_id},
                                ),
                                LogH3Frame(
                                    category="http",
                                    event="stream_type_set",
                                    data={"new": "qpack_encoder", "stream_id": encoder_stream_id},
                                ),
                                LogH3Frame(
                                    category="http",
                                    event="stream_type_set",
                                    data={"new": "qpack_decoder", "stream_id": decoder_stream_id},
                                ),
                            ]
                            self._state.handshake_complete = True

                            if self._is_client:
                                (readiness_effects, is_ready) = self._check_client_connection_ready()
                                new_effects.extend(readiness_effects)
                                if is_ready:
                                    re_queue_pending_actions = True
                            else:
                                self._state.connection_state = ConnectionState.CONNECTED
                                self._state.connected_at = get_timestamp()
                                new_effects.append(
                                    EmitConnectionEvent(
                                        event_type=EventType.CONNECTION_ESTABLISHED,
                                        data={"connection_id": self._connection_id},
                                    )
                                )
                                logger.debug("Server connection established and H3 initialized.")

                        except Exception as h3_init_error:
                            logger.error("H3 initialization failed after handshake: %s", h3_init_error, exc_info=True)
                            new_effects.append(
                                CloseQuicConnection(
                                    error_code=ErrorCodes.INTERNAL_ERROR,
                                    reason=f"H3 initialization failed: {h3_init_error}",
                                )
                            )
                    else:
                        logger.warning(
                            "Received TransportHandshakeCompleted in unexpected state: %s", self._state.connection_state
                        )

                case TransportQuicParametersReceived() as tqpr_ev:
                    new_effects.extend(
                        self._connection_processor.handle_transport_parameters_received(
                            event=tqpr_ev, state=self._state
                        )
                    )

                case TransportQuicTimerFired():
                    new_effects.extend([TriggerQuicTimer(), RescheduleQuicTimer()])

                case TransportStreamReset() as tsr_ev:
                    new_effects.extend(
                        self._stream_processor.handle_transport_stream_reset(event=tsr_ev, state=self._state)
                    )

                case CapsuleReceived() as cr_ev:
                    new_effects.extend(self._session_processor.handle_capsule_received(event=cr_ev, state=self._state))

                case ConnectStreamClosed() as csc_ev:
                    new_effects.extend(
                        self._session_processor.handle_connect_stream_closed(event=csc_ev, state=self._state)
                    )

                case DatagramReceived() as dr_ev:
                    new_effects.extend(self._session_processor.handle_datagram_received(event=dr_ev, state=self._state))

                case GoawayReceived() as gr_ev:
                    new_effects.extend(
                        self._connection_processor.handle_goaway_received(event=gr_ev, state=self._state)
                    )

                case HeadersReceived() as hr_ev:
                    new_effects.extend(
                        self._connection_processor.handle_headers_received(event=hr_ev, state=self._state)
                    )

                    session_id_to_check: SessionId | None = None
                    for effect in new_effects:
                        if isinstance(effect, EmitSessionEvent) and effect.event_type in (
                            EventType.SESSION_REQUEST,
                            EventType.SESSION_READY,
                        ):
                            session_id_to_check = effect.session_id
                            break

                    if session_id_to_check:
                        session_data = self._state.sessions.get(session_id_to_check)
                        if session_data:
                            control_stream_id = session_data.control_stream_id
                            buffered_events = self._state.early_event_buffer.pop(control_stream_id, None)
                            if buffered_events:
                                logger.debug(
                                    "Session %s (ControlStream %d) is now active, re-queueing %d buffered events.",
                                    session_id_to_check,
                                    control_stream_id,
                                    len(buffered_events),
                                )
                                self._state.early_event_count -= len(buffered_events)
                                events_to_process.extendleft(reversed([evt for _ts, evt in buffered_events]))

                case SettingsReceived() as sr_ev:
                    logger.debug("Processing H3 SETTINGS frame.")
                    self._state.peer_initial_max_data = sr_ev.settings.get(constants.SETTINGS_WT_INITIAL_MAX_DATA, 0)
                    self._state.peer_initial_max_streams_bidi = sr_ev.settings.get(
                        constants.SETTINGS_WT_INITIAL_MAX_STREAMS_BIDI, 0
                    )
                    self._state.peer_initial_max_streams_uni = sr_ev.settings.get(
                        constants.SETTINGS_WT_INITIAL_MAX_STREAMS_UNI, 0
                    )

                case WebTransportStreamDataReceived() as wtsdr_ev:
                    new_effects.extend(
                        self._stream_processor.handle_webtransport_stream_data(event=wtsdr_ev, state=self._state)
                    )

                case UserAcceptSession() as uas_ev:
                    new_effects.extend(self._session_processor.handle_accept_session(event=uas_ev, state=self._state))

                case UserCloseSession() as ucs_ev:
                    new_effects.extend(self._session_processor.handle_close_session(event=ucs_ev, state=self._state))

                case UserConnectionGracefulClose() as ugcc_ev:
                    new_effects.extend(
                        self._connection_processor.handle_graceful_close(event=ugcc_ev, state=self._state)
                    )

                case UserCreateSession() as ucs_ev:
                    if self._is_client and self._state.connection_state != ConnectionState.CONNECTED:
                        logger.debug("Client not fully connected, buffering UserCreateSession.")
                        self._pending_user_actions.append(ucs_ev)
                    else:
                        new_effects.extend(
                            self._connection_processor.handle_create_session(event=ucs_ev, state=self._state)
                        )

                case UserCreateStream() as ucs_ev:
                    if self._is_client and self._state.connection_state != ConnectionState.CONNECTED:
                        logger.debug("Client not fully connected, buffering UserCreateStream.")
                        self._pending_user_actions.append(ucs_ev)
                    else:
                        new_effects.extend(
                            self._session_processor.handle_create_stream(event=ucs_ev, state=self._state)
                        )

                case UserGetConnectionDiagnostics() as ugcd_ev:
                    new_effects.extend(
                        self._connection_processor.handle_get_connection_diagnostics(event=ugcd_ev, state=self._state)
                    )

                case UserGetSessionDiagnostics() as ugsd_ev:
                    new_effects.extend(
                        self._session_processor.handle_get_session_diagnostics(event=ugsd_ev, state=self._state)
                    )

                case UserGetStreamDiagnostics() as ugstd_ev:
                    new_effects.extend(
                        self._stream_processor.handle_get_stream_diagnostics(event=ugstd_ev, state=self._state)
                    )

                case UserGrantDataCredit() as ugdc_ev:
                    new_effects.extend(
                        self._session_processor.handle_grant_data_credit(event=ugdc_ev, state=self._state)
                    )

                case UserGrantStreamsCredit() as ugsc_ev:
                    new_effects.extend(
                        self._session_processor.handle_grant_streams_credit(event=ugsc_ev, state=self._state)
                    )

                case UserRejectSession() as urs_ev:
                    new_effects.extend(self._session_processor.handle_reject_session(event=urs_ev, state=self._state))

                case UserResetStream() as urs_ev:
                    new_effects.extend(self._stream_processor.handle_reset_stream(event=urs_ev, state=self._state))

                case UserSendDatagram() as usd_ev:
                    new_effects.extend(self._session_processor.handle_send_datagram(event=usd_ev, state=self._state))

                case UserSendStreamData() as ussd_ev:
                    new_effects.extend(self._stream_processor.handle_send_stream_data(event=ussd_ev, state=self._state))

                case UserStopStream() as uss_ev:
                    new_effects.extend(self._stream_processor.handle_stop_stream(event=uss_ev, state=self._state))

                case UserStreamRead() as usr_ev:
                    new_effects.extend(self._stream_processor.handle_stream_read(event=usr_ev, state=self._state))

                case ConnectionClose() as cc_ev:
                    new_effects.extend(
                        self._connection_processor.handle_connection_close(event=cc_ev, state=self._state)
                    )

                case _:
                    logger.warning("Unhandled event type in engine's handle_event: %s", type(current_event))

            all_effects.extend(new_effects)

            if re_queue_pending_actions:
                if self._pending_user_actions:
                    logger.debug(
                        "Connection is ready, re-queueing %d pending user actions.", len(self._pending_user_actions)
                    )
                    events_to_process.extendleft(reversed(self._pending_user_actions))
                    self._pending_user_actions.clear()

        if not any(isinstance(effect, RescheduleQuicTimer) for effect in all_effects):
            all_effects.append(RescheduleQuicTimer())

        return all_effects

    async def _resource_gc_timer_loop(self) -> None:
        """Periodically trigger garbage collection for closed resources."""
        if self._resource_cleanup_interval <= 0:
            logger.debug("Resource GC timer disabled (interval=0).")
            return

        loop = asyncio.get_running_loop()
        try:
            while self._state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                await asyncio.sleep(delay=self._resource_cleanup_interval)

                if self._state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                    await self.put_event(event=InternalCleanupResources())

        except asyncio.CancelledError:
            logger.debug("Engine resource GC timer task cancelled.")
        except Exception as e:
            logger.error("Fatal error in engine resource GC timer loop: %s", e, exc_info=True)
            if self._state.connection_state not in (ConnectionState.CLOSING, ConnectionState.CLOSED):
                fut = loop.create_future()
                timer_error = ConnectionError(
                    message=f"Resource GC loop failed: {e}", error_code=ErrorCodes.INTERNAL_ERROR
                )
                await self.put_event(
                    event=ConnectionClose(error_code=timer_error.error_code, reason=timer_error.message, future=fut)
                )
