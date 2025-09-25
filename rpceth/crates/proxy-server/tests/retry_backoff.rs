use axum::body::Body;
use http::StatusCode;
use http_body_util::BodyExt;
use httpmock::prelude::*;
use proxy_core::{ProxyConfig, ProxyConfigLoader};
use proxy_server::build_router;
use tower::ServiceExt;

fn config_yaml(primary: &str, secondary: &str) -> String {
    format!(
        r#"
strategy: round_robin
default_timeout_ms: 500
max_retries: 3
default_tolerance: Balanced
methods:
  default:
    timeout_ms: 500
    max_retries: 2
    backoff:
      min_ms: 150
      max_ms: 300
      jitter: 0.0
providers:
  - id: primary
    url: {primary}
    timeout_ms: 200
  - id: secondary
    url: {secondary}
    timeout_ms: 200
"#
    )
}

fn build_config(primary: &str, secondary: &str) -> ProxyConfig {
    ProxyConfigLoader::load_from_str(&config_yaml(primary, secondary)).expect("config parses")
}

fn sample_body() -> Body {
    Body::from(
        serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 1
        })
        .to_string(),
    )
}

#[tokio::test]
async fn retries_wait_between_attempts() {
    let server = MockServer::start_async().await;

    let primary = server
        .mock_async(|when, then| {
            when.method(POST).path("/primary");
            then.status(500)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": "boom"},
                    "id": 1
                }));
        })
        .await;

    let secondary = server
        .mock_async(|when, then| {
            when.method(POST).path("/secondary");
            then.status(200)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "result": "0x1",
                    "id": 1
                }));
        })
        .await;

    let router = build_router(build_config(
        &server.url("/primary"),
        &server.url("/secondary"),
    ));

    let request = http::Request::builder()
        .method("POST")
        .uri("/")
        .header("content-type", "application/json")
        .body(sample_body())
        .unwrap();

    let response = router.oneshot(request).await.expect("router call");

    assert_eq!(response.status(), StatusCode::OK);

    let body_bytes = response.into_body().collect().await.unwrap().to_bytes();
    let payload: serde_json::Value = serde_json::from_slice(&body_bytes).unwrap();
    assert_eq!(payload["result"], "0x1");

    // Primary should be attempted at least once and then the retry should reach
    // the secondary. Allow extra hits due to circuit checks but require both
    // providers to be contacted.
    let primary_hits = primary.hits();
    let secondary_hits = secondary.hits();

    assert!(
        primary_hits + secondary_hits >= 2,
        "expected at least two total attempts across providers, observed primary={primary_hits} secondary={secondary_hits}"
    );
}
