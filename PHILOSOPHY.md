# Implementation Philosophy

This document outlines the core principles that guide the design and development of PyWebTransport.

---

PyWebTransport is engineered to be a **standards-compliant and robust** implementation of the WebTransport protocol for the Python ecosystem. Our philosophy prioritizes standards compliance, a clean architecture, and long-term maintainability.

### 1. Strict Adherence to Standards

The primary responsibility of this library is correctness. The core protocol layer—encompassing connection, stream, and datagram management—is implemented in strict accordance with the official IETF WebTransport specifications, currently targeting **[draft-ietf-webtrans-http3-13](https://www.ietf.org/archive/id/draft-ietf-webtrans-http3-13.txt)**.

- **Standard as the Sole Authority**: We treat the official IETF drafts and RFCs as the single source of truth.
- **No Compatibility Patches**: The core implementation does not include patches or workarounds for buggy, non-standard, or outdated clients. We believe that adhering strictly to the standard is the best way to foster a healthy and interoperable ecosystem.

### 2. Layered and Composable Design

As a foundational infrastructure component, PyWebTransport is designed with a clear separation of concerns, ensuring a lean and pure protocol core.

- **Pure Protocol Core**: The low-level protocol implementation is kept independent of application-level concerns. It focuses solely on providing a reliable and efficient transport layer.
- **Optional Application Toolkit**: High-level utilities such as serializers, RPC frameworks, or Pub/Sub patterns are provided as optional, pluggable modules. This allows developers to build complex applications quickly without bloating the core protocol implementation.

### 3. Standard-Focused Development and Testing

Our development and testing practices prioritize protocol correctness over accommodating specific implementation quirks.

- **E2E as Verification**: End-to-end (E2E) tests between our own client and server implementations serve as the primary means of validating correctness against the standard.
- **Correctness Over Compatibility**: While external tools like Web Platform Tests (WPT) are valuable references, we will not sacrifice protocol correctness to pass tests that accommodate divergent or erroneous browser behavior. Our goal is to promote the standard, not to patch over deviations.

---

We believe this disciplined approach will provide long-term value to the Python community and the broader internet ecosystem.
