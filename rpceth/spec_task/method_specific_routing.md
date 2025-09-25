# Phase 4: Method-Specific Routing and Failure Strategies

## Objective
Design method-aware routing, retry, and circuit-breaker logic so that high-throughput read methods prefer reliable providers, write methods get tailored safeguards, and the proxy reacts gracefully to consecutive failures. Build on phases 1–3 without regressing existing functionality.

## Scope
- Method grouping (read vs write vs admin) with per-group tolerances, timeout overrides, and weight multipliers.
- Retry pipeline with exponential backoff + jitter and provider rotation on each attempt (max 3).
- Circuit breaker subsystem tracking soft vs hard failures, transition states, and gradual recovery.
- OpenTelemetry-compatible tracing for end-to-end request spans, retry attempts, and circuit transitions.

## Non-Goals
- Cross-chain routing (reserved for phase 5+).
- Full configuration hot-reload (baseline manual reload acceptable).

## Key Flows
1. Request intake reads method metadata and picks tolerance profile.
2. Load balancer filters providers using health score + method overrides.
3. Retry layer wraps forwarding call, applying jittered backoff and provider exclusion set.
4. Circuit breaker consults per-provider state prior to dispatch; closed ➜ open transitions emit tracing events.
5. Health service feeds breaker recovery after successful probes.

## Data Model Changes
- Extend config schema with:
  - `methods` table covering method wildcards (e.g., `eth_*`, `trace_*`, `engine_*`).
  - Fields: `tolerance_override`, `timeout_ms`, `weight_multiplier`, `max_retries`, `backoff_profile`.
- Add circuit-breaker parameters under `providers`: `failure_threshold`, `half_open_probe`, `reset_timeout_ms`.

## Implementation Plan
- Method registry module mapping method name → policy (use `globset` for wildcard matching).
- Retry layer built with `tower::retry` + `tower::retry::backoff::ExponentialBackoff`. Add jitter via `ExponentialBackoffMaker::jitter`. Ensure `MakeBackoff` clones per attempt.
- Circuit breaker: maintain `ProviderBreakerState` with counters, last failure time, state enum (`Closed`, `Open`, `HalfOpen`). Use `tokio::time::Instant` for windows and `tokio::sync::Mutex` to guard state.
- Integrate breaker into load balancer selection by excluding `Open` providers and allowing limited `HalfOpen` probes.
- Extend tracing: create parent span `proxy.request` with attributes (`method`, `trace_id`, `provider`). Add child span for each attempt capturing latency, backoff duration, breaker state, and health score.
- Update error responses to include `retries_attempted` in logs (not in client payload to preserve JSON-RPC spec).

## Libraries & Tools
- `globset` for wildcard method matching.
- `tower::retry`, `tower::retry::backoff` for retries.
- `backoff` crate for circuit breaker recovery timers if needed; otherwise rely on `tokio::time`.
- `tracing`, `tracing-opentelemetry`, `opentelemetry` to emit spans (phase 5 will wire exporters).

## Testing Strategy
- Unit tests for method policy resolution (`engine_*` picks strict tolerance).
- Property tests ensuring retry excludes already-failed providers and honors max attempts.
- Integration test simulating 3 consecutive failures to trigger circuit breaker, confirm subsequent call skips provider until recovery window passes.
- Trace assertions using `tracing-test` to verify span fields.

## Risks
- Increased latency if retries stack; mitigate with sane defaults and guard rails on `max_retries`.
- Overly strict tolerance can starve traffic; include fallback path when all providers filtered (return JSON-RPC error with trace ID and log).
- Circuit breaker misconfiguration causing thundering herd during recovery; half-open probes must be rate limited (one probe per interval).

## Typed RPC Integration with alloy-rpc-types

### Goal
Adopt `alloy-rpc-types` across the proxy stack to model Ethereum JSON-RPC payloads explicitly, enabling type-safe internal calls, richer validation, and method-aware routing without brittle string handling.

