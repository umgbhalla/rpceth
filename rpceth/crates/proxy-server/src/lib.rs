use std::{
    collections::{HashMap, HashSet},
    convert::Infallible,
    sync::Arc,
    time::{Duration, Instant},
};

pub mod admin;

use axum::body::Body;
use axum::{
    Json, Router,
    extract::{Extension, Path, State},
    http::{HeaderMap, Request, StatusCode, Uri},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::post,
};
use metrics::{histogram, increment_counter};
use tower::retry::backoff::{
    Backoff as TowerBackoff, ExponentialBackoff, ExponentialBackoffMaker, MakeBackoff,
};
use tracing::{error, info, instrument, warn};

use serde::Deserialize;
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
    pub load_balancer: proxy_core::LoadBalancer,
    pub health_service: Option<Arc<proxy_core::HealthService>>,
    pub circuit_breaker: Arc<proxy_core::CircuitBreaker>,
    pub method_registry: proxy_core::MethodRegistry,
    pub client: reqwest::Client,
    pub providers_by_id: HashMap<proxy_core::ProviderId, proxy_core::ProviderHandle>,
}

impl ProxyState {
    pub fn new(config: proxy_core::ProxyConfig) -> Self {
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

        let health_service: Option<Arc<proxy_core::HealthService>> = {
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
                    provider_handles.clone(),
                    proxy_core::ToleranceLevel::Balanced,
                    Duration::from_secs(15),
                    probe,
                ));

                let runner = Arc::clone(&service);
                tokio::spawn(async move {
                    runner.spawn().await;
                });

                Some(service)
            }
        };

        let circuit_breaker = Arc::new(proxy_core::CircuitBreaker::new(
            &provider_handles,
            &config.circuit_breaker,
        ));

        let load_balancer = proxy_core::LoadBalancer::new(
            config.strategy,
            provider_handles.clone(),
            health_service.clone(),
        );

        let method_registry =
            proxy_core::MethodRegistry::new(&config).expect("failed to build method registry");

        Self {
            config,
            load_balancer,
            health_service,
            circuit_breaker,
            method_registry,
            client,
            providers_by_id,
        }
    }

    pub fn api_key(&self) -> &str {
        self.config.auth.api_key.as_str()
    }
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
        .route("/metrics", get(crate::main::metrics_handler))
        .route("/:chain_id", post(proxy_handler))
        .route("/", post(proxy_handler))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            authenticate_request,
        ))
        .merge(admin::admin_routes())
        .with_state(state)
}

async fn authenticate_request<B>(
    State(state): State<ProxyState>,
    mut req: Request<B>,
    next: Next<B>,
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

#[instrument(
    skip(body, state, _headers),
    fields(
        method = body.get("method").and_then(|v| v.as_str()).unwrap_or("<unknown>"),
        request_id = body.get("id").and_then(|v| v.as_i64()).unwrap_or(0),
        jsonrpc_version = body.get("jsonrpc").and_then(|v| v.as_str()).unwrap_or("unknown"),
        otel_trace_id = tracing::field::Empty
    )
)]
async fn proxy_handler(
    State(state): State<ProxyState>,
    Extension(ctx): Extension<RequestContext>,
    _headers: HeaderMap,
    Json(body): Json<serde_json::Value>,
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
    let method_policy = state.method_registry.resolve(Some(method_name));
    let max_attempts = method_policy.max_retries.max(1);

    let mut tried = HashSet::new();
    let mut last_error: Option<String> = None;
    let mut backoff = method_policy.backoff.as_ref().map(make_backoff);

    let method_label = method_name.to_owned();
    increment_counter!(
        "rpc_requests_total",
        "method" => method_label,
        "status" => "started"
    );

    for attempt in 0..max_attempts {
        let lb_selection_start = Instant::now();
        let provider = match select_provider(&state, &ctx, &tried, &method_policy).await {
            Some(provider) => provider,
            None => break,
        };
        let lb_selection_duration = lb_selection_start.elapsed();
        tried.insert(provider.id.clone());

        state.circuit_breaker.on_request_start(&provider.id);

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

                state.circuit_breaker.on_success(&provider.id);

                // Record detailed timing in span
                span.in_scope(|| {
                    info!(
                        provider_request_duration_ms = provider_request_duration.as_millis(),
                        total_request_duration_ms = total_request_duration.as_millis(),
                        lb_overhead_us = lb_selection_duration.as_micros(),
                        "request completed successfully"
                    );
                });

                record_success_metrics(method_name, &provider.id, total_request_duration);
                return ProxyOutcome::Success(build_success_response(success, trace_id));
            }
            Err(error_message) => {
                let provider_request_duration = provider_request_start.elapsed();
                let total_request_duration = request_start.elapsed();

                record_failure_metrics(method_name, Some(provider.id.0.as_str()), &error_message);
                last_error = Some(error_message.clone());

                state.circuit_breaker.on_failure(&provider.id);

                span.in_scope(|| {
                    error!(
                        error = %error_message,
                        provider_request_duration_ms = provider_request_duration.as_millis(),
                        total_request_duration_ms = total_request_duration.as_millis(),
                        lb_overhead_us = lb_selection_duration.as_micros(),
                        "provider attempt failed"
                    );
                });

                if attempt + 1 < max_attempts {
                    if let Some(delay) = backoff.as_mut().map(TowerBackoff::next_backoff) {
                        span.in_scope(|| warn!("retrying request after backoff"));
                        delay.await;
                    }
                }
            }
        }
    }

    record_failure_metrics(method_name, None, "all providers failed");

    ProxyOutcome::Failure(build_error_response(&body, trace_id, last_error))
}

async fn select_provider(
    state: &ProxyState,
    ctx: &RequestContext,
    tried: &HashSet<proxy_core::ProviderId>,
    policy: &proxy_core::MethodPolicy,
) -> Option<proxy_core::ProviderHandle> {
    if let Some(ref override_id) = ctx.provider_override {
        if !tried.contains(override_id) {
            if let Some(handle) = state.providers_by_id.get(override_id) {
                if state.circuit_breaker.is_available(override_id) {
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
        let provider = state.load_balancer.select(&excluded, Some(policy)).await?;

        if state.circuit_breaker.is_available(&provider.id) {
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

fn record_success_metrics(method: &str, provider: &proxy_core::ProviderId, elapsed: Duration) {
    let method_label = method.to_owned();
    let provider_label = provider.0.clone();
    histogram!(
        "rpc_request_duration_seconds",
        elapsed.as_secs_f64(),
        "method" => method_label.clone(),
        "provider" => provider_label.clone()
    );
    increment_counter!(
        "rpc_requests_total",
        "method" => method_label,
        "provider" => provider_label,
        "status" => "success"
    );
}

fn record_failure_metrics(method: &str, provider: Option<&str>, error: &str) {
    let method_label = method.to_owned();
    let provider_label = provider.unwrap_or("<none>").to_owned();
    increment_counter!(
        "rpc_requests_total",
        "method" => method_label.clone(),
        "provider" => provider_label.clone(),
        "status" => "failure"
    );
    increment_counter!(
        "rpc_errors_total",
        "method" => method_label,
        "provider" => provider_label,
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
