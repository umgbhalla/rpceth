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
    for provider in &state.config.providers {
        let provider_id = &provider.id;
        let is_available = state.circuit_breaker.is_available(provider_id);

        provider_statuses.insert(
            provider_id.0.clone(),
            json!({
                "available": is_available,
                "url": provider.url,
                "timeout_ms": provider.timeout().as_millis(),
                "weight": provider.base_weight
            }),
        );

        if !is_available {
            ready = false;
            issues.push(format!("Provider {} is not available", provider_id.0));
        }
    }

    // Check if we have at least one available provider
    let available_providers = provider_statuses
        .values()
        .filter(|status| status["available"].as_bool().unwrap_or(false))
        .count();

    if available_providers == 0 {
        ready = false;
        issues.push("No providers are available".to_string());
    }

    let status_code = if ready {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    let response = json!({
        "status": if ready { "ready" } else { "not_ready" },
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "available_providers": available_providers,
        "total_providers": provider_statuses.len(),
        "providers": provider_statuses,
        "issues": issues
    });

    (status_code, Json(response))
}

/// Detailed provider status including health metrics if available
#[instrument(skip(state))]
async fn providers_handler(State(state): State<ProxyState>) -> impl IntoResponse {
    info!("provider status requested");

    let mut providers_info = Vec::new();

    for provider in &state.config.providers {
        let provider_id = &provider.id;
        let is_available = state.circuit_breaker.is_available(provider_id);

        // Get health information if health service is available
        let health_info = if let Some(ref _health_service) = state.health_service {
            // Try to get health metrics (this would need to be implemented in HealthService)
            json!({
                "health_check_enabled": true,
                "last_check": "N/A", // Would need to be implemented
                "success_rate": "N/A", // Would need to be implemented
                "avg_latency_ms": "N/A" // Would need to be implemented
            })
        } else {
            json!({
                "health_check_enabled": false
            })
        };

        providers_info.push(json!({
            "id": provider_id.0,
            "url": provider.url,
            "weight": provider.base_weight,
            "timeout_ms": provider.timeout().as_millis(),
            "available": is_available,
            "health": health_info
        }));
    }

    let response = json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "total_providers": providers_info.len(),
        "strategy": format!("{:?}", state.config.strategy),
        "providers": providers_info
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
            "enabled": state.health_service.is_some()
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
