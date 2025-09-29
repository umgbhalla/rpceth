use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
    time::{Duration, Instant},
};

pub mod admin;

use axum::body::Body;
use axum::{
    Json, Router,
    extract::{Extension, Path, State},
    http::{HeaderMap, Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::post,
};
use metrics::{gauge, histogram, increment_counter};
use tokio::time::{Duration as TokioDuration, interval};
use tower::retry::backoff::{
    Backoff as TowerBackoff, ExponentialBackoff, ExponentialBackoffMaker, MakeBackoff,
};
use tracing::{error, info, instrument, warn};

use serde_json::json;
use url::form_urlencoded;

const API_KEY_PARAM: &str = "apikey";
const PROVIDER_PARAM: &str = "provider_id";

#[derive(Debug, Clone, Default)]
struct RequestContext {
    provider_override: Option<proxy_core::ProviderId>,
}

#[derive(Clone)]
pub struct ProxyState {
    pub config: proxy_core::ProxyConfig,
    pub client: reqwest::Client,
    pub providers_by_id: HashMap<proxy_core::ProviderId, proxy_core::ProviderHandle>,
    chains: HashMap<ChainKey, ChainRuntime>,
    alias_map: HashMap<String, ChainKey>,
    default_chain: Option<ChainKey>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct ChainKey(String);

#[derive(Clone)]
pub(crate) struct ChainRuntime {
    id: ChainKey,
    aliases: HashSet<String>,
    tolerance: proxy_core::ToleranceLevel,
    load_balancer: proxy_core::LoadBalancer,
    health_service: Option<Arc<proxy_core::HealthService>>,
    circuit_breaker: Arc<proxy_core::CircuitBreaker>,
    method_registry: Arc<proxy_core::MethodRegistry>,
    providers: HashSet<proxy_core::ProviderId>,
}

impl ChainRuntime {
    fn contains_provider(&self, provider: &proxy_core::ProviderId) -> bool {
        self.providers.contains(provider)
    }

    fn aliases(&self) -> impl Iterator<Item = &str> {
        self.aliases.iter().map(|alias| alias.as_str())
    }

    fn tolerance(&self) -> proxy_core::ToleranceLevel {
        self.tolerance
    }

    fn providers(&self) -> impl Iterator<Item = &proxy_core::ProviderId> {
        self.providers.iter()
    }

    fn health_enabled(&self) -> bool {
        self.health_service.is_some()
    }
}

impl ProxyState {
    pub fn new(mut config: proxy_core::ProxyConfig) -> Self {
        let client = reqwest::Client::builder()
            .pool_max_idle_per_host(8)
            .build()
            .expect("failed to build reqwest client");

        let provider_handles: Vec<proxy_core::ProviderHandle> = config
            .providers
            .iter()
            .cloned()
            .map(proxy_core::ProviderConfig::into_handle)
            .collect();

        let providers_by_id: HashMap<proxy_core::ProviderId, proxy_core::ProviderHandle> =
            provider_handles
                .iter()
                .map(|handle| (handle.id.clone(), handle.clone()))
                .collect();

        let mut chains: HashMap<ChainKey, ChainRuntime> = HashMap::new();
        let mut alias_map: HashMap<String, ChainKey> = HashMap::new();

        let base_method_registry = Arc::new(
            proxy_core::MethodRegistry::new(&config).expect("failed to build method registry"),
        );

        if config.chains.is_empty() {
            // Fallback to legacy single-chain behaviour
            let key = ChainKey("default".to_string());
            let runtime = build_chain_runtime(
                &key,
                &[],
                config.strategy,
                proxy_core::ToleranceLevel::Balanced,
                &provider_handles,
                &config,
                Arc::clone(&base_method_registry),
            );
            chains.insert(key.clone(), runtime);
            config.default_chain = Some(key.0.clone());
        } else {
            for (chain_id, chain_config) in &config.chains {
                let provider_subset: Vec<proxy_core::ProviderHandle> = chain_config
                    .providers
                    .iter()
                    .filter_map(|id| providers_by_id.get(id))
                    .cloned()
                    .collect();

                let key = ChainKey(chain_id.clone());
                let runtime = build_chain_runtime(
                    &key,
                    &chain_config.aliases,
                    config.strategy,
                    chain_config.tolerance.unwrap_or(config.default_tolerance),
                    &provider_subset,
                    &config,
                    Arc::clone(&base_method_registry),
                );

                register_alias(&mut alias_map, &key, std::iter::once(chain_id));
                register_alias(&mut alias_map, &key, chain_config.aliases.iter());

                chains.insert(key, runtime);
            }
        }

        let default_chain = config
            .default_chain
            .as_ref()
            .and_then(|id| chains.keys().find(|key| key.0 == *id).cloned());

        Self {
            config,
            client,
            providers_by_id,
            chains,
            alias_map,
            default_chain,
        }
    }

    pub fn api_key(&self) -> &str {
        self.config.auth.api_key.as_str()
    }

    pub fn chain_provider_handle(
        &self,
        provider_id: &proxy_core::ProviderId,
    ) -> Option<&proxy_core::ProviderHandle> {
        self.providers_by_id.get(provider_id)
    }

    fn resolve_chain(&self, chain_id: Option<&str>) -> Result<&ChainRuntime, ChainError> {
        let key = match chain_id {
            None | Some("") => self
                .default_chain
                .as_ref()
                .ok_or(ChainError::Unsupported("default".to_string()))?,
            Some(value) => {
                let normalized = normalize_chain_id(value);
                self.alias_map
                    .get(&normalized)
                    .ok_or_else(|| ChainError::Unsupported(value.to_string()))?
            }
        };

        self.chains
            .get(key)
            .ok_or_else(|| ChainError::Unsupported(key.0.clone()))
    }

    pub(crate) fn chains(&self) -> impl Iterator<Item = (&str, &ChainRuntime)> {
        self.chains
            .iter()
            .map(|(key, runtime)| (key.0.as_str(), runtime))
    }

    pub fn default_chain(&self) -> Option<&str> {
        self.default_chain.as_ref().map(|key| key.0.as_str())
    }
}

fn build_chain_runtime(
    key: &ChainKey,
    aliases: &[String],
    strategy: proxy_core::BalancerStrategy,
    tolerance: proxy_core::ToleranceLevel,
    providers: &[proxy_core::ProviderHandle],
    config: &proxy_core::ProxyConfig,
    method_registry: Arc<proxy_core::MethodRegistry>,
) -> ChainRuntime {
    let health_service: Option<Arc<proxy_core::HealthService>> = {
        if providers.is_empty() {
            None
        } else {
            #[cfg(test)]
            {
                None
            }

            #[cfg(not(test))]
            {
                let probe = Arc::new(proxy_core::health::JsonRpcHealthProbe::new(
                    Duration::from_secs(3),
                ));
                let service = Arc::new(proxy_core::HealthService::new(
                    providers.to_vec(),
                    tolerance,
                    Duration::from_secs(15),
                    probe,
                ));

                let runner = Arc::clone(&service);
                tokio::spawn(async move {
                    runner.spawn().await;
                });

                Some(service)
            }
        }
    };

    let circuit_breaker = Arc::new(proxy_core::CircuitBreaker::new(
        providers,
        &config.circuit_breaker,
    ));

    let load_balancer =
        proxy_core::LoadBalancer::new(strategy, providers.to_vec(), health_service.clone());

    ChainRuntime {
        id: key.clone(),
        aliases: aliases
            .iter()
            .map(|alias| normalize_chain_id(alias))
            .collect(),
        tolerance,
        load_balancer,
        health_service,
        circuit_breaker,
        method_registry,
        providers: providers.iter().map(|handle| handle.id.clone()).collect(),
    }
}

fn register_alias<'a, I>(map: &mut HashMap<String, ChainKey>, key: &ChainKey, aliases: I)
where
    I: IntoIterator<Item = &'a String>,
{
    for alias in aliases {
        map.insert(normalize_chain_id(alias), key.clone());
    }
}

fn normalize_chain_id(value: &str) -> String {
    percent_encoding::percent_decode_str(value)
        .decode_utf8_lossy()
        .trim()
        .to_ascii_lowercase()
}

#[derive(Debug)]
enum ChainError {
    Unsupported(String),
}

#[derive(Debug)]
enum ProxyOutcome {
    Success(Response),
    Failure(Response),
}

impl IntoResponse for ProxyOutcome {
    fn into_response(self) -> Response {
        match self {
            ProxyOutcome::Success(resp) | ProxyOutcome::Failure(resp) => resp,
        }
    }
}

pub fn build_router(config: proxy_core::ProxyConfig) -> Router {
    let state = ProxyState::new(config);
    Router::new()
        .route("/:chain_id", post(proxy_handler_with_chain))
        .route("/", post(proxy_handler_default))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            authenticate_request,
        ))
        .merge(admin::admin_routes())
        .with_state(state)
}

