# Phase 1 Research Notes

- **Library Layout**: Rust packages can expose a reusable `lib.rs` while hosting executables under `src/bin/*`; modules partition functionality cleanly for the proxy core and HTTP server implementation (see Rust Book guidance on packages and modules).
- **Async Runtime & HTTP Server**: `tokio` provides the multi-threaded async runtime; pair with `axum` or lower-level `hyper` for the HTTP server to accept JSON-RPC requests.
- **JSON-RPC Handling**: `jsonrpsee` supplies HTTP and WebSocket JSON-RPC servers/clients with serde-based request parsing, minimizing custom protocol code.
- **HTTP Upstream Client**: `reqwest` (Tokio-native) or `hyper` client handles forwarding to the upstream Ethereum RPC endpoint with timeout configuration.
- **JSON Serialization**: `serde` and `serde_json` cover request validation and response proxying while preserving JSON-RPC envelope fields.
- **Tracing & Logging**: `tracing` plus `tracing-subscriber` enable structured spans; attach an `xrayid` generated via `uuid` or `ulid` crates for per-request correlation.
- **Error Handling**: `thiserror` aids in defining proxy error types that map to JSON-RPC error objects; wrap upstream timeouts via `tokio::time::timeout`.
- **Reverse Proxy Helpers**: `axum-proxy` and `axum-reverse-proxy` offer ready-made Tower `Service` layers for forwarding requests when using Axum, reducing boilerplate.

