# Known Issues

- **ID**: KI-001
- **Subject**: Race Condition in aioquic Core on Connection Shutdown
- **Status**: Resolved
- **Dependency**: aioquic (< 1.3.0)
- **Date Discovered**: 2025-09-17
- **Date Resolved**: 2025-10-23

### Summary

On the `pywebtransport` server, a benign `AssertionError` may be triggered in the underlying `aioquic` dependency when a client connection is closed cleanly and rapidly. The issue stems from a non-idempotent event handler within `aioquic` (< 1.3.0) that creates a race condition when processing concurrent shutdown signals. This defect does not affect the library's core functionality or data transfer stability but produces `ERROR`-level stack traces in the server logs, which can interfere with operational monitoring.

We have hardened our own codebase where possible and have identified this as a low-level issue fixed in the upstream `aioquic` library.

### Symptoms

The server logs periodically show `asyncio - ERROR` level entries accompanied by the following stack trace:

```
ERROR - Exception in callback _Selector_datagram_transport._read_ready()
...
AssertionError: cannot call reset() more than once
```

### Root Cause Analysis

The root cause of this issue is that `aioquic`'s `_handle_stop_sending_frame` method (< 1.3.0) calls a non-idempotent internal stream reset function. During a rapid client-side connection closure, at least three events can race to reset the same stream:

1.  **Application Layer Cleanup**: `pywebtransport` receives a `CLOSE_SESSION` capsule and, per the protocol specification, calls `reset_stream`.
2.  **Peer Stream Closure**: The client sends a `STOP_SENDING` frame.
3.  **Peer Connection Closure**: The client sends a `CONNECTION_CLOSE` frame, which also triggers `aioquic` to clean up all associated streams.

Because `aioquic`'s `datagram_received` method executes synchronously, if any of the above events cause a stream to be reset, a subsequent `STOP_SENDING` frame handled by `_handle_stop_sending_frame` would trigger the internal assertion failure in versions prior to 1.3.0.

### Impact Assessment

- **On Library Functionality**: **None**. Data transfer, session, and stream lifecycle management remain correct, and connections are ultimately closed successfully.
- **On Operations & Monitoring**: **Significant**. The `ERROR`-level logs are misleading, may trigger false positives in monitoring systems, increase unnecessary investigation costs, and cast doubt on the service's stability.

### Resolution

- **Status**: This issue has been **fixed** in the upstream `aioquic` library, starting from version **1.3.0**, by making the internal stream reset operation idempotent.
- **Action**: Resolved by updating the required `aioquic` dependency to version 1.3.0 or later within `pywebtransport`.
- **Upstream Fix Link**: [aiortc/aioquic#597](https://github.com/aiortc/aioquic/issues/597) (Original issue tracking)
- **Note**: This `AssertionError` should no longer occur when using a version of `pywebtransport` that depends on `aioquic` 1.3.0 or later. If observed, it might indicate a different issue.

---

- **ID**: KI-002
- **Subject**: Protocol Compliance Gap due to Lack of `RESET_STREAM_AT` Support
- **Status**: Confirmed
- **Dependency**: aioquic (all known versions)
- **Date Discovered**: 2025-09-12

### Summary

The current version of `pywebtransport` does not support the `RESET_STREAM_AT` frame as required by the WebTransport standard. This is entirely due to the lack of support for the `draft-ietf-quic-reliable-stream-reset` extension in the underlying `aioquic` library. Standard `RESET_STREAM` functionality is unaffected, but this may impact applications requiring high-reliability stream resets under specific network conditions.

### Symptoms

This issue does not produce direct error logs or crashes. The symptom is a functional gap in protocol compliance with the WebTransport specification (`draft-ietf-webtrans-h3-13` and later). Applications or clients relying on this specific feature may not behave as expected.

### Root Cause Analysis

The WebTransport specification mandates support for `RESET_STREAM_AT` to ensure that a predictable amount of stream data is delivered before the stream is reset. This is a low-level frame type that must be implemented at the QUIC transport layer; it cannot be polyfilled or emulated at the application layer by `pywebtransport`.

### Impact Assessment

- **On Library Functionality**: **Medium**. For most use cases, the standard `RESET_STREAM` is sufficient. However, for scenarios requiring "at-least-once" semantics with precise data delivery on reset, this missing feature is a critical limitation.
- **On Protocol Compliance**: **High**. This prevents `pywebtransport` from being 100% compliant with the latest WebTransport specification, which could affect interoperability with other strictly compliant implementations.

### Current Status & Action Plan

1.  **Upstream Tracking**: We have submitted a formal feature request to the `aioquic` community to add support for this QUIC extension.
    - **Upstream Issue Link**: [aiortc/aioquic#596](https://github.com/aiortc/aioquic/issues/596)
2.  **Documentation**: This compliance limitation is formally documented in this `KNOWN_ISSUES.md` file.
3.  **Short-Term Strategy**: `pywebtransport` cannot provide this functionality until it is supported by `aioquic`. We will continue to monitor upstream progress.