### Scope
- Shared request/response schema using alloy types for all `eth_*` (and other namespaces as enabled).
- Health probes, retries, and method policies operate on typed enums rather than raw `serde_json::Value`.
- Preserve ability to forward unrecognized methods transparently; only opt-in transformations use alloy types.

### Design Overview
1. **Dependency Wiring**
   - Add `alloy-rpc-types = { version = "^1.0", features = ["eth"] }` to `proxy-core` and `proxy-server`.
   - Gate additional namespaces (`trace`, `engine`, etc.) behind Cargo features so we only compile what we need.
2. **Core Data Model**
   - Define `JsonRpcEnvelope<T>` wrapper (struct with `jsonrpc`, `id`, `method`, `params`) to deserialize requests generically.
   - For known methods, map to `alloy_rpc_types::eth::request::EthRequest` variants via `TryFrom` implementations.
   - Represent responses with `alloy_rpc_types::eth::response::EthResponse` and fall back to raw `serde_json::Value` when the method is unknown or passthrough is required.
3. **Parsing Pipeline**
   - In `proxy-server`, parse inbound body into `JsonRpcEnvelope<Value>`.
   - Lookup method policy (phase 4) to determine if typed handling is required; if so, parse params using alloy helpers (`EthCallRequest`, `EthGetLogsFilter`, etc.).
   - Store typed payload alongside raw JSON in a new `ParsedRequest` struct shared with load balancer and retry logic.
4. **Forwarding Path**
   - When dispatching to providers, decide whether to serialize from typed struct (preferred) or reuse raw body (fallback).
   - For typed flows, use alloy serialization to ensure canonical hex formatting and field validation.
5. **Internal Calls**
   - Update health probe to construct `EthChainId`/`EthBlockNumber` requests via alloy request builders.
   - Future method-aware logic (retries, circuit breakers, metrics) reads standardized fields from typed enums (e.g., `EthRequest::Call` exposes `gas`, `block`, `tx`).
6. **Error Handling**
   - Translate alloy parsing errors into JSON-RPC `-32602` (invalid params) responses before forwarding.
   - Ensure passthrough behavior remains for methods we do not explicitly model.

### Implementation Steps
1. Add dependencies and feature flags in `proxy-core`/`proxy-server` Cargo manifests.
2. Create `crates/proxy-core/src/rpc/mod.rs` with:
   - `JsonRpcEnvelope` struct + serde helpers.
   - `ParsedRequest` enum capturing `Known(EthRequest)` vs `Unknown(Value)`.
   - Conversion utilities for responses.
3. Refactor `proxy-server::proxy_handler` to produce `ParsedRequest` and propagate method metadata to load balancer and retry code.
4. Replace manual JSON construction in `health::probe` with alloy request structs and decoding via `EthChainIdResponse`, `EthBlockNumberResponse`.
5. Extend method policy registry (phase 4) to work with `EthRequest` variants, enabling pattern matching without string parsing.
6. Add targeted tests:
   - Unit tests for envelope parsing and alloy conversions (valid + invalid hex, missing params).
   - Integration test ensuring unknown methods still proxy raw payloads unchanged.
   - Regression test for health probe using mocked provider to verify typed serialization.
7. Documentation updates in `details.md` and developer guide clarifying typed vs passthrough behavior.

### Risks & Mitigations
- **Coverage Gaps**: alloy may not yet expose every execution-apis method. Keep fallback path to raw JSON and track missing variants via logging.
- **Performance**: Additional serialization/deserialization overhead; mitigate with zero-copy references where alloy supports borrowed data and by retaining raw bytes for passthrough.
- **Version Drift**: Pin to caret version with dependabot monitoring; add compatibility tests against execution-apis fixtures.

### Future Extensions
- Enable `alloy-rpc-types-trace` and `-engine` when Phase 4/5 introduces namespace-specific logic.
- Build derive macros or helper traits to map alloy types to method policy configs automatically.
- Share `JsonRpcEnvelope` with admin/metrics endpoints for consistent typing across modules.
