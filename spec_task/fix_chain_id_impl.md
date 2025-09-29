Fix Specification: Chain ID–Aware Multi-Chain Routing & Validation
Root Cause
The proxy currently ignores the /:chain_id path segment. All requests hit the same global provider pool (ProxyState.config.providers), so every chain ID returns Ethereum results (e.g., /137 still returns 0x1).
Incoming chain_id path values are not validated, so malformed inputs (SQL injection strings, Unicode, etc.) are accepted and passed downstream.
Trace logs show repeated 429 throttles because all traffic hits the same upstream regardless of the requested chain.
Phase docs (method-specific routing) explicitly deferred cross-chain support; Phase 5 requires a foundation for multi-chain routing and config reloads.
Goals
Chain ID Routing: Route requests to chain-specific provider pools based on the /:chain_id path segment, with support for numeric IDs (e.g., 1) and canonical aliases (e.g., eth, polygon, bsc).
Validation & Security: Strictly validate chain IDs against configured allowlists; reject unknown or malformed chain IDs with JSON-RPC-compliant errors.
Default Behavior: Maintain current behavior for / (no chain ID) by routing to the default EVM chain configured (likely Ethereum); configurable fallback if desired.
Graceful Errors: Return JSON-RPC -32602 (invalid params) for malformed chain strings and -32004-style bespoke error for unsupported chains, with 400 HTTP status.
Provider Pools: Select load balancer and provider sets per chain, keeping method policies and circuit breaker logic intact but scoped to the relevant pool.
Configuration: Extend config/proxy.yaml schema to define chains, mapping chain_id / aliases → provider IDs, tolerance overrides, and defaults. Provide YAML validation.
Health & Metrics: Propagate chain context to metrics, circuit breaker logs, and health probes. Ensure per-chain provider availability is visible in admin endpoints.
Testing: Update smoke tests to expect correct chain-specific responses, run sample requests pre/post-change, and expand unit/integration test coverage.
Observability: Tag traces/logs with chain_id for improved debugging.
Design Overview
Detailed Plan
Config Schema
Introduce ChainConfig struct in proxy-core::config:
Each chain references existing providers by ID (ensures reuse of ProviderConfig).
Add default_chain for / route.
Validate: every alias unique across chains; chain has >=1 providers; referenced providers exist; optional url_prefix for admin expansions.
ProxyState Restructure
Precompute:
HashMap<ChainKey, ChainRuntime> where ChainRuntime holds LoadBalancer, CircuitBreaker, MethodRegistry, HealthService configured for chain’s provider subset.
ChainKey includes canonical id (numeric string) & alias set.
providers_by_id remains global, but ChainRuntime references only required handles.
Request Handling
Modify proxy_handler route to extract Path<Option<String>> for chain_id.
Normalize: lowercase, trim whitespace, decode percent-encoding.
Map to canonical chain using alias map. If missing:
Respond HTTP 400 with JSON-RPC error code: -32602, message: invalid chain_id.
Retrieve chain-specific runtime (ChainRuntime) to pass into selection/forwarding pipeline instead of global state.
Provider Selection Changes
Adjust select_provider, forward_to_provider to operate using the ChainRuntime context rather than state.config.providers.
RequestContext now carries both provider override and selected ChainId.
Provider override must reference provider that belongs to the selected chain; otherwise reject with error.
Circuit Breaker & Health
Each chain’s providers share the existing proxy_core::CircuitBreaker but scoped to chain’s subset. Consider per-chain breaker instance to avoid cross-talk.
Health service: either instantiate per chain or adapt existing service to accept filtered provider list per chain.
Admin/Observability
Update /admin/providers & readiness endpoints to show per-chain provider affiliation.
Include chain_id tag in metrics counters (rpc_requests_total, rpc_errors_total) and proxy.attempt span.
Error Handling
Add guard for invalid chain_id path segment before authentication? (Probably after, but before load balancing.)
For unsupported chains: HTTP 400, JSON-RPC error {"code": -32602, "message": "unsupported chain: {chain_id}"}.
Testing
Update smoke tests: expect eth_chainId returns correct result per chain.
Add unit tests for ChainRegistry alias resolution & validation.
Integration tests: request /1, /137, /polygon, ensure provider overrides restricted to chain.
Security tests: ensure malformed chain IDs return JSON-RPC error with correct status & message.
Migration
Provide sample config updates in README, ensure backwards compatibility (if no chains defined, fallback to single global provider behavior with warning).
Document in README_CHAINID_TESTS.md updated behavior & expected config.
Out-of-Scope (Future)
Dynamic chain discovery.
Non-EVM/future chain support (Phase 5).
Hot reload implementation (but design for later extension).
Implementation Tasks
Config & Parsing
[ ] Extend ProxyConfig with chains: HashMap<String, ChainConfig>, default_chain: String.
[ ] Implement ChainConfig::validate() ensuring providers exist and alias set unique.
[ ] Build ChainRegistry (map alias → canonical key).
ProxyState
[ ] Update ProxyState::new to build HashMap<ChainKey, ChainRuntime>:
ChainRuntime { id, aliases, load_balancer, circuit_breaker, method_registry, health_service }.
Global providers_by_id remains for lookups.
[ ] Add method resolve_chain(&self, chain_str: Option<&str>) -> Result<&ChainRuntime, ChainError>.
Handler Flow
[ ] Change router to route("/:chain_id", post(proxy_handler)).
[ ] In handler, parse chain_id using new ChainRegistry.
[ ] Pass ChainRuntime into select_provider/forward_to_provider.
[ ] Ensure provider override must belong to chain runtime, else error.
Metrics & Tracing
[ ] Add chain label to metrics counters/histograms.
[ ] Include chain field in tracing spans/logs.
[ ] Ensure x-trace-id still propagated.
Error Responses
[ ] Add helper chain_error_response(id, trace_id, message, code) for 400 cases.
[ ] Ensure HTTP 400 used for invalid chain (not 502).
Tests
Config validation units.
Handler tests verifying chain selection & error cases.
Integration tests hitting /1, /137, /unknown.
Update smoke tests to assert correct results.
Docs
Update README_CHAINID_TESTS.md to reflect expected behavior.
Add new docs entry for chain configuration.
Acceptance Criteria
/1 returns Ethereum ChainId 0x1; /137 returns Polygon 0x89; /56 returns BSC 0x38.
/polygon alias works.
/invalid_chain returns HTTP 400 with JSON-RPC error -32602.
Provider override only works within chain’s provider list.
Metrics show chain label.
Admin endpoints reveal per-chain provider availability.
All smoke tests pass.
This fix spec provides a roadmap to complete Phase 5’s chain routing foundation, eliminate misrouted traffic, and harden security around the chain ID parameter.
