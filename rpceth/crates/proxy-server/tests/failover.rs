use std::time::Duration;

use axum::body::Body;
use http::StatusCode;
use http_body_util::BodyExt;
use httpmock::prelude::*;
use proxy_core::{BalancerStrategy, ProviderConfig, ProxyConfig, config::CircuitBreakerConfig};
use proxy_server::build_router;
use serde_json::json;
use tower::ServiceExt;

fn provider(url: &str, id: &str) -> ProviderConfig {
    ProviderConfig {
        id: id.into(),
        url: url.parse().unwrap(),
        base_weight: 100,
        max_connections: 16,
        timeout_ms: 1_000,
        circuit_breaker: CircuitBreakerConfig::default(),
    }
}

fn build_config(primary: &str, fallback: &str) -> ProxyConfig {
    ProxyConfig::try_new(
        BalancerStrategy::RoundRobin,
        1_000,
        3,
        vec![provider(primary, "primary"), provider(fallback, "fallback")],
    )
    .expect("valid config")
}

fn sample_body() -> Body {
    Body::from(
        json!({
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 99
        })
        .to_string(),
    )
}

#[tokio::test]
async fn falls_back_to_next_provider_on_timeout() {
    let server = MockServer::start_async().await;

    let _slow_primary = server
        .mock_async(|when, then| {
            when.method(POST).path("/primary");
            then.status(200)
                .delay(Duration::from_secs(5))
                .header("content-type", "application/json")
                .json_body(json!({
                    "jsonrpc": "2.0",
                    "id": 99,
                    "result": "0xsleepy"
                }));
        })
        .await;

    let _fast_fallback = server
        .mock_async(|when, then| {
            when.method(POST).path("/fallback");
            then.status(200)
                .header("content-type", "application/json")
                .json_body(json!({
                    "jsonrpc": "2.0",
                    "id": 99,
                    "result": "0xawake"
                }));
        })
        .await;

    let router = build_router(build_config(
        &server.url("/primary"),
        &server.url("/fallback"),
    ));

    let response = router
        .oneshot(
            http::Request::builder()
                .method("POST")
                .uri("/")
                .header("content-type", "application/json")
                .body(sample_body())
                .unwrap(),
        )
        .await
        .expect("router call");

    assert_eq!(response.status(), StatusCode::OK);

    let body_bytes = response.into_body().collect().await.unwrap().to_bytes();
    let payload: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap();
    assert_eq!(payload["result"], "0xawake");
}