async fn authenticate_request(
    State(state): State<ProxyState>,
    mut req: Request<Body>,
    next: Next,
) -> Result<Response, Response> {
    if req.uri().path() == "/metrics" {
        return Ok(next.run(req).await);
    }

    let mut provided_key: Option<String> = None;
    let mut provider_override: Option<proxy_core::ProviderId> = None;

    if let Some(query) = req.uri().query() {
        for (key, value) in form_urlencoded::parse(query.as_bytes()) {
            if key == API_KEY_PARAM {
                provided_key = Some(value.into_owned());
            } else if key == PROVIDER_PARAM {
                provider_override = Some(proxy_core::ProviderId(value.into_owned()));
            }
        }
    }

    match provided_key {
        Some(ref key) if key == state.api_key() => {
            req.extensions_mut()
                .insert(RequestContext { provider_override });
            Ok(next.run(req).await)
        }
        _ => Err(unauthorized_response()),
    }
}

fn unauthorized_response() -> Response {
    Response::builder()
        .status(StatusCode::UNAUTHORIZED)
        .header("content-type", "application/json")
        .body(Body::from(
            json!({
                "error": {
                    "code": -32000,
                    "message": "unauthorized"
                }
            })
            .to_string(),
        ))
        .unwrap()
}

async fn proxy_handler_default(
    State(state): State<ProxyState>,
    Extension(ctx): Extension<RequestContext>,
    _headers: HeaderMap,
    Json(body): Json<serde_json::Value>,
) -> ProxyOutcome {
    proxy_handler_impl(state, ctx, None, body).await
}

