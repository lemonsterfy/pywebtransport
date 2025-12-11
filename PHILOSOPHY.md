# Implementation Philosophy

This document outlines the core principles that guide the design and development of PyWebTransport.

---

PyWebTransport is engineered to be a **standards-compliant and robust** implementation of the WebTransport protocol for the Python ecosystem. Our philosophy prioritizes standards compliance, clean architecture, and long-term maintainability.

## Core Tenets

- **The Standard is the Sole Authority**: We treat IETF Drafts and formal RFCs as the only technical basis for implementation decisions.
- **Rejection of Compatibility Patches**: The core implementation does not include compatibility patches or workarounds for non-standard, flawed, or outdated clients. Strict adherence to the standard is the foundation of a healthy, interoperable ecosystem.

### 1. Strict Adherence to Standards

The primary responsibility of this library is correctness. The core protocol layer—encompassing connection, stream, and datagram management—is implemented in strict accordance with the official IETF WebTransport specifications, currently targeting **[draft-ietf-webtrans-http3-14](https://www.ietf.org/archive/id/draft-ietf-webtrans-http3-14.txt)**.

**Note on Active Draft Implementations**: When our target specification remains in an active IETF draft stage, this library will prioritize tracking and implementing the IETF Working Group's (WG) latest live consensus, even if that consensus is not yet reflected in the published draft text. This approach ensures forward-compatibility and avoids implementing features already deprecated by WG resolution.

### 2. Layered and Composable Design

As a foundational infrastructure component, PyWebTransport is designed with a clear separation of concerns, ensuring a lean and pure protocol core.

- **Pure Protocol Core**: The low-level protocol implementation is kept independent of application-level concerns. It focuses solely on providing a reliable and efficient transport layer.
- **Optional Application Toolkit**: High-level utilities such as **pluggable serializers** and **structured messaging** wrappers are provided as optional modules. This allows developers to build complex applications quickly without bloating the core protocol implementation.

### 3. Standard-Focused Development and Testing

Our development and testing practices prioritize protocol correctness over accommodating specific implementation quirks.

- **E2E as Verification**: End-to-end (E2E) tests between our own client and server implementations serve as the primary means of validating correctness against the standard.
- **Correctness Over Compatibility**: While external tools like Web Platform Tests (WPT) are valuable references, we will not sacrifice protocol correctness to pass tests that accommodate divergent or erroneous browser behavior. Our goal is to promote the standard, not to patch over deviations.

---

We believe this disciplined approach will provide long-term value to the Python community and the broader internet ecosystem.
