# Architecture

RPCETH separates provider routing from the HTTP transport. `proxy-core` owns configuration, method policies, health scoring, selection, and circuit breakers. `proxy-server` builds the chain runtimes and exposes them through Axum.

## A request through the gateway

1. RPC authentication checks the `apikey` query parameter. An optional `provider_id` becomes a request-scoped provider override.
2. The gateway resolves the path to a chain name or alias. Requests to `/` use the configured default chain.
3. The method registry resolves a policy from defaults, groups, and glob overrides.
4. Provider selection uses the chain's pool, health data, policy, circuit state, and providers already tried for this request.
5. The server forwards the JSON body with a timeout. Success updates circuit state and returns the upstream response. Failure records the attempt and can select another provider within the attempt budget.
6. Metrics and tracing record the request and its attempts. Background health probes supply provider snapshots used by selection.

```mermaid
sequenceDiagram
    participant Client
    participant Gateway
    participant Policy as Chain and method policy
    participant Pool as Provider selection
    participant A as RPC node A
    participant B as RPC node B
    Client->>Gateway: JSON-RPC request + API key
    Gateway->>Policy: Resolve chain and method
    Policy-->>Gateway: Pool and attempt policy
    Gateway->>Pool: Select eligible provider
    Pool-->>Gateway: Node A
    Gateway->>A: Forward request
    A-->>Gateway: Failed attempt
    Note over Gateway: Update circuit state; exclude A
    opt Attempt budget and another provider remain
        Gateway->>Pool: Select next provider
        Pool-->>Gateway: Node B
        Gateway->>B: Forward request
        B-->>Gateway: Response
    end
    Gateway-->>Client: Response or final error
```

This is an illustrative failover sequence, not a guarantee that every upstream error is retryable. See the forwarding implementation for exact error classification.

## Code map

| Responsibility | Source |
| --- | --- |
| YAML parsing and validation | [`config.rs`](../crates/proxy-core/src/config.rs) |
| Provider definitions | [`provider.rs`](../crates/proxy-core/src/provider.rs) |
| Method policy resolution | [`methods.rs`](../crates/proxy-core/src/methods.rs) |
| Health probes and snapshots | [`health/`](../crates/proxy-core/src/health/) |
| Weighted / round-robin selection | [`load_balancer.rs`](../crates/proxy-core/src/routing/load_balancer.rs) |
| Circuit states | [`circuit.rs`](../crates/proxy-core/src/circuit.rs) |
| HTTP routing and forwarding | [`proxy-server/src/lib.rs`](../crates/proxy-server/src/lib.rs) |
| Status endpoints | [`admin.rs`](../crates/proxy-server/src/admin.rs) |
| Startup and telemetry exporters | [`main.rs`](../crates/proxy-server/src/main.rs) |

## Current boundaries

- **HTTP transport.** The server registers POST routes for JSON-RPC. It does not expose a WebSocket subscription route.
- **Attempt limits.** The forwarding loop uses `max_retries.max(1)` as its total number of attempts. It does not add that many retries after an initial attempt.
- **Timeouts.** The forwarding timeout currently takes the larger of the provider timeout and method timeout. A smaller method timeout does not shorten a larger provider timeout.
- **Readiness.** `/readyz` examines circuit availability. Its implementation marks the service unready when any configured provider is unavailable; it is not a proof of fresh block synchronization.
- **Metrics state.** Startup constructs a separate `ProxyState` for the background metrics task. Its circuit state is distinct from the request router's state, so those gauges should not be treated as an exact view of request-path circuits.
- **Configuration.** The executable reads `config/proxy.yaml` from its working directory and binds to `0.0.0.0:3000`. These are not CLI options. SIGHUP currently completes the shutdown signal future; it does not reload configuration.
- **Access.** RPC authentication is applied before admin routes are merged. Admin and metrics endpoints need separate ingress protection when exposed beyond a trusted network.

These notes describe inspected source, not a deployment certification or a benchmark. Historical implementation documents may describe intended behavior beyond what the executable currently provides.
