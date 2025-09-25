use std::{collections::HashSet, sync::Arc, time::Duration};

use axum::extract::State;
use axum::response::IntoResponse;
use axum::response::Response;
use axum::{Json, Router, routing::post};
use http::{HeaderMap, StatusCode};
#[cfg(not(test))]
use proxy_core::ToleranceLevel;
#[cfg(not(test))]
use proxy_core::health::JsonRpcHealthProbe;
use proxy_core::{
    CircuitBreaker, HealthService, LoadBalancer, MethodPolicy, MethodRegistry, ProviderConfig,
    ProviderHandle, ProviderId, ProxyConfig, ResolvedBackoff,
};
use serde_json::{Value, json};
use tokio::time::timeout;
use tower::retry::backoff::{
    Backoff as TowerBackoff, ExponentialBackoff, ExponentialBackoffMaker, MakeBackoff,
};
use tower::util::rng::HasherRng;
use tracing::{error, info, instrument, warn};
use uuid::Uuid;

#[derive(Clone)]
pub struct ProxyState {
    pub config: ProxyConfig,
    pub load_balancer: LoadBalancer,
    pub health_service: Option<Arc<HealthService>>,
    pub circuit_breaker: Arc<CircuitBreaker>,
    pub method_registry: MethodRegistry,
    pub client: reqwest::Client,
}

impl ProxyState {
    pub fn new(config: ProxyConfig) -> Self {
        let client = reqwest::Client::builder()
            .pool_max_idle_per_host(8)
            .build()
            .expect("failed to build reqwest client");

        let provider_handles: Vec<ProviderHandle> = config
            .providers
            .iter()
            .cloned()
            .map(ProviderConfig::into_handle)
            .collect();

        let health_service: Option<Arc<HealthService>> = {
            #[cfg(test)]
            {
                None
            }

            #[cfg(not(test))]
            {
                let probe = Arc::new(JsonRpcHealthProbe::new(Duration::from_secs(3)));
                let service = Arc::new(HealthService::new(
                    provider_handles.clone(),
                    ToleranceLevel::Balanced,
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

        let circuit_breaker = Arc::new(CircuitBreaker::new(
            &provider_handles,
            &config.circuit_breaker,
        ));

        let load_balancer = LoadBalancer::new(
            config.strategy,
            provider_handles.clone(),
            health_service.clone(),
        );

        let method_registry =
            MethodRegistry::new(&config).expect("failed to build method registry");

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

pub fn build_router(config: ProxyConfig) -> Router {
    let state = ProxyState::new(config);
    Router::new()
        .route("/", post(proxy_handler))
        .with_state(state)
}

#[instrument(skip(body, state, headers))]
async fn proxy_handler(
    State(state): State<ProxyState>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> ProxyOutcome {
    let trace_id = headers
        .get("x-xray-id")
        .and_then(|value| value.to_str().ok().map(|s| s.to_owned()))
        .unwrap_or_else(|| Uuid::new_v4().to_string());

    let mut tried = HashSet::new();
    let mut last_error: Option<String> = None;
    let method_name = body.get("method").and_then(Value::as_str);
    let method_policy = state.method_registry.resolve(method_name);
    let max_attempts = method_policy.max_retries.max(1);
    let timeout_override = method_policy.timeout;
    let mut backoff: Option<ExponentialBackoff> = method_policy
        .backoff
        .as_ref()
        .and_then(|cfg| make_backoff(cfg));

    for attempt in 0..max_attempts {
        let provider = match select_provider(&state, &tried, &method_policy).await {
            Some(provider) => provider,
            None => break,
        };

        state.circuit_breaker.on_request_start(&provider.id);

        info!(
            provider = %provider.id.0,
            %trace_id,
            attempt,
            "proxy forwarding request"
        );

        let timeout = provider.timeout.max(timeout_override);

        match forward_to_provider(&state, &provider, &body, &trace_id, timeout).await {
            Ok(success) => {
                state.circuit_breaker.on_success(&provider.id);
                return ProxyOutcome::Success(build_success_response(success, trace_id));
            }
            Err(error_message) => {
                error!(
                    provider = %provider.id.0,
                    %trace_id,
                    attempt,
                    %error_message,
                    "provider attempt failed"
                );
                last_error = Some(format!(
                    "provider {} attempt {} failed: {}",
                    provider.id.0, attempt, error_message
                ));
                tried.insert(provider.id.clone());

                state.circuit_breaker.on_failure(&provider.id);

                if attempt + 1 < max_attempts {
                    if let Some(backoff) = backoff.as_mut() {
                        let sleep = backoff.next_backoff();
                        warn!(
                            %trace_id,
                            attempt = attempt + 1,
                            provider = %provider.id.0,
                            "retrying request after backoff"
                        );
                        sleep.await;
                    }
                }
                continue;
            }
        }
    }

    ProxyOutcome::Failure(build_error_response(&body, trace_id, last_error))
}

async fn select_provider(
    state: &ProxyState,
    tried: &HashSet<ProviderId>,
    policy: &MethodPolicy,
) -> Option<ProviderHandle> {
    let mut excluded = tried.clone();

    loop {
        let provider = state.load_balancer.select(&excluded, Some(policy)).await?;

        if state.circuit_breaker.is_available(&provider.id) {
            return Some(provider);
        }

        excluded.insert(provider.id);
    }
}

fn make_backoff(policy: &ResolvedBackoff) -> Option<ExponentialBackoff> {
    let mut maker =
        ExponentialBackoffMaker::new(policy.min, policy.max, policy.jitter, HasherRng::default())
            .ok()?;

    Some(maker.make_backoff())
}

async fn forward_to_provider(
    state: &ProxyState,
    provider: &ProviderHandle,
    request: &Value,
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

    let response = timeout(timeout_duration, fut)
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
    original_request: &Value,
    trace_id: String,
    last_error: Option<String>,
) -> Response {
    let id = original_request.get("id").cloned().unwrap_or(Value::Null);

    let error_message = last_error.unwrap_or_else(|| "all providers failed".to_string());

    let payload = json!({
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
