use std::net::SocketAddr;

use axum::{Router, routing::get};
use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};
use opentelemetry::sdk::trace as sdktrace;
use opentelemetry::{KeyValue, global};
use opentelemetry_otlp::WithExportConfig;
use proxy_core::ProxyConfigLoader;
use tokio::signal;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

#[tokio::main]
async fn main() {
    let prometheus = install_metrics_exporter();
    install_tracing();

    let config = ProxyConfigLoader::from_path("config/proxy.yaml").expect("load proxy config");

    let app = proxy_server::build_router(config).merge(observability_routes(prometheus));

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .expect("failed to bind listener");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .expect("server failed");

    global::shutdown_tracer_provider();
}

fn observability_routes(prometheus: PrometheusHandle) -> Router {
    Router::new().route("/metrics", get(|| async move { prometheus.render() }))
}

fn install_metrics_exporter() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("install prometheus recorder")
}

fn install_tracing() {
    let exporter = opentelemetry_otlp::new_exporter()
        .tonic()
        .with_env()
        .build_exporter()
        .expect("create otlp exporter");

    let provider = sdktrace::TracerProvider::builder()
        .with_batch_exporter(exporter, opentelemetry::runtime::Tokio)
        .with_config(
            sdktrace::Config::default().with_resource(opentelemetry::sdk::Resource::new(vec![
                KeyValue::new("service.name", "proxy-server"),
            ])),
        )
        .build();

    let tracer = provider.tracer("proxy-server");

    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::from_default_env())
        .with(tracing_subscriber::fmt::layer().json())
        .with(otel_layer)
        .init();

    global::set_tracer_provider(provider);
}

async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("install SIGTERM handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    };
}
