# Health Monitoring Enhancements Specification

## Goals
- Refine health scoring to account for circuit breaker state, failure types, and latency spikes.
- Implement adaptive probe intervals and recovery acceleration.
- Capture rich health metrics for observability.

## Key Tasks
- Adjust scoring formula to introduce penalties for circuit breakers (score zero while open), differentiate timeout/failure severity.
- Track latency percentiles over time (maybe using rolling histogram) rather than single EWMA.
- Introduce adaptive probe cadence: rapid probing for failed providers, slower for stable ones.
- Log chain-specific health data (sync lag, chain ID mismatches) with higher fidelity.
- Emit metrics per provider: health score, probe success/failure counts, last probe latency.

## File/Module Plan
- `crates/proxy-core/src/health/service.rs`: update `ProviderHealthState` to store additional stats (histograms, failure causes); integrate circuit breaker hooks; adjust `apply_success`/`apply_failure` logic.
- `crates/proxy-core/src/health/probe.rs`: support custom probe intervals (maybe pass `Duration` per provider); capture failure reasons more granularly.
- `crates/proxy-core/src/health/model.rs`: extend `ProviderHealthSnapshot` with new fields (breaker state, latency percentiles, failure counts).
- Add new module `crates/proxy-core/src/health/adaptive.rs` (optional) to manage dynamic scheduling (maybe spawn per-provider tasks with individualized intervals using `tokio::time::sleep_until`).
- `crates/proxy-server/src/lib.rs`: expose health snapshot data via admin endpoint; integrate metrics emission.
- Update configuration to allow customizing probe intervals, method weights, recovery thresholds.
- Tests: 
  - Unit tests verifying new scoring adjustments. 
  - Integration tests simulating slow vs fast providers and ensuring filtering responds dynamically.

## Additional Considerations
- Ensure adaptive scheduling does not spawn unlimited tasks; central scheduler may manage provider intervals.
- Consider decoupling health probe clients from request clients to avoid interference.
- Provide debug logging hooks for health transitions to aid operations.

# Phase 3 Review & Phase 5 Health Extensions

## Completed in Phase 3
- Built `HealthService` maintaining EWMA latency, success rate, and method support per provider using `dashmap` with periodic probes (`tokio::time::interval` every 15s). Health score formula aligns with spec weights (sync 0.4, latency 0.3, success 0.2, method support 0.1).
- Implemented `JsonRpcHealthProbe` invoking `eth_chainId` & `eth_blockNumber`, parsing hex responses, capturing latency, mapping failures (timeout, HTTP status, payload parsing).
- Integrated tolerance filtering in `LoadBalancer`: only providers within tolerance threshold of best score participate; fallback to all providers if none pass.
- Stored consecutive failure counts to inform Phase 4 circuit breaker integration.

## Gaps / Next Steps
- Need configurable probe interval and tolerance level overrides (per-method in Phase 4, per-chain in Phase 5).
- Health snapshots should publish aggregated metrics for Prometheus (Phase 5 requirement).
- Recovery backoff currently immediate; Phase 3 spec requires exponential backoff + 30s probe interval for failed providers.

## Phase 5 Health Extension Spec
- Allow health service to adjust probe cadence per provider based on consecutive failures (exponential backoff, capped at 5 minutes).
- Introduce `HealthEvent` channel to broadcast updates to metrics subsystem and admin endpoints.
- Provide API for circuit breaker to request immediate probe (half-open support).
- Support pluggable probe implementations keyed by chain (Ethereum default, placeholders for Solana). Define trait `ChainProbeFactory` returning `Arc<dyn HealthProbe>`.
- Persist limited health history (last N snapshots) for debugging via `/admin/providers`.
- Metrics: expose `provider_health_score{provider}`, `provider_latency_ms{provider}` gauges.

## Testing
- Mock probe returning canned responses to validate backoff progression.
- Ensure tolerance filtering excludes providers under strict mode when score gap exceeds threshold.
- Verify event stream captures both success and failure transitions for metrics export.
