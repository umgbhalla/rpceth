use axum::{Router, routing::get};
use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};
use opentelemetry::{KeyValue, global};
use opentelemetry_otlp::{WithExportConfig, new_exporter, new_pipeline};
use opentelemetry_sdk::{Resource, runtime::Tokio, trace as sdktrace};
use proxy_core::ProxyConfigLoader;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() {
    let prometheus = install_metrics_exporter();
    let _tracer_guard = install_tracing();

    let config = ProxyConfigLoader::from_path("config/proxy.yaml").expect("load proxy config");

    let app = proxy_server::build_router(config).merge(observability_routes(prometheus));

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .expect("failed to bind listener");

    axum::serve(listener, app).await.expect("server failed");

    // tracer guard dropped here to flush remaining spans
}

fn observability_routes(prometheus: PrometheusHandle) -> Router {
    Router::new().route("/metrics", get(|| async move { prometheus.render() }))
}

fn install_metrics_exporter() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("install prometheus recorder")
}

fn install_tracing() -> opentelemetry::sdk::trace::TracerProviderGuard {
    let exporter = new_exporter()
        .tonic()
        .with_env()
        .build_exporter()
        .expect("create otlp exporter");

    let tracer = new_pipeline()
        .tracing()
        .with_trace_config(
            sdktrace::Config::default().with_resource(Resource::new(vec![KeyValue::new(
                "service.name",
                "proxy-server",
            )])),
        )
        .with_exporter(exporter)
        .install_batch(Tokio)
        .expect("install otlp tracer");

    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::from_default_env())
        .with(tracing_subscriber::fmt::layer().json())
        .with(otel_layer)
        .init();

    global::tracer_provider().unwrap()
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        use tokio::signal::unix::{SignalKind, signal};
        signal(SignalKind::terminate())
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