async fn proxy_handler_with_chain(
    State(state): State<ProxyState>,
    Extension(ctx): Extension<RequestContext>,
    Path(chain_id): Path<String>,
    _headers: HeaderMap,
    Json(body): Json<serde_json::Value>,
) -> ProxyOutcome {
    proxy_handler_impl(state, ctx, Some(chain_id), body).await
}

#[instrument(
    skip(body, state, ctx),
    fields(
        method = body.get("method").and_then(|v| v.as_str()).unwrap_or("<unknown>"),
        request_id = body.get("id").and_then(|v| v.as_i64()).unwrap_or(0),
        jsonrpc_version = body.get("jsonrpc").and_then(|v| v.as_str()).unwrap_or("unknown"),
        otel_trace_id = tracing::field::Empty,
        otel.kind = "server"
    )
)]
async fn proxy_handler_impl(
    state: ProxyState,
    ctx: RequestContext,
    chain_id: Option<String>,
    body: serde_json::Value,
) -> ProxyOutcome {
    let request_start = Instant::now();

    // Get the OpenTelemetry trace ID from the current span context
    let trace_id = {
        use opentelemetry::trace::TraceContextExt;
        use tracing_opentelemetry::OpenTelemetrySpanExt;
        let context = tracing::Span::current().context();
        let span = context.span();
        let span_context = span.span_context();
        format!("{:032x}", span_context.trace_id())
    };

    // Record the OpenTelemetry trace_id in the current span
    tracing::Span::current().record("otel_trace_id", &trace_id);

    let method_name = body
        .get("method")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("<unknown>");
    let chain_runtime = match state.resolve_chain(chain_id.as_deref()) {
        Ok(runtime) => runtime,
        Err(err) => {
            return ProxyOutcome::Failure(build_chain_error_response(&body, trace_id, err));
        }
    };

    let method_policy = chain_runtime.method_registry.resolve(Some(method_name));
    let max_attempts = method_policy.max_retries.max(1);

    let mut tried = HashSet::new();
    let mut last_error: Option<String> = None;
    let mut backoff = method_policy.backoff.as_ref().map(make_backoff);

    let method_label = method_name.to_owned();
    let chain_label = chain_runtime.id.0.clone();

    // Record request start
    increment_counter!(
        "rpc_requests_total",
        "method" => method_label.clone(),
        "chain" => chain_label.clone(),
        "status" => "started"
    );

    // Record request volume metrics
    increment_counter!(
        "rpc_request_volume_total",
        "method" => method_label.clone(),
        "chain" => chain_label.clone()
    );

    for attempt in 0..max_attempts {
        let lb_selection_start = Instant::now();
        let provider = match select_provider(
            chain_runtime,
            &state.providers_by_id,
            &ctx,
            &tried,
            &method_policy,
        )
        .await
        {
            Some(provider) => provider,
            None => break,
        };
        let lb_selection_duration = lb_selection_start.elapsed();
        tried.insert(provider.id.clone());

        // Record load balancer selection metrics
        histogram!(
            "rpc_lb_selection_duration_seconds",
            lb_selection_duration.as_secs_f64(),
            "method" => method_label.clone(),
            "chain" => chain_label.clone(),
            "provider" => provider.id.0.clone()
        );

        // Record provider selection
        increment_counter!(
            "rpc_provider_selections_total",
            "method" => method_label.clone(),
            "chain" => chain_label.clone(),
            "provider" => provider.id.0.clone(),
            "attempt" => attempt.to_string()
        );

        chain_runtime.circuit_breaker.on_request_start(&provider.id);

        let span = tracing::info_span!(
            "proxy.attempt",
            method = method_name,
            provider = %provider.id.0,
            provider_url = %provider.url,
            attempt,
            otel_trace_id = %trace_id,
            timeout_ms = provider.timeout.as_millis(),
            max_retries = max_attempts,
            request_id = body.get("id").and_then(|v| v.as_i64()).unwrap_or(0),
            lb_selection_duration_us = lb_selection_duration.as_micros(),
            provider_weight = provider.base_weight,
            total_providers = state.config.providers.len(),
            tried_providers = tried.len()
        );
        span.in_scope(|| {
            info!(
                provider_url = %provider.url,
                timeout_ms = provider.timeout.as_millis(),
                "proxy forwarding request"
            );
        });

        let timeout_override = method_policy.timeout;
        let timeout = provider.timeout.max(timeout_override);

        let provider_request_start = Instant::now();
        match forward_to_provider(&state, &provider, &body, &trace_id, timeout).await {
            Ok(success) => {
                let provider_request_duration = provider_request_start.elapsed();
                let total_request_duration = request_start.elapsed();

                chain_runtime.circuit_breaker.on_success(&provider.id);

                // Record detailed timing in span
                span.in_scope(|| {
                    info!(
                        provider_request_duration_ms = provider_request_duration.as_millis(),
                        total_request_duration_ms = total_request_duration.as_millis(),
                        lb_overhead_us = lb_selection_duration.as_micros(),
                        "request completed successfully"
                    );
                });

                info!(
                    target: "proxy_server::forward",
                    trace_id = %trace_id,
                    chain = %chain_runtime.id.0,
                    method = %method_name,
                    provider = %provider.id.0,
                    status = success.status.as_u16(),
                    "proxy call success"
                );

                record_success_metrics(
                    method_name,
                    &provider.id,
                    &chain_runtime.id,
                    total_request_duration,
                    provider_request_duration,
                    lb_selection_duration,
                );

                // Record successful request completion
                increment_counter!(
                    "rpc_request_completions_total",
                    "method" => method_label.clone(),
                    "chain" => chain_label.clone(),
                    "status" => "success"
                );

                return ProxyOutcome::Success(build_success_response(success, trace_id));
            }
            Err(error_message) => {
                let provider_request_duration = provider_request_start.elapsed();
                let total_request_duration = request_start.elapsed();

                record_failure_metrics(
                    method_name,
                    Some(provider.id.0.as_str()),
                    &chain_runtime.id,
                    &error_message,
                );
                last_error = Some(error_message.clone());

                chain_runtime.circuit_breaker.on_failure(&provider.id);

                span.in_scope(|| {
                    error!(
                        error = %error_message,
                        provider_request_duration_ms = provider_request_duration.as_millis(),
                        total_request_duration_ms = total_request_duration.as_millis(),
                        lb_overhead_us = lb_selection_duration.as_micros(),
                        "provider attempt failed"
                    );
                });

                warn!(
                    target: "proxy_server::forward",
                    trace_id = %trace_id,
                    chain = %chain_runtime.id.0,
                    method = %method_name,
                    provider = %provider.id.0,
                    error = %error_message,
                    "proxy call failure"
                );

                if attempt + 1 < max_attempts {
                    if let Some(delay) = backoff.as_mut().map(TowerBackoff::next_backoff) {
                        span.in_scope(|| warn!("retrying request after backoff"));
                        delay.await;
                    }
                }
            }
        }
    }

    record_failure_metrics(method_name, None, &chain_runtime.id, "all providers failed");

    // Record failed request completion
    increment_counter!(
        "rpc_request_completions_total",
        "method" => method_label.clone(),
        "chain" => chain_label.clone(),
        "status" => "failure"
    );

    ProxyOutcome::Failure(build_error_response(&body, trace_id, last_error))
}

