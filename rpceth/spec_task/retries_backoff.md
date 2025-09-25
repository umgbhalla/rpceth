# Phase 4 Supporting Spec: Retry, Backoff, and Circuit Breaking

## Purpose
Detail the behavior of the retry subsystem, exponential backoff policy, and circuit breaker integration required for method-aware routing.

## Requirements
- Retry attempts must be capped (default 3) with per-method overrides.
- Backoff schedule uses exponential growth with jitter to avoid synchronized retries.
- Each retry must select a different provider when possible; providers in `Open` breaker state are skipped.
- Circuit breaker thresholds differentiate between soft (HTTP 4xx, JSON-RPC errors) and hard failures (timeouts, HTTP 5xx, transport errors).

## Design
- Implement `RetryPolicy` struct capturing per-method limits and tolerance.
- Use `tower::retry::RetryLayer` with custom policy returning `Action::Retry(Duration)` populated via `ExponentialBackoff` (min 200ms, max 2s, jitter 30%).
- Maintain `AttemptContext` storing attempted provider IDs to avoid repeats.
- Circuit breaker state machine:
  - Closed: normal operation counting consecutive hard failures.
  - Open: skip provider for `reset_timeout_ms`; failures increment while open for logging only.
  - HalfOpen: allow single probe request; success ➜ Closed, failure ➜ Open with doubled timeout (`reset_timeout_ms` * 2, capped).
- Use `tokio::sync::Mutex<HashMap<ProviderId, BreakerState>>` with timestamps.
- Emit tracing events on state transitions including `provider`, `state`, `failures`, `next_probe_at`.

## Config Additions
```
methods:
  - pattern: "eth_call"
    max_retries: 2
    timeout_ms: 2000
    tolerance_override: strict
    backoff_profile:
      min_ms: 150
      max_ms: 1200
      jitter: 0.25
providers:
  - id: ...
    circuit_breaker:
      failure_threshold: 3
      reset_timeout_ms: 10000
      half_open_probe: single
```

## Testing
- Unit test backoff builder to ensure jitter range (±30%).
- Simulate successive failures to ensure breaker transitions to Open.
- Ensure half-open success resets state and logs `breaker.recovered` event.
- Verify integration test of write method hits limited retries and surfaces JSON-RPC error when all providers fail.

## References
- `tower::retry::backoff::ExponentialBackoffMaker` documentation (July 2025 release).
- `tokio_retry` examples for jittered exponential delays.
