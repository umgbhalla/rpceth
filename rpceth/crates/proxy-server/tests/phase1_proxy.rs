use std::time::Duration;

use axum::body::Body;
use http_body_util::BodyExt;
use httpmock::prelude::*;
use hyper::{Request, StatusCode};
use proxy_core::{BalancerStrategy, ProviderConfig, ProxyConfig, config::CircuitBreakerConfig};
use proxy_server::build_router;
use serde_json::json;
use tower::ServiceExt;

fn sample_json_rpc_request() -> serde_json::Value {
    json!({
        "jsonrpc": "2.0",
        "method": "eth_blockNumber",
        "params": [],
        "id": 1
    })
}

fn proxy_config_for(url: &str, timeout_ms: u64) -> ProxyConfig {
    let provider = ProviderConfig {
        id: "example".into(),
        url: url.parse().unwrap(),
        base_weight: 100,
        max_connections: 16,
        timeout_ms,
        circuit_breaker: CircuitBreakerConfig::default(),
    };

    ProxyConfig::try_new(
        BalancerStrategy::WeightedRandom,
        timeout_ms,
        2,
        vec![provider],
    )
    .expect("valid config")
}

#[tokio::test]
async fn proxies_json_rpc_requests_to_upstream_and_returns_response() {
    let server = MockServer::start_async().await;

    let expected_response = json!({
        "jsonrpc": "2.0",
        "id": 1,
        "result": "0xabcdef"
    });

    let _mock = server
        .mock_async(|when, then| {
            when.method(POST)
                .path("/")
                .header("content-type", "application/json")
                .header_exists("x-xray-id")
                .json_body(sample_json_rpc_request());

            then.status(200)
                .header("content-type", "application/json")
                .json_body(expected_response.clone());
        })
        .await;

    let router = build_router(proxy_config_for(&server.url("/"), 3_000));

    let request_body = Body::from(sample_json_rpc_request().to_string());

    let response = router
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/")
                .header("content-type", "application/json")
                .body(request_body)
                .expect("failed to build request"),
        )
        .await
        .expect("router returned error");

    assert_eq!(response.status(), StatusCode::OK);

    let headers = response.headers();
    assert!(
        headers.contains_key("x-xray-id"),
        "response missing x-xray-id header"
    );

    let body_bytes = response
        .into_body()
        .collect()
        .await
        .expect("body to bytes")
        .to_bytes();
    let body_json: serde_json::Value =
        serde_json::from_slice(&body_bytes).expect("valid json response");

    assert_eq!(body_json, expected_response);
}

#[tokio::test]
async fn returns_json_rpc_error_when_upstream_times_out() {
    let server = MockServer::start_async().await;

    let _mock = server
        .mock_async(|when, then| {
            when.method(POST).path("/");

            then.status(200)
                .delay(Duration::from_secs(10))
                .header("content-type", "application/json")
                .json_body(json!({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": "0xdeadbeef"
                }));
        })
        .await;

    let router = build_router(proxy_config_for(&server.url("/"), 100));

    let request_body = Body::from(sample_json_rpc_request().to_string());

    let response = router
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/")
                .header("content-type", "application/json")
                .body(request_body)
                .expect("failed to build request"),
        )
        .await
        .expect("router returned error");

    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);

    let body_bytes = response
        .into_body()
        .collect()
        .await
        .expect("body to bytes")
        .to_bytes();
    let error_payload: serde_json::Value =
        serde_json::from_slice(&body_bytes).expect("valid json response");

    assert_eq!(error_payload["jsonrpc"], "2.0");
    assert_eq!(error_payload["id"], 1);
    assert_eq!(error_payload["error"]["code"], -32001);
    assert_eq!(
        error_payload["error"]["message"],
        "provider request timed out"
    );
}
