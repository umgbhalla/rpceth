# Circuit Breaker Specification

## Goals
- Introduce provider-level circuit breaker enforcing open/half-open/closed states.
- Prevent repeated calls to unhealthy providers while allowing controlled recovery.
- Integrate with health scoring, retries, and metrics.

## Key Tasks
- Define breaker configuration (failure threshold, open timeout, half-open probe attempts, reset window).
- Persist breaker state per provider using thread-safe data structure (e.g., `DashMap<ProviderId, CircuitState>`).
- Update request flow to consult breaker before selecting provider; skip providers in `Open` state.
- On failure, increment counter; when threshold reached, transition to `Open`, schedule timer to half-open.
- On half-open attempt, allow limited test requests; success resets to `Closed`, failure returns to `Open` with backoff.
- Expose breaker state via metrics/admin endpoints; include trace logs when state changes occur.
- Coordinate with health service (e.g., on open state, reduce health score, adjust tolerance inclusion).

## File/Module Plan
- New module `crates/proxy-core/src/circuit.rs`: define `CircuitBreaker`, `CircuitState`, state machine logic, configuration handling.
- `crates/proxy-core/src/config.rs`: extend config for breaker defaults and per-provider/method overrides.
- `config/proxy.yaml`: add `circuit_breaker` block with defaults (thresholds, cooldowns).
- `crates/proxy-server/src/lib.rs`: integrate breaker checks into provider selection and failure handling; record transitions in traces.
- `crates/proxy-core/src/health/service.rs`: adjust health snapshots to reflect breaker state (e.g., set multiplier to 0 for open providers); ensure periodic probes can reopen.
- `crates/proxy-core/src/routing/load_balancer.rs`: update `eligible` provider filtering to skip open circuits.
- Tests: 
  - Unit tests covering state transitions (closed → open → half-open → closed, with backoff). 
  - Integration tests verifying breaker opens after consecutive failures, prevents selection, and recovers after cooldown.

## Additional Considerations
- Align breaker thresholds with method-specific policies (e.g., writes more sensitive).
- Provide manual override via admin endpoint to reset breaker state (future enhancement).
- Ensure timers/shutdown handle gracefully (use `tokio::time::sleep` with cancellation on drop).
- Document interplay between breaker and health scoring to avoid conflicting behaviors.
