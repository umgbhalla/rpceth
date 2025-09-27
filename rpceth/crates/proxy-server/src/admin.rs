use axum::{
    Router,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Json, Response},
    routing::get,
};
use serde_json::json;
use std::collections::HashMap;
use tracing::{info, instrument};

use crate::ProxyState;

/// Build admin routes for health, readiness, and provider status
pub fn admin_routes() -> Router<ProxyState> {
    Router::new()
        .route("/healthz", get(health_handler))
        .route("/readyz", get(readiness_handler))
        .route("/admin/providers", get(providers_handler))
        .route("/admin/config", get(config_handler))
}

/// Basic liveness check - always returns OK if the service is running
#[instrument(skip(_state))]
async fn health_handler(State(_state): State<ProxyState>) -> impl IntoResponse {
    info!("health check requested");

    let response = json!({
        "status": "healthy",
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "service": "proxy-server",
        "version": env!("CARGO_PKG_VERSION")
    });

    (StatusCode::OK, Json(response))
}

/// Readiness check based on provider health and circuit breaker states
#[instrument(skip(state))]
async fn readiness_handler(State(state): State<ProxyState>) -> impl IntoResponse {
    info!("readiness check requested");

    let mut ready = true;
    let mut provider_statuses = HashMap::new();
    let mut issues = Vec::new();

    // Check each provider's circuit breaker status
    for (chain_id, runtime) in state.chains() {
        let mut chain_providers = Vec::new();
        let mut available_in_chain = 0usize;
        let mut total_in_chain = 0usize;

        for provider_id in runtime.providers() {
            total_in_chain += 1;
            let provider = match state.chain_provider_handle(provider_id) {
                Some(handle) => handle,
                None => continue,
            };

            let is_available = runtime.circuit_breaker.is_available(provider_id);
            if is_available {
                available_in_chain += 1;
            }

            chain_providers.push(json!({
                "id": provider_id.0,
                "url": provider.url,
                "timeout_ms": provider.timeout.as_millis(),
                "weight": provider.base_weight,
                "available": is_available,
            }));

            if !is_available {
                ready = false;
                issues.push(format!(
                    "Provider {} (chain {}) is not available",
                    provider_id.0, chain_id
                ));
            }
        }

        provider_statuses.insert(
            chain_id.to_string(),
            json!({
                "chain": chain_id,
                "available_providers": available_in_chain,
                "total_providers": total_in_chain,
                "providers": chain_providers,
            }),
        );

        if available_in_chain == 0 {
            ready = false;
            issues.push(format!("No providers are available for chain {}", chain_id));
        }
    }

    let status_code = if ready {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    let response = json!({
        "status": if ready { "ready" } else { "not_ready" },
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "chains": provider_statuses,
        "issues": issues,
        "default_chain": state.default_chain(),
    });

    (status_code, Json(response))
}

/// Detailed provider status including health metrics if available
#[instrument(skip(state))]
async fn providers_handler(State(state): State<ProxyState>) -> impl IntoResponse {
    info!("provider status requested");

    let mut chains_info = Vec::new();

    for (chain_id, runtime) in state.chains() {
        let mut providers_info = Vec::new();

        for provider_id in runtime.providers() {
            if let Some(provider) = state.chain_provider_handle(provider_id) {
                let is_available = runtime.circuit_breaker.is_available(provider_id);

                let health_info = json!({
                    "health_check_enabled": runtime.health_enabled(),
                });

                providers_info.push(json!({
                    "id": provider_id.0,
                    "url": provider.url,
                    "weight": provider.base_weight,
                    "timeout_ms": provider.timeout.as_millis(),
                    "available": is_available,
                    "health": health_info
                }));
            }
        }

        chains_info.push(json!({
            "chain": chain_id,
            "aliases": runtime.aliases().collect::<Vec<_>>(),
            "tolerance": format!("{:?}", runtime.tolerance()),
            "provider_count": providers_info.len(),
            "providers": providers_info,
        }));
    }

    let response = json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "total_chains": chains_info.len(),
        "strategy": format!("{:?}", state.config.strategy),
        "chains": chains_info,
        "default_chain": state.default_chain(),
    });

    (StatusCode::OK, Json(response))
}

/// Configuration information (non-sensitive parts)
#[instrument(skip(state))]
async fn config_handler(State(state): State<ProxyState>) -> impl IntoResponse {
    info!("configuration info requested");

    let response = json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "service": {
            "name": "proxy-server",
            "version": env!("CARGO_PKG_VERSION")
        },
        "load_balancing": {
            "strategy": format!("{:?}", state.config.strategy),
            "total_providers": state.config.providers.len()
        },
        "circuit_breaker": {
            "enabled": true,
            "failure_threshold": state.config.circuit_breaker.failure_threshold,
            "reset_timeout_ms": state.config.circuit_breaker.reset_timeout_ms,
            "half_open_probe": state.config.circuit_breaker.half_open_probe
        },
        "health_monitoring": {
            "enabled": state.chains().any(|(_, runtime)| runtime.health_enabled())
        }
    });

    (StatusCode::OK, Json(response))
}

/// Prometheus metrics endpoint
#[instrument(skip(_state))]
pub async fn metrics_handler(State(_state): State<ProxyState>) -> Response {
    let output = "# Metrics endpoint placeholder\n# TODO: Implement actual metrics collection\n";

    Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "text/plain; version=0.0.4")
        .body(output.into())
        .unwrap()
}