async fn select_provider(
    chain: &ChainRuntime,
    providers_by_id: &HashMap<proxy_core::ProviderId, proxy_core::ProviderHandle>,
    ctx: &RequestContext,
    tried: &HashSet<proxy_core::ProviderId>,
    policy: &proxy_core::MethodPolicy,
) -> Option<proxy_core::ProviderHandle> {
    if let Some(ref override_id) = ctx.provider_override {
        if !tried.contains(override_id) {
            if !chain.contains_provider(override_id) {
                return None;
            }

            if let Some(handle) = providers_by_id.get(override_id) {
                if chain.circuit_breaker.is_available(override_id) {
                    return Some(handle.clone());
                }
            }
        }
    }

    let mut excluded = tried.clone();
    if let Some(ref override_id) = ctx.provider_override {
        excluded.insert(override_id.clone());
    }

    loop {
        let provider = chain.load_balancer.select(&excluded, Some(policy)).await?;

        if chain.circuit_breaker.is_available(&provider.id) {
            return Some(provider);
        }

        excluded.insert(provider.id);
    }
}

fn make_backoff(policy: &proxy_core::ResolvedBackoff) -> ExponentialBackoff {
    ExponentialBackoffMaker::new(
        policy.min,
        policy.max,
        policy.jitter,
        tower::util::rng::HasherRng::default(),
    )
    .expect("invalid backoff configuration")
    .make_backoff()
}

