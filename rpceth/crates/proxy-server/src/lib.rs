use std::{
    collections::HashSet,
    sync::Arc,
    time::{Duration, Instant},
};

use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::post,
    Json, Router,
};
use tracing::{error, info, instrument, warn};
use tower::retry::backoff::{Backoff as TowerBackoff, ExponentialBackoff, ExponentialBackoffMaker, MakeBackoff};
use metrics::{counter, histogram, Key, Label};

#[derive(Clone)]
pub struct ProxyState {
    pub config: proxy_core::ProxyConfig,
    pub load_balancer: proxy_core::LoadBalancer,
    pub health_service: Option<Arc<proxy_core::HealthService>>,
    pub circuit_breaker: Arc<proxy_core::CircuitBreaker>,
    pub method_registry: proxy_core::MethodRegistry,
    pub client: reqwest::Client,
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
        }
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
        .route("/", post(proxy_handler))
        .with_state(state)
}

#[instrument(skip(body, state, headers))]
async fn proxy_handler(
    State(state): State<ProxyState>,
    headers: HeaderMap,
    Json(body): Json<serde_json::Value>,
) -> ProxyOutcome {
    let start = Instant::now();
    let trace_id = headers
        .get("x-xray-id")
        .and_then(|value| value.to_str().ok().map(|s| s.to_owned()))
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());

    let method_name = body
        .get("method")
        .and_then(serde_json::Value::as_str)
        .unwrap_or("<unknown>");
    let method_policy = state.method_registry.resolve(Some(method_name));
    let max_attempts = method_policy.max_retries.max(1);

    let mut tried = HashSet::new();
    let mut last_error: Option<String> = None;
    let mut backoff = method_policy
        .backoff
        .as_ref()
        .and_then(|cfg| make_backoff(cfg));

    let method_label = leak_label(method_name);
    let mut labels = Vec::with_capacity(2);
    labels.push(Label::new("method", method_name.to_owned()));
    labels.push(Label::new("status", "started"));
    counter!(Key::from_parts("rpc_requests_total", labels)).increment(1);

    for attempt in 0..max_attempts {
        let provider = match select_provider(&state, &tried, &method_policy).await {
            Some(provider) => provider,
            None => break,
        };
        tried.insert(provider.id.clone());

        state.circuit_breaker.on_request_start(&provider.id);

        let span = tracing::info_span!(
            "proxy.attempt",
            method = method_name,
            provider = %provider.id.0,
            attempt,
            trace_id = %trace_id
        );
        span.in_scope(|| {
            info!("proxy forwarding request");
        });

        let timeout_override = method_policy.timeout;
        let timeout = provider.timeout.max(timeout_override);

        match forward_to_provider(&state, &provider, &body, &trace_id, timeout).await {
            Ok(success) => {
                state.circuit_breaker.on_success(&provider.id);
                record_success_metrics(method_name, &provider.id, start.elapsed());
                return ProxyOutcome::Success(build_success_response(success, trace_id));
            }
            Err(error_message) => {
                record_failure_metrics(method_name, Some(provider.id.0.as_str()), &error_message);
                last_error = Some(error_message.clone());

                state.circuit_breaker.on_failure(&provider.id);

                span.in_scope(|| {
                    error!(
                        error = %error_message,
                        "provider attempt failed"
                    );
                });

                if attempt + 1 < max_attempts {
                    if let Some(backoff) = backoff.as_mut() {
                        let sleep = backoff.next_backoff();
                        span.in_scope(|| {
                            warn!("retrying request after backoff");
                        });
                        sleep.await;
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
    tried: &HashSet<proxy_core::ProviderId>,
    policy: &proxy_core::MethodPolicy,
) -> Option<proxy_core::ProviderHandle> {
    let mut excluded = tried.clone();

    loop {
        let provider = state.load_balancer.select(&excluded, Some(policy)).await?;

        if state.circuit_breaker.is_available(&provider.id) {
            return Some(provider);
        }

        excluded.insert(provider.id);
    }
}

fn make_backoff(
    policy: &proxy_core::ResolvedBackoff,
) -> Option<tower::retry::backoff::ExponentialBackoff> {
    let mut maker = tower::retry::backoff::ExponentialBackoffMaker::new(
        policy.min,
        policy.max,
        policy.jitter,
        tower::util::rng::HasherRng::default(),
    )
    .ok()?;

    Some(maker.make_backoff())
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
        .header("x-xray-id", trace_id);

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
        .header("x-xray-id", trace_id)
        .body(axum::body::Body::from(payload.to_string()))
        .unwrap()
}

fn record_success_metrics(method: &str, provider: &proxy_core::ProviderId, elapsed: Duration) {
    let mut hist_labels = Vec::with_capacity(2);
    hist_labels.push(Label::new("method", method.to_owned()));
    hist_labels.push(Label::new("provider", provider.0.clone()));
    histogram!(Key::from_parts("rpc_request_duration_seconds", hist_labels), elapsed.as_secs_f64());

    let mut success_labels = Vec::with_capacity(3);
    success_labels.push(Label::new("method", method.to_owned()));
    success_labels.push(Label::new("provider", provider.0.clone()));
    success_labels.push(Label::new("status", "success"));
    counter!(Key::from_parts("rpc_requests_total", success_labels)).increment(1);
}

fn record_failure_metrics(method: &str, provider: Option<&str>, error: &str) {
    let provider_value = provider.unwrap_or("<none>").to_owned();

    let mut failure_labels = Vec::with_capacity(3);
    failure_labels.push(Label::new("method", method.to_owned()));
    failure_labels.push(Label::new("provider", provider_value.clone()))
;    failure_labels.push(Label::new("status", "failure"));
    counter!(Key::from_parts("rpc_requests_total", failure_labels)).increment(1);

    let mut error_labels = Vec::with_capacity(3);
    error_labels.push(Label::new("method", method.to_owned()));
    error_labels.push(Label::new("provider", provider_value));
    error_labels.push(Label::new("code", classify_error(error)));
    counter!(Key::from_parts("rpc_errors_total", error_labels)).increment(1);
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

fn leak_label(value: &str) -> &'static str {
    Box::leak(value.to_owned().into_boxed_str())
}
