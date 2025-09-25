use axum::body::Body;
use http::StatusCode;
use httpmock::prelude::*;
use proxy_core::{BalancerStrategy, ProviderConfig, ProxyConfig, config::CircuitBreakerConfig};
use proxy_server::build_router;
use serde_json::json;
use tower::ServiceExt;

fn provider(url: &str, id: &str, weight: u16) -> ProviderConfig {
    ProviderConfig {
        id: id.into(),
        url: url.parse().unwrap(),
        base_weight: weight,
        max_connections: 16,
        timeout_ms: 5_000,
        circuit_breaker: CircuitBreakerConfig::default(),
    }
}

fn config(high_weight: &str, low_weight: &str) -> ProxyConfig {
    ProxyConfig::try_new(
        BalancerStrategy::WeightedRandom,
        2_000,
        3,
        vec![
            provider(high_weight, "eth_llamarpc", 900),
            provider(low_weight, "cloudflare_eth", 100),
        ],
    )
    .expect("valid config")
}

fn sample_request() -> Body {
    Body::from(
        json!({
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 7
        })
        .to_string(),
    )
}

#[tokio::test]
async fn higher_weight_provider_receives_more_requests() {
    let server = MockServer::start_async().await;

    let high_mock = server
        .mock_async(move |when, then| {
            when.method(POST)
                .path("/eth_llamarpc")
                .header("content-type", "application/json")
                .header_exists("x-xray-id");

            then.status(200)
                .header("content-type", "application/json")
                .json_body(json!({
                    "jsonrpc": "2.0",
                    "id": 7,
                    "result": "0x42"
                }));
        })
        .await;

    let low_mock = server
        .mock_async(move |when, then| {
            when.method(POST)
                .path("/cloudflare_eth")
                .header("content-type", "application/json")
                .header_exists("x-xray-id");

            then.status(200)
                .header("content-type", "application/json")
                .json_body(json!({
                    "jsonrpc": "2.0",
                    "id": 7,
                    "result": "0x43"
                }));
        })
        .await;

    let router = build_router(config(
        &server.url("/eth_llamarpc"),
        &server.url("/cloudflare_eth"),
    ));

    for _ in 0..50 {
        let response = router
            .clone()
            .oneshot(
                http::Request::builder()
                    .method("POST")
                    .uri("/")
                    .header("content-type", "application/json")
                    .body(sample_request())
                    .unwrap(),
            )
            .await
            .expect("router call");

        assert_eq!(response.status(), StatusCode::OK);
    }

    let high = high_mock.hits_async().await;
    let low = low_mock.hits_async().await;

    assert!(
        high > low,
        "expected high-weight provider to be selected more frequently ({high} vs {low})"
    );
}