async fn forward_to_provider(
    state: &ProxyState,
    provider: &proxy_core::ProviderHandle,
    request: &serde_json::Value,
    trace_id: &str,
    timeout_duration: Duration,
) -> Result<ProviderResponse, String> {
    let request_body = serde_json::to_vec(request).map_err(|err| err.to_string())?;

    let client = state.client.clone();
    let url = provider.url.clone();

    let fut = async move {
        client
            .post(url)
            .header("content-type", "application/json")
            .header("x-xray-id", trace_id)
            .body(request_body)
            .send()
            .await
    };

    let response = tokio::time::timeout(timeout_duration, fut)
        .await
        .map_err(|_| "provider request timed out".to_string())?
        .map_err(|err| err.to_string())?;

    if !response.status().is_success() {
        return Err(format!("provider returned status {}", response.status()));
    }

    let status = response.status();
    let headers = response.headers().clone();
    let bytes = response.bytes().await.map_err(|err| err.to_string())?;

    Ok(ProviderResponse {
        status,
        headers,
        body: bytes,
    })
}

struct ProviderResponse {
    status: StatusCode,
    headers: HeaderMap,
    body: bytes::Bytes,
}

fn build_success_response(provider_response: ProviderResponse, trace_id: String) -> Response {
    let mut response = Response::builder()
        .status(provider_response.status)
        .header("content-type", "application/json")
        .header("x-trace-id", trace_id); // Use x-trace-id for OpenTelemetry trace ID

    if let Some(value) = provider_response.headers.get("content-type") {
        response = response.header("content-type", value);
    }

    response
        .body(axum::body::Body::from(provider_response.body))
        .unwrap()
}

