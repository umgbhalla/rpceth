use proxy_core::ProxyConfigLoader;

#[tokio::main]
async fn main() {
    let config = ProxyConfigLoader::from_path("config/proxy.yaml").expect("load proxy config");

    let app = proxy_server::build_router(config);

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .expect("failed to bind listener");

    axum::serve(listener, app).await.expect("server failed");
}
