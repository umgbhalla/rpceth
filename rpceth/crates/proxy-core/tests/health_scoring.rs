use std::time::Duration;

use proxy_core::{
    BalancerStrategy, LoadBalancer, ProviderHandle, ProviderId,
    config::CircuitBreakerConfig,
    health::{FailureReason, HealthService, ProbeFailureKind, ProbeSuccess, ToleranceLevel},
};
use url::Url;

fn provider(id: &str, weight: u16) -> ProviderHandle {
    ProviderHandle {
        id: ProviderId::from(id),
        url: Url::parse("https://example.com").unwrap(),
        base_weight: weight,
        max_connections: 10,
        timeout: Duration::from_millis(500),
        circuit_breaker: CircuitBreakerConfig::default(),
    }
}

#[tokio::test]
async fn health_service_updates_scores_on_success() {
    struct SuccessProbe;

    #[async_trait::async_trait]
    impl proxy_core::health::HealthProbe for SuccessProbe {
        async fn probe(&self, provider: &ProviderHandle) -> Result<ProbeSuccess, ProbeFailureKind> {
            Ok(ProbeSuccess {
                provider: provider.id.clone(),
                latency: Duration::from_millis(150),
                block_number: 100,
                chain_id: 1,
                method_support_score: 1.0,
            })
        }
    }

    let service = HealthService::new(
        vec![provider("eth_llamarpc", 900)],
        ToleranceLevel::Balanced,
        Duration::from_millis(10),
        std::sync::Arc::new(SuccessProbe),
    );
    let service = std::sync::Arc::new(service);

    let spawned = std::sync::Arc::clone(&service);
    tokio::spawn(async move {
        spawned.spawn().await;
    });

    tokio::time::sleep(Duration::from_millis(50)).await;

    let snapshots = service.snapshots();
    assert_eq!(snapshots.len(), 1);
    let snapshot = &snapshots[0];
    assert_eq!(snapshot.provider.0, "eth_llamarpc");
    assert!(snapshot.score > 0.5);
    assert_eq!(snapshot.latest_block, Some(100));
    assert_eq!(snapshot.chain_id, Some(1));
}

#[tokio::test]
async fn load_balancer_respects_health_scores() {
    use std::collections::HashSet;
    use std::sync::Arc;

    struct ToggleProbe;

    #[async_trait::async_trait]
    impl proxy_core::health::HealthProbe for ToggleProbe {
        async fn probe(&self, provider: &ProviderHandle) -> Result<ProbeSuccess, ProbeFailureKind> {
            if provider.id.0 == "healthy" {
                Ok(ProbeSuccess {
                    provider: provider.id.clone(),
                    latency: Duration::from_millis(50),
                    block_number: 200,
                    chain_id: 1,
                    method_support_score: 1.0,
                })
            } else {
                Err(ProbeFailureKind {
                    provider: provider.id.clone(),
                    latency: Some(Duration::from_secs(1)),
                    reason: FailureReason::Timeout,
                })
            }
        }
    }

    let providers = vec![provider("healthy", 800), provider("unhealthy", 800)];

    let health_service = HealthService::new(
        providers.clone(),
        ToleranceLevel::Strict,
        Duration::from_millis(10),
        Arc::new(ToggleProbe),
    );
    let health_service = Arc::new(health_service);
    let spawned = Arc::clone(&health_service);
    tokio::spawn(async move {
        spawned.spawn().await;
    });

    tokio::time::sleep(Duration::from_millis(100)).await;

    let balancer = LoadBalancer::new(
        BalancerStrategy::WeightedRandom,
        providers,
        Some(Arc::clone(&health_service)),
    );

    let mut seen = HashSet::new();
    for _ in 0..10 {
        if let Some(provider) = balancer.select(&HashSet::new(), None).await {
            seen.insert(provider.id.0);
        }
    }

    assert!(seen.contains("healthy"));
    assert!(!seen.contains("unhealthy"));
}