fn build_error_response(
    original_request: &serde_json::Value,
    trace_id: String,
    last_error: Option<String>,
) -> Response {
    let id = original_request
        .get("id")
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let error_message = last_error.unwrap_or_else(|| "all providers failed".to_string());

    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": -32001,
            "message": error_message,
        }
    });

    Response::builder()
        .status(StatusCode::BAD_GATEWAY)
        .header("content-type", "application/json")
        .header("x-trace-id", trace_id) // Use x-trace-id for OpenTelemetry trace ID
        .body(axum::body::Body::from(payload.to_string()))
        .unwrap()
}

fn build_chain_error_response(
    original_request: &serde_json::Value,
    trace_id: String,
    error: ChainError,
) -> Response {
    let id = original_request
        .get("id")
        .cloned()
        .unwrap_or(serde_json::Value::Null);

    let (code, message) = match error {
        ChainError::Unsupported(value) => (-32602, format!("unsupported chain: {}", value)),
    };

    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {
            "code": code,
            "message": message,
        }
    });

    Response::builder()
        .status(StatusCode::BAD_REQUEST)
        .header("content-type", "application/json")
        .header("x-trace-id", trace_id)
        .body(axum::body::Body::from(payload.to_string()))
        .unwrap()
}

fn record_success_metrics(
    method: &str,
    provider: &proxy_core::ProviderId,
    chain: &ChainKey,
    total_elapsed: Duration,
    provider_elapsed: Duration,
    lb_elapsed: Duration,
) {
    let method_label = method.to_owned();
    let provider_label = provider.0.clone();
    let chain_label = chain.0.clone();

    // Total request duration
    histogram!(
        "rpc_request_duration_seconds",
        total_elapsed.as_secs_f64(),
        "method" => method_label.clone(),
        "provider" => provider_label.clone(),
        "chain" => chain_label.clone()
    );

    // Provider-specific request duration
    histogram!(
        "rpc_provider_request_duration_seconds",
        provider_elapsed.as_secs_f64(),
        "method" => method_label.clone(),
        "provider" => provider_label.clone(),
        "chain" => chain_label.clone()
    );

    // Load balancer overhead
    histogram!(
        "rpc_lb_overhead_seconds",
        lb_elapsed.as_secs_f64(),
        "method" => method_label.clone(),
        "provider" => provider_label.clone(),
        "chain" => chain_label.clone()
    );

    // Success counter
    increment_counter!(
        "rpc_requests_total",
        "method" => method_label,
        "provider" => provider_label,
        "chain" => chain_label,
        "status" => "success"
    );
}

fn record_failure_metrics(method: &str, provider: Option<&str>, chain: &ChainKey, error: &str) {
    let method_label = method.to_owned();
    let provider_label = provider.unwrap_or("<none>").to_owned();
    increment_counter!(
        "rpc_requests_total",
        "method" => method_label.clone(),
        "provider" => provider_label.clone(),
        "chain" => chain.0.clone(),
        "status" => "failure"
    );
    increment_counter!(
        "rpc_errors_total",
        "method" => method_label,
        "provider" => provider_label,
        "chain" => chain.0.clone(),
        "code" => classify_error(error)
    );
}

fn classify_error(message: &str) -> &'static str {
    if message.contains("timed out") {
        "timeout"
    } else if message.contains("status 4") {
        "client"
    } else if message.contains("status 5") {
        "server"
    } else {
        "other"
    }
}

