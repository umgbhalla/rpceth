# Method-Aware Routing Specification

## Goals
- Parse JSON-RPC method names and apply method-specific routing behavior.
- Support per-method overrides for tolerance, timeout, retries, weight multipliers, circuit breaker sensitivity.
- Categorize methods into strategy groups (read, write, critical) to influence provider selection.

## Key Tasks
- Extend configuration schema to define method overrides and method groups.
- Parse overrides at startup; validate method names, default fallback behavior.
- Modify proxy handler to look up method metadata before selecting provider.
- Apply overrides to load balancer (e.g., tighter tolerance, weight boost), timeouts, retry count, circuit breaker thresholds.
- Add logging/tracing fields capturing method group and overrides applied.

## File/Module Plan
- `crates/proxy-core/src/config.rs`: add structs for `MethodConfig`, `MethodGroupConfig`, extend validation.
- `config/proxy.yaml`: introduce new `methods:` section with examples.
- New module `crates/proxy-core/src/methods.rs`: hold lookup tables, default group definitions, helper functions to fetch method policies.
- `crates/proxy-server/src/lib.rs`: during request handling, resolve method metadata; adjust `max_attempts`, `timeout`, `tolerance`, and provider weighting prior to selection.
- `crates/proxy-core/src/routing/load_balancer.rs`: accept dynamic weight/tolerance inputs per selection request.
- Update health scoring/circuit breaker modules to accept per-method adjustments (e.g., strict thresholds for writes).
- Tests: add unit tests ensuring config parsing; integration tests verifying read vs write methods route differently under artificially varied health scores.

## Additional Considerations
- Provide sensible defaults for unspecified methods (inherit from `default` group).
- Permit wildcard or prefix matching for method families (`eth_get*`), possibly using glob or regex; evaluate complexity.
- Ensure thread-safe caches for method lookup (e.g., `DashMap` or `Arc<HashMap>` built at startup).
- Document new configuration in repository docs/spec.
