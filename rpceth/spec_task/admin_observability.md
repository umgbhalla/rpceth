# Admin Endpoints & Observability Spec

## Goals
- Provide operational endpoints for health status, readiness, configuration validation, and metrics export.
- Support graceful shutdown and runtime config reload.

## Key Tasks
- Implement `/healthz` (basic liveness), `/readyz` (readiness based on provider health/circuit states), `/metrics` (if metrics enabled), `/admin/providers` (optional detailed provider status).
- Add signal handling (e.g., SIGHUP) to trigger config reload without downtime; ensure new config validated and applied atomically.
- Implement graceful shutdown by listening for SIGINT/SIGTERM, draining in-flight requests, stopping health tasks, flushing telemetry.
- Validate configuration at startup and reload, returning explicit errors.

## File/Module Plan
- `crates/proxy-server/src/lib.rs`: extend router with new admin routes, maybe under `/admin/*` path; add state endpoints returning JSON snapshots.
- New module `crates/proxy-server/src/admin.rs`: handlers for liveness/readiness, provider listing, reload triggers.
- `crates/proxy-server/src/main.rs`: install signal listeners, call into admin module for reload/shutdown; ensure watchers integrate with `ProxyState`.
- `crates/proxy-core/src/config.rs`: implement reload logic (maybe `ProxyConfigLoader::watch` or manual re-read), ensure provider handles updated accordingly.
- Introduce background task manager to allow shutting down spawned health checks gracefully.
- Tests: 
  - Unit tests for readiness endpoint logic. 
  - Integration test verifying reload flow with test config, verifying requests use new providers after reload.

## Additional Considerations
- Address concurrency when swapping config (e.g., replace `Arc<ProxyState>` atomically or use RwLock).
- Provide authentication or guard for admin endpoints if considering production (future work).
- Log all admin operations with trace context for auditing.