/// Background task to collect and export health metrics
pub async fn health_metrics_task(state: ProxyState) {
    let mut interval = interval(TokioDuration::from_secs(15)); // Update every 15 seconds

    loop {
        interval.tick().await;

        // Export provider health metrics
        for (chain_id, runtime) in state.chains() {
            let chain_label = chain_id.to_string();

            // Export chain-level metrics
            gauge!(
                "rpc_chain_provider_count",
                runtime.providers().count() as f64,
                "chain" => chain_label.clone()
            );

            gauge!(
                "rpc_chain_health_enabled",
                if runtime.health_enabled() { 1.0 } else { 0.0 },
                "chain" => chain_label.clone()
            );

            gauge!(
                "rpc_chain_tolerance_level",
                match runtime.tolerance() {
                    proxy_core::ToleranceLevel::Strict => 1.0,
                    proxy_core::ToleranceLevel::Balanced => 2.0,
                    proxy_core::ToleranceLevel::Relaxed => 3.0,
                },
                "chain" => chain_label.clone()
            );

            // Export provider-level metrics
            for provider_id in runtime.providers() {
                if let Some(provider) = state.chain_provider_handle(provider_id) {
                    let provider_label = provider_id.0.clone();

                    // Basic provider info
                    gauge!(
                        "rpc_provider_base_weight",
                        provider.base_weight as f64,
                        "provider" => provider_label.clone(),
                        "chain" => chain_label.clone()
                    );

                    gauge!(
                        "rpc_provider_timeout_seconds",
                        provider.timeout.as_secs_f64(),
                        "provider" => provider_label.clone(),
                        "chain" => chain_label.clone()
                    );

                    gauge!(
                        "rpc_provider_available",
                        if runtime.circuit_breaker.is_available(provider_id) { 1.0 } else { 0.0 },
                        "provider" => provider_label.clone(),
                        "chain" => chain_label.clone()
                    );

                    // Health metrics if available
                    if let Some(health_service) = &runtime.health_service {
                        let snapshots = health_service.snapshots();
                        if let Some(snapshot) =
                            snapshots.iter().find(|s| s.provider == *provider_id)
                        {
                            gauge!(
                                "rpc_provider_health_score",
                                snapshot.score,
                                "provider" => provider_label.clone(),
                                "chain" => chain_label.clone()
                            );

                            gauge!(
                                "rpc_provider_sync_score",
                                snapshot.sync_score,
                                "provider" => provider_label.clone(),
                                "chain" => chain_label.clone()
                            );

                            gauge!(
                                "rpc_provider_latency_score",
                                snapshot.latency_score,
                                "provider" => provider_label.clone(),
                                "chain" => chain_label.clone()
                            );

                            gauge!(
                                "rpc_provider_success_score",
                                snapshot.success_score,
                                "provider" => provider_label.clone(),
                                "chain" => chain_label.clone()
                            );

                            gauge!(
                                "rpc_provider_method_support_score",
                                snapshot.method_support_score,
                                "provider" => provider_label.clone(),
                                "chain" => chain_label.clone()
                            );

                            gauge!(
                                "rpc_provider_consecutive_failures",
                                snapshot.consecutive_failures as f64,
                                "provider" => provider_label.clone(),
                                "chain" => chain_label.clone()
                            );

                            if let Some(block) = snapshot.latest_block {
                                gauge!(
                                    "rpc_provider_latest_block",
                                    block as f64,
                                    "provider" => provider_label.clone(),
                                    "chain" => chain_label.clone()
                                );
                            }

                            if let Some(chain_id_val) = snapshot.chain_id {
                                gauge!(
                                    "rpc_provider_chain_id",
                                    chain_id_val as f64,
                                    "provider" => provider_label.clone(),
                                    "chain" => chain_label.clone()
                                );
                            }
                        }
                    }
                }
            }
        }

        // Export global configuration metrics
        gauge!(
            "rpc_config_total_providers",
            state.config.providers.len() as f64
        );

        gauge!("rpc_config_total_chains", state.chains().count() as f64);

        gauge!(
            "rpc_config_strategy",
            match state.config.strategy {
                proxy_core::BalancerStrategy::RoundRobin => 1.0,
                proxy_core::BalancerStrategy::WeightedRandom => 2.0,
            }
        );

        gauge!(
            "rpc_config_circuit_breaker_failure_threshold",
            state.config.circuit_breaker.failure_threshold.unwrap_or(5) as f64
        );

        gauge!(
            "rpc_config_circuit_breaker_reset_timeout_ms",
            state
                .config
                .circuit_breaker
                .reset_timeout_ms
                .unwrap_or(30000) as f64
        );
    }
}
