# RPCETH Core Library Implementation Documentation

## Architecture Overview

The RPCETH proxy is implemented as a Rust workspace with two main crates:

- **`proxy-core`**: Core library containing all business logic, configuration, health monitoring, load balancing, and routing
- **`proxy-server`**: HTTP server implementation using Axum that exposes the core functionality via REST API

### Core Components

```
proxy-core/
├── config.rs          # Configuration management and validation
├── provider.rs        # Provider definitions and handles
├── health/           # Health monitoring system
│   ├── model.rs      # Health data structures
│   ├── probe.rs      # Health probe implementations
│   └── service.rs    # Health service orchestration
├── routing/          # Load balancing and routing
│   └── load_balancer.rs
├── circuit.rs        # Circuit breaker implementation
├── methods.rs        # Method-specific routing and policies
└── error.rs          # Error handling
```

## Implemented Features

### 1. Configuration Management (`config.rs`)

**Complete Implementation**: Full YAML-based configuration with validation

```rust
pub struct ProxyConfig {
    pub strategy: BalancerStrategy,
    pub default_timeout_ms: u64,
    pub max_retries: u8,
    pub default_tolerance: ToleranceLevel,
    pub methods: MethodConfig,
    pub circuit_breaker: CircuitBreakerConfig,
    pub auth: AuthConfig,
    pub providers: Vec<ProviderConfig>,
    pub chains: HashMap<String, ChainConfig>,
    pub default_chain: Option<String>,
}
```

**Key Features**:
- Multi-chain support with chain-specific provider assignments
- Method-specific routing with groups and overrides
- Circuit breaker configuration per provider
- Comprehensive validation with detailed error messages
- YAML configuration loading with `ProxyConfigLoader`

### 2. Provider Management (`provider.rs`)

**Complete Implementation**: Provider configuration and runtime handles

```rust
pub struct ProviderConfig {
    pub id: ProviderId,
    pub url: Url,
    pub base_weight: u16,
    pub max_connections: u32,
    pub timeout_ms: u64,
    pub circuit_breaker: CircuitBreakerConfig,
}

pub struct ProviderHandle {
    pub id: ProviderId,
    pub url: Url,
    pub base_weight: u16,
    pub max_connections: u32,
    pub timeout: Duration,
    pub circuit_breaker: CircuitBreakerConfig,
}
```

**Key Features**:
- Provider weight configuration (1-1000 scale)
- Connection limits and timeouts
- Per-provider circuit breaker settings
- URL validation and provider ID uniqueness

### 3. Health Monitoring System (`health/`)

**Complete Implementation**: Comprehensive health tracking with multiple metrics

```rust
pub struct HealthService {
    state: Arc<DashMap<ProviderId, ProviderHealthState>>,
    tolerance: ToleranceLevel,
    interval: Duration,
    probe: Arc<dyn HealthProbe + Send + Sync>,
}

pub struct ProviderHealthState {
    pub provider: ProviderHandle,
    pub latest_block: Option<u64>,
    pub chain_id: Option<u64>,
    pub latency_avg: f64,
    pub success_rate: f64,
    pub sync_score: f64,
    pub method_support_score: f64,
    pub last_updated: Option<Instant>,
    pub consecutive_failures: u32,
}
```

**Key Features**:
- **Health Score Calculation**: Weighted formula combining sync (40%), latency (30%), success rate (20%), method support (10%)
- **Tolerance Levels**: Strict, Balanced, Relaxed filtering
- **Periodic Health Checks**: Configurable intervals with `eth_blockNumber` and `eth_chainId` probes
- **Exponential Weighted Moving Average**: Smooth latency and success rate tracking
- **Recovery Logic**: Gradual traffic restoration after failures

### 4. Load Balancing (`routing/load_balancer.rs`)

**Complete Implementation**: Two load balancing strategies with health-aware selection

```rust
pub enum BalancerStrategy {
    RoundRobin,
    WeightedRandom,
}

pub struct LoadBalancer {
    inner: Arc<LoadBalancerInner>,
}
```

**Key Features**:
- **Round Robin**: Sequential provider selection
- **Weighted Random**: Probability-based selection using provider weights
- **Health-Aware Selection**: Filters providers based on health scores and tolerance
- **Method-Specific Overrides**: Per-method weight multipliers and provider preferences
- **Exclusion Support**: Avoids previously failed providers during retries

### 5. Circuit Breaker (`circuit.rs`)

**Complete Implementation**: Three-state circuit breaker with configurable thresholds

```rust
pub enum CircuitStateKind {
    Closed,
    Open,
    HalfOpen,
}

pub struct CircuitBreaker {
    entries: DashMap<ProviderId, ProviderCircuit>,
}
```

**Key Features**:
- **Three States**: Closed (normal), Open (failing), HalfOpen (testing)
- **Configurable Thresholds**: Failure count, reset timeout, half-open probe count
- **Per-Provider Configuration**: Individual circuit breaker settings
- **Automatic Recovery**: Transitions from Open → HalfOpen → Closed
- **Request Tracking**: Monitors request start, success, and failure events

### 6. Method-Specific Routing (`methods.rs`)

**Complete Implementation**: Advanced method routing with groups, overrides, and backoff

