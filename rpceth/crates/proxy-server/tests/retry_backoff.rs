use axum::body::Body;
use http::StatusCode;
use http_body_util::BodyExt;
use httpmock::prelude::*;
use proxy_core::{ProxyConfig, ProxyConfigLoader};
use proxy_server::build_router;
use tower::ServiceExt;

fn config_yaml(entries: &[(&str, u16)]) -> String {
    let mut providers = String::new();
    for (name, timeout) in entries {
        providers.push_str(&format!(
            "  - id: {name}\n    url: PLACEHOLDER_{name}\n    timeout_ms: {timeout}\n"
        ));
    }

    format!(
        r#"
strategy: round_robin
default_timeout_ms: 500
max_retries: 3
default_tolerance: Balanced
methods:
  default:
    timeout_ms: 500
    max_retries: 3
    backoff:
      min_ms: 10
      max_ms: 20
      jitter: 0.0
providers:
{providers}"#
    )
}

fn build_config(map: &[(&str, String, u16)]) -> ProxyConfig {
    let template = config_yaml(
        &map.iter()
            .map(|(id, _, timeout)| (*id, *timeout))
            .collect::<Vec<_>>(),
    );

    let mut patched = template.clone();
    for (id, url, _) in map {
        patched = patched.replace(&format!("PLACEHOLDER_{id}"), url);
    }

    ProxyConfigLoader::load_from_str(&patched).expect("config parses")
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
async fn rotates_providers_until_success() {
    let server = MockServer::start_async().await;

    let fail_one = server
        .mock_async(|when, then| {
            when.method(POST).path("/fail-one");
            then.status(500)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": "failure one"},
                    "id": 1
                }));
        })
        .await;

    let fail_two = server
        .mock_async(|when, then| {
            when.method(POST).path("/fail-two");
            then.status(502)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": "failure two"},
                    "id": 1
                }));
        })
        .await;

    let succeed = server
        .mock_async(|when, then| {
            when.method(POST).path("/succeed");
            then.status(200)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "result": "0x42",
                    "id": 1
                }));
        })
        .await;

    let router = build_router(build_config(&[
        ("fail_one", server.url("/fail-one"), 200),
        ("fail_two", server.url("/fail-two"), 200),
        ("succeed", server.url("/succeed"), 200),
    ]));

    let request = http::Request::builder()
        .method("POST")
        .uri("/")
        .header("content-type", "application/json")
        .body(sample_body())
        .unwrap();

    let response = router.oneshot(request).await.expect("router call");
    assert_eq!(response.status(), StatusCode::OK);

    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    let payload: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(payload["result"], "0x42");

    assert_eq!(fail_one.hits(), 1, "first provider should be tried once");
    assert_eq!(fail_two.hits(), 1, "second provider should be tried once");
    assert_eq!(
        succeed.hits(),
        1,
        "success provider should be used on final attempt"
    );
}

#[tokio::test]
async fn soft_error_stops_retrying() {
    let server = MockServer::start_async().await;

    let soft = server
        .mock_async(|when, then| {
            when.method(POST).path("/soft");
            then.status(400)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "error": {"code": -32602, "message": "invalid params"},
                    "id": 1
                }));
        })
        .await;

    let healthy = server
        .mock_async(|when, then| {
            when.method(POST).path("/healthy");
            then.status(200)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "result": "0x1",
                    "id": 1
                }));
        })
        .await;

    let router = build_router(build_config(&[
        ("soft", server.url("/soft"), 200),
        ("healthy", server.url("/healthy"), 200),
    ]));

    let request = http::Request::builder()
        .method("POST")
        .uri("/")
        .header("content-type", "application/json")
        .body(sample_body())
        .unwrap();

    let response = router.oneshot(request).await.expect("router call");
    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let payload: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(
        payload["error"]["message"],
        "provider returned status 400 Bad Request"
    );

    assert_eq!(soft.hits(), 1, "soft failure should be observed once");
    assert_eq!(healthy.hits(), 0, "soft failure should not trigger retries");
}

#[tokio::test]
async fn stops_after_max_attempts_when_all_fail() {
    let server = MockServer::start_async().await;

    let fail_one = server
        .mock_async(|when, then| {
            when.method(POST).path("/fail-one");
            then.status(504)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": "timeout"},
                    "id": 1
                }));
        })
        .await;

    let fail_two = server
        .mock_async(|when, then| {
            when.method(POST).path("/fail-two");
            then.status(500)
                .header("content-type", "application/json")
                .json_body(serde_json::json!({
                    "jsonrpc": "2.0",
                    "error": {"code": -32000, "message": "boom"},
                    "id": 1
                }));
        })
        .await;

    let router = build_router(build_config(&[
        ("fail_one", server.url("/fail-one"), 200),
        ("fail_two", server.url("/fail-two"), 200),
    ]));

    let request = http::Request::builder()
        .method("POST")
        .uri("/")
        .header("content-type", "application/json")
        .body(sample_body())
        .unwrap();

    let response = router.oneshot(request).await.expect("router call");
    assert_eq!(response.status(), StatusCode::BAD_GATEWAY);

    let body = response.into_body().collect().await.unwrap().to_bytes();
    let payload: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(
        payload["error"]["message"],
        "provider returned status 500 Internal Server Error"
    );

    assert_eq!(
        fail_one.hits(),
        1,
        "first provider should be attempted once"
    );
    assert_eq!(
        fail_two.hits(),
        1,
        "second provider should be attempted once"
    );
}
