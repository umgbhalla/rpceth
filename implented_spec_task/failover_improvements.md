# Failover Logic Improvements Specification

## Goals
- Ensure seamless transition when providers fail, coordinating with retries, circuit breakers, and health scores.
- Reduce latency impact by proactively selecting backup providers within tolerance windows.
- Provide visibility into failover events.

## Key Tasks
- Integrate circuit breaker state, health snapshots, and method overrides to build ordered fallback candidate list per request.
- Precompute provider preference list factoring base weights, health multipliers, method priority, fallback tiers.
- On failure, apply backoff delay, mark provider as attempted, and select next candidate; if exhaustion occurs, optionally relax tolerance or fallback to `Relaxed` mode.
- Emit tracing events/metrics for failover occurrences, including root cause (timeout, HTTP error, circuit open).
- Consider caching short-lived failover decisions to avoid thrashing (cooldown per provider/method pair).

## File/Module Plan
- `crates/proxy-core/src/routing/load_balancer.rs`: extend `select` API to return ordered iterator or provide `select_next` helper; incorporate method metadata and breaker states.
- `crates/proxy-server/src/lib.rs`: restructure request loop to consult new selection logic; maintain `AttemptContext` recording tries, delays, reason codes.
- `crates/proxy-core/src/config.rs`: allow configuration of tolerance relaxation steps, fallback strategies, cooldown durations.
- Introduce new module `crates/proxy-core/src/failover.rs` (optional) encapsulating failover planning algorithms, including candidate ranking and cooldown caches, enabling reuse by both routing and health modules.
- Update metrics module to export counters/histograms for failover events.
- Tests: 
  - Integration tests simulating provider failure mid-request to ensure alternative provider used with minimal delay. 
  - Tests verifying tolerance relaxation after all eligible providers fail.

## Additional Considerations
- Ensure failover respects method-specific restrictions (some methods may not permit fallback to certain providers).
- Provide hooks for future features like provider tags/regions to influence selection.
- Document behavior for operations, including manual override to force provider disablement.
- Confirm success after failure returns early and stops retry loop.

## Dependencies
- Works in concert with `circuit_breaker.md` for state machine behavior.
- Requires updated LoadBalancer filters (Phase 4 plan) and health events (Phase 5 extension).