```rust
pub struct MethodRegistry {
    default_timeout: Duration,
    default_tolerance: ToleranceLevel,
    default_max_retries: usize,
    default_weight_multiplier: f64,
    default_provider_weights: HashMap<ProviderId, f64>,
    default_backoff: Option<ResolvedBackoff>,
    groups: HashMap<String, MethodPolicy>,
    override_set: Arc<OverrideSet>,
}

pub struct MethodPolicy {
    pub tolerance: ToleranceLevel,
    pub timeout: Duration,
    pub weight_multiplier: f64,
    pub max_retries: usize,
    pub provider_weights: HashMap<ProviderId, f64>,
    pub backoff: Option<ResolvedBackoff>,
}
```

**Key Features**:
- **Method Groups**: Predefined groups (read, write) with shared policies
- **Pattern Matching**: Glob-based method pattern matching for overrides
- **Provider Weight Overrides**: Per-method provider weight customization
- **Exponential Backoff**: Configurable retry delays with jitter
- **Timeout Overrides**: Method-specific timeout configurations

### 7. HTTP Server Implementation (`proxy-server/`)

**Complete Implementation**: Full HTTP server with authentication, routing, and observability

```rust
pub struct ProxyState {
    pub config: proxy_core::ProxyConfig,
    pub client: reqwest::Client,
    pub providers_by_id: HashMap<proxy_core::ProviderId, proxy_core::ProviderHandle>,
    chains: HashMap<ChainKey, ChainRuntime>,
    alias_map: HashMap<String, ChainKey>,
    default_chain: Option<ChainKey>,
}
```

**Key Features**:
- **Multi-Chain Support**: Route requests to different chains via URL path
- **API Key Authentication**: Required API key for all requests
- **Provider Override**: Query parameter to force specific provider selection
- **Request Tracing**: OpenTelemetry integration with trace ID propagation
- **Retry Logic**: Configurable retry attempts with exponential backoff
- **Metrics Collection**: Prometheus metrics for request counts, durations, and errors

### 8. Admin and Observability (`admin.rs`)

**Complete Implementation**: Comprehensive admin endpoints and monitoring

```rust
pub fn admin_routes() -> Router<ProxyState> {
    Router::new()
        .route("/healthz", get(health_handler))
        .route("/readyz", get(readiness_handler))
        .route("/admin/providers", get(providers_handler))
        .route("/admin/config", get(config_handler))
}
```

**Key Features**:
- **Health Endpoints**: `/healthz` (liveness), `/readyz` (readiness)
- **Provider Status**: Detailed provider health and circuit breaker states
- **Configuration Info**: Non-sensitive configuration details
- **Metrics Endpoint**: Prometheus metrics at `/metrics`
- **Chain Information**: Multi-chain status and provider assignments

## Configuration Example

```yaml
strategy: weighted_random
default_timeout_ms: 5000
max_retries: 3
default_tolerance: Balanced
auth:
  api_key: change-me
providers:
  - id: alchemy
    url: https://eth-mainnet.g.alchemy.com/v2/demo
    base_weight: 900
    max_connections: 32
    timeout_ms: 2000
  - id: nodereal_eth
    url: https://eth-mainnet.nodereal.io/v1/demo
    base_weight: 600
    max_connections: 16
    timeout_ms: 2500
chains:
  ethereum:
    providers: [alchemy, nodereal_eth]
    aliases: [eth, main, 1]
    tolerance: Balanced
  polygon:
    providers: [nodereal_eth]
    aliases: [pol, 137]
    tolerance: Relaxed
default_chain: ethereum
methods:
  default:
    timeout_ms: 5000
    weight_multiplier: 1.0
    max_retries: 3
  groups:
    read:
      tolerance: Relaxed
      timeout_ms: 4000
      weight_multiplier: 1.1
      max_retries: 2
    write:
      tolerance: Strict
      timeout_ms: 8000
      weight_multiplier: 0.9
      max_retries: 4
  overrides:
    - pattern: "eth_get*"
      group: read
    - pattern: "eth_sendRawTransaction"
      group: write
```

## Testing Coverage

**Comprehensive Test Suite**:
- **Configuration Tests**: Validation, multi-chain support, provider validation
- **Health Scoring Tests**: Health service updates, load balancer health filtering
- **Load Balancer Tests**: Round-robin cycling, weighted random distribution
- **Method Routing Tests**: Pattern matching, provider overrides, backoff configuration
- **Integration Tests**: End-to-end proxy functionality with real RPC calls

## Dependencies

**Core Dependencies**:
- `axum`: HTTP server framework
- `reqwest`: HTTP client for upstream requests
- `serde_yaml`: YAML configuration parsing
- `dashmap`: Concurrent hash map for health state
- `tokio`: Async runtime
- `tracing`: Structured logging
- `metrics`: Prometheus metrics collection
- `opentelemetry`: Distributed tracing

## Performance Characteristics

- **Concurrent Health Monitoring**: Non-blocking health checks with configurable intervals
- **Efficient Load Balancing**: O(1) provider selection with health filtering
- **Memory Efficient**: Shared state with Arc for concurrent access
- **Low Latency**: Direct provider selection without unnecessary allocations
- **Scalable**: Supports multiple chains and providers with independent health tracking

## Production Readiness

**Fully Implemented Features**:
- ✅ Multi-chain routing with chain aliases
- ✅ Health monitoring with tolerance filtering
- ✅ Circuit breaker with automatic recovery
- ✅ Method-specific routing and retry policies
- ✅ Comprehensive observability and admin endpoints
- ✅ Request tracing and metrics collection
- ✅ Graceful shutdown and signal handling
- ✅ Configuration validation and error handling
