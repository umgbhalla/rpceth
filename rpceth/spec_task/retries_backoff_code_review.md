# Phase 4 Retry & Backoff Gap Review

## Current Implementation Snapshot
- `crates/proxy-server/src/lib.rs` drives retries with a manual `for attempt` loop. It constructs a `tower::retry::backoff::ExponentialBackoff`, but the loop is not wrapped in `tower::retry::RetryLayer`, so policy decisions and delays are hand-rolled.
- Provider rotation relies on a `HashSet<ProviderId>` named `tried`. Providers are excluded after each attempt, but there is no explicit attempt context or guard against exhausted pools beyond breaking out of the loop.
- All upstream failures are collapsed into `Err(String)` values (e.g., "provider returned status 500"). HTTP 4xx, 5xx, timeouts, and JSON-RPC errors are treated the same for retries and the circuit breaker.
- `CircuitBreaker::on_failure` increments counters for every failure without distinguishing soft vs hard failures, and there is no exponential increase of the open-state cooldown.
- Backoff parameters come from `MethodPolicy::backoff`, but jitter bounds are not validated in tests and there is no logging of the effective delay per attempt.
- Tracing currently records attempts via `info!`/`warn!` logs but does not emit structured metadata (retry attempt number, backoff duration, breaker state) required for Phase 4 observability.

## Required Adjustments to Meet Spec
- Introduce a retry policy built on `tower::retry::RetryLayer` that:
  - Classifies outcomes into `RetryDecision` values (continue, fail fast on soft errors, open breaker on hard errors).
  - Pulls per-method caps (`max_retries`, `backoff`) from `MethodPolicy` and instantiates `ExponentialBackoffMaker` with the configured jitter range.
  - Tracks attempted provider IDs in an `AttemptContext` so each retry picks a fresh provider when possible and short-circuits if the pool is exhausted.
- Extend failure handling to distinguish:
  - **Hard** failures (timeouts, transport errors, HTTP 5xx) that should increment breaker counters and trigger retries.
  - **Soft** failures (HTTP 4xx, JSON-RPC user errors) that should bypass retries, return immediately, and only log the failure.
- Enhance `CircuitBreaker`:
  - Store soft vs hard failure tallies and only transition to `Open` on hard failures meeting the configured threshold.
  - Implement exponential backoff for the `retry_at` window (`reset_timeout_ms`, `reset_timeout_ms * 2`, capped) and reset the multiplier after a successful half-open probe.
  - Emit structured tracing events on state transitions with `provider`, `state`, `failures`, `next_probe_at`.
- Surface retry diagnostics:
  - Record retry attempt count, provider ID, and chosen backoff delay via `tracing::Span` fields so Phase 5 telemetry can consume them.
  - Consider attaching the final `retries_attempted` count to server logs (while keeping JSON-RPC responses unchanged).
- Validate backoff configuration boundaries in dedicated unit tests (min ≤ max, jitter ∈ [0.0, 1.0]) and cover jitter randomness within ±configured range.

## Test & Verification Plan
- **Unit tests** for the new retry policy to ensure:
  - Soft failures stop retries and propagate the original error payload.
  - Hard failures respect the max-attempt cap and rotate providers without repeats.
  - Backoff durations grow exponentially and include jitter within expected bounds.
- **Circuit breaker tests** covering Closed → Open → HalfOpen transitions, exponential cooldown growth, and recovery after a successful probe.
- **Integration test** (Axum/httpmock) simulating two failing providers followed by a healthy one to confirm provider rotation and bounded retries, plus a scenario where all providers return 400 to verify no retries occur.
- **Tracing test** using `tracing-test` or a collector stub to assert recorded span attributes (`retry_attempt`, `backoff_ms`, breaker state changes).
