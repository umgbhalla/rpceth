use axum::{Router, routing::get};
use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};
use opentelemetry::{KeyValue, global, trace::TracerProvider as _};
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::{Resource, metrics::SdkMeterProvider, trace::SdkTracerProvider};
use proxy_core::ProxyConfigLoader;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() {
    let prometheus = install_metrics_exporter();
    let _tracer_provider = install_tracing();
    let _meter_provider = install_otel_metrics();

    let config = ProxyConfigLoader::from_path("config/proxy.yaml").expect("load proxy config");

    let app = proxy_server::build_router(config.clone()).merge(observability_routes(prometheus));

    // Start health metrics collection task
    let state_for_metrics = proxy_server::ProxyState::new(config);
    tokio::spawn(proxy_server::health_metrics_task(state_for_metrics));

    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000")
        .await
        .expect("failed to bind listener");

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .expect("server failed");

    // tracer and meter providers dropped here to flush remaining data
}

fn observability_routes(prometheus: PrometheusHandle) -> Router {
    Router::new()
        .route("/metrics", get(metrics_handler))
        .with_state(prometheus)
}

async fn metrics_handler(
    axum::extract::State(prometheus): axum::extract::State<PrometheusHandle>,
) -> String {
    prometheus.render()
}

fn install_metrics_exporter() -> PrometheusHandle {
    PrometheusBuilder::new()
        .install_recorder()
        .expect("install prometheus recorder")
}

fn install_tracing() -> SdkTracerProvider {
    let exporter = opentelemetry_otlp::SpanExporter::builder()
        .with_tonic()
        .with_endpoint("http://localhost:4317")
        .build()
        .expect("Failed to create OTLP exporter");

    let resource = Resource::builder_empty()
        .with_attributes([
            KeyValue::new("service.name", "proxy-server"),
            KeyValue::new("service.version", env!("CARGO_PKG_VERSION")),
            KeyValue::new(
                "deployment.environment",
                std::env::var("ENVIRONMENT").unwrap_or_else(|_| "development".to_string()),
            ),
            KeyValue::new("telemetry.sdk.name", "opentelemetry"),
            KeyValue::new("telemetry.sdk.language", "rust"),
            KeyValue::new("telemetry.sdk.version", "0.30.0"),
        ])
        .build();

    let provider = SdkTracerProvider::builder()
        .with_batch_exporter(exporter)
        .with_resource(resource)
        .build();

    let tracer = provider.tracer("proxy-server");
    let otel_layer = tracing_opentelemetry::layer().with_tracer(tracer);

    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::from_default_env())
        .with(tracing_subscriber::fmt::layer().json())
        .with(otel_layer)
        .init();

    let _ = global::set_tracer_provider(provider.clone());
    provider
}

fn install_otel_metrics() -> SdkMeterProvider {
    let exporter = opentelemetry_otlp::MetricExporter::builder()
        .with_tonic()
        .with_endpoint("http://localhost:4317")
        .build()
        .expect("Failed to create OTLP metrics exporter");

    let resource = Resource::builder_empty()
        .with_attributes([
            KeyValue::new("service.name", "proxy-server"),
            KeyValue::new("service.version", env!("CARGO_PKG_VERSION")),
            KeyValue::new(
                "deployment.environment",
                std::env::var("ENVIRONMENT").unwrap_or_else(|_| "development".to_string()),
            ),
            KeyValue::new("telemetry.sdk.name", "opentelemetry"),
            KeyValue::new("telemetry.sdk.language", "rust"),
            KeyValue::new("telemetry.sdk.version", "0.30.0"),
        ])
        .build();

    let provider = SdkMeterProvider::builder()
        .with_reader(
            opentelemetry_sdk::metrics::PeriodicReader::builder(exporter)
                .with_interval(std::time::Duration::from_secs(5))
                .build(),
        )
        .with_resource(resource)
        .build();

    let _ = global::set_meter_provider(provider.clone());
    provider
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
        tracing::info!("received SIGINT (Ctrl+C), initiating graceful shutdown");
    };

    #[cfg(unix)]
    let terminate = async {
        use tokio::signal::unix::{SignalKind, signal};
        signal(SignalKind::terminate())
            .expect("install SIGTERM handler")
            .recv()
            .await;
        tracing::info!("received SIGTERM, initiating graceful shutdown");
    };

    #[cfg(unix)]
    let reload = async {
        use tokio::signal::unix::{SignalKind, signal};
        signal(SignalKind::hangup())
            .expect("install SIGHUP handler")
            .recv()
            .await;
        tracing::info!("received SIGHUP, config reload requested (not implemented yet)");
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    #[cfg(not(unix))]
    let reload = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {
            tracing::info!("shutting down due to SIGINT");
        },
        _ = terminate => {
            tracing::info!("shutting down due to SIGTERM");
        },
        _ = reload => {
            tracing::warn!("config reload not yet implemented, ignoring SIGHUP");
            // In the future, this would trigger a config reload
            // For now, we just log and ignore the signal
        },
    };
}
