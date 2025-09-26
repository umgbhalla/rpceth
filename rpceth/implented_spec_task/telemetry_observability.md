# Phase 5: Metrics & Observability Foundation

## Objective
Establish full observability for the proxy covering metrics, logs, and tracing with focus on request pipeline, provider health, and system lifecycle events. Provide operator endpoints and ensure readiness for multi-chain expansion.

## Scope
- Instrument proxy request flow with Prometheus-style metrics (counts, histograms, error codes) partitioned by method and provider.
- Expose `/metrics` endpoint using `metrics-exporter-prometheus` or `axum-prometheus`.
- Integrate `tracing-opentelemetry` to export spans to OTLP collector (configurable exporter target).
- Add structured logging for key events (request start/end, provider selection, health changes, circuit transitions).
- Implement graceful shutdown hooks ensuring metrics/tracing flush.

## Non-Goals
- Full multi-chain implementation (only placeholders for future extenders).
- Alerting rules (left to deployment tooling).

## Implementation Steps
1. Metrics Layer
   - Add dependency on `metrics`, `metrics-exporter-prometheus`, `metrics-util`.
   - Initialize recorder in `main.rs`; expose `/metrics` route.
   - Counters: `rpc_requests_total{method,provider,outcome}`.
   - Histograms: `rpc_request_duration_seconds{method,provider}` using exponential buckets.
   - Gauge: provider health scores via `metrics::gauge!` updated from `HealthService` snapshots.

2. Tracing & Logging
   - Configure `tracing-subscriber` with JSON formatter for logs; include trace ID.
   - Add `tracing_opentelemetry::layer()` to exporter pipeline. Provide config to toggle exporter (e.g., OTLP gRPC endpoint).
   - Ensure spans from Phase 4 include attributes `retry_attempt`, `backoff_ms`, `breaker_state`.
   - Add instrumentation to health probes and admin actions.

3. Admin Endpoints (tie-in with `admin_observability.md`)
   - `/healthz`: liveness.
   - `/readyz`: readiness based on all providers having non-zero health and no open breakers beyond threshold.
   - `/admin/providers`: dumps current health snapshots, breaker states, weight multipliers.
   - `/admin/reload`: trigger config reload (if enabled) and respond with status.

4. Graceful Shutdown
   - Use `tokio::signal` to listen for SIGINT/SIGTERM.
   - Introduce `ShutdownHandle` coordinating server graceful stop, health task cancellation, metrics flush.
   - Ensure in-flight requests complete within configurable timeout; otherwise abort with log.

5. Extensibility Prep
   - Introduce `ChainId` enum (Ethereum, placeholder for Solana) used in provider definitions.
   - Abstract health probes behind trait returning `ProviderHealthSnapshot` so new chains can plug their own logic.
   - Document extension points in code comments and spec.

## Testing Plan
- Unit tests verifying metrics counters increment correctly (use `metrics_util::debugging::DebuggingRecorder`).
- Integration tests hitting `/metrics` and validating presence of counters for existing phases.
- Simulate shutdown signal in test to confirm tasks exit and log events recorded.
- Snapshot tests for `/admin/providers` payload.

## Risks & Mitigations
- Performance impact from metrics/tracing: ensure batching and asynchronous exporters.
- Metrics cardinality explosion: limit method labels to defined groups/wildcards.
- Config reload race conditions: use `RwLock` or `tokio::sync::watch` to swap state safely.

## References
- Tower + OpenTelemetry example: `axum-tower-tracing-opentelemetry` showcase (GitHub, 2023).
- `metrics-exporter-prometheus` usage from Axum example (Ellie’s 2025 blog on exporting Prometheus metrics with Axum).
- `tower_governor` for rate-limiting (potential future addition).
