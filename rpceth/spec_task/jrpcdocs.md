If you're building a JSON-RPC proxy or server with Axum (e.g., for Ethereum RPC based on your project name "rpceth"), a strong crate for handling RPC logic with built-in support for generating documentation is `jsonrpsee`. It's modern, performant, and integrates well with Axum via its HTTP server capabilities or by mounting its handlers as routes.

### Why `jsonrpsee`?
- It provides a proc-macro-based API to define your RPC methods via traits, making it easy to structure your proxy-core logic.
- Built-in generation of OpenRPC specs (the JSON-RPC equivalent of OpenAPI), which you can expose via a dedicated Axum route (e.g., GET `/rpc-docs` returning JSON).
- Supports WebSockets, batching, subscriptions, and middleware (e.g., for proxying requests with reqwest, which you already depend on).
- Compatible with Tokio and Tower (you have both in your deps), so it layers nicely without conflicts.
- For the "integrated docs page," you can serve an interactive HTML playground using the generated OpenRPC spec. Embed or proxy the official OpenRPC Playground (https://playground.open-rpc.org/) and feed it your spec dynamically.

### Adding to Your Project
Add to your `proxy-core` Cargo.toml (since it seems to hold the core logic):
```toml
jsonrpsee = { version = "0.24", features = ["server", "proc-macros"] }  # Adjust version as needed; check crates.io for latest
```

If you need client-side proxying:
```toml
jsonrpsee = { version = "0.24", features = ["client", "proc-macros"] }
```

### Basic Integration Example
Assuming your proxy forwards Ethereum-like RPC calls, here's a minimal setup in `proxy-core`. Define your RPC interface:

```rust
use jsonrpsee::proc_macros::rpc;
use jsonrpsee::types::error::CallError;

// Define your RPC trait (methods like eth_getBlockByNumber, etc.)
#[rpc(server, namespace = "eth")]
pub trait EthereumRpc {
    #[method(name = "getBlockByNumber")]
    async fn get_block_by_number(&self, block: String, full: bool) -> Result<serde_json::Value, CallError>;
    // Add other methods as needed
}

// Implement it, proxying to upstream with reqwest
pub struct ProxyImpl {
    upstream: reqwest::Client,
    upstream_url: url::Url,
}

#[async_trait::async_trait]
impl EthereumRpcServer for ProxyImpl {
    async fn get_block_by_number(&self, block: String, full: bool) -> Result<serde_json::Value, CallError> {
        // Proxy logic: forward to upstream, handle errors, etc.
        let req = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_getBlockByNumber",
            "params": [block, full],
            "id": uuid::Uuid::new_v4().to_string(),
        });
        let resp = self.upstream.post(self.upstream_url.clone()).json(&req).send().await?;
        let json: serde_json::Value = resp.json().await?;
        Ok(json["result"].clone())  // Simplify; handle errors properly
    }
}
```

In `proxy-server`, set up Axum to handle the RPC endpoint and docs:

```rust
use axum::{Router, routing::post};
use jsonrpsee::server::{ServerBuilder, RpcModule};
use proxy_core::{EthereumRpcServer, ProxyImpl};
use tower::ServiceBuilder;
use tower_http::trace::TraceLayer;  // If you want tracing

async fn start_server() {
    let proxy = ProxyImpl {
        upstream: reqwest::Client::new(),
        upstream_url: url::Url::parse("https://mainnet.infura.io/v3/YOUR_KEY").unwrap(),  // Example
    };

    // Build JSON-RPC module from your impl
    let mut module = RpcModule::new(());
    module.register_trait(EthereumRpcServer::into_rpc(proxy)).unwrap();

    // Generate OpenRPC docs
    let rpc_docs = module.generate_doc();  // This is your OpenRPC JSON spec

    // Axum router: mount RPC at / and docs at /docs
    let app = Router::new()
        .route("/", post(|req| async move { /* Handle JSON-RPC requests via jsonrpsee */ }))
        // Actually, to integrate: use jsonrpsee's hyper server and wrap in axum's from_fn or similar
        // For full integration, build jsonrpsee server and extract its handler
        .route("/docs", axum::routing::get(move || async { serde_json::to_string(&rpc_docs).unwrap() }))
        .layer(ServiceBuilder::new().layer(TraceLayer::new_for_http()));

    // Bind and serve
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
```

For the full RPC handler integration: Jsonrpsee's `ServerBuilder` produces a Hyper service, which you can mount in Axum using `axum::service::from_service` or by nesting routers. Check the jsonrpsee docs for "axum integration" examples—it's straightforward.

### Serving the Interactive Docs Page
- Expose the OpenRPC JSON at `/rpc-docs`.
- Create a static HTML route in Axum (e.g., `/docs`) that embeds an iframe or JS to load https://playground.open-rpc.org/?uiSchema[appBar][ui:splitView]=true&url=YOUR_SERVER/rpc-docs.
- Use `tower-http` to serve static files if needed (add to deps: `tower-http = { version = "0.5", features = ["fs"] }`).

This keeps docs integrated and auto-generated from your code. If your RPC is purely a passthrough proxy without custom methods, you can still generate a spec based on standard Ethereum methods (hardcode or load from a YAML/JSON schema).

If this isn't what you meant (e.g., if you want something else like auto-gen Markdown docs), provide more details on your setup!
