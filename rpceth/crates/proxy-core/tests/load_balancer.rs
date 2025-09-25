use std::time::Duration;

use proxy_core::{
    BalancerStrategy, LoadBalancer, ProviderHandle, ProviderId, config::CircuitBreakerConfig,
};
use tokio::test;
use url::Url;

fn provider(id: &str, url: &str, weight: u16) -> ProviderHandle {
    ProviderHandle {
        id: ProviderId::from(id),
        url: Url::parse(url).unwrap(),
        base_weight: weight,
        max_connections: 32,
        timeout: Duration::from_secs(5),
        circuit_breaker: CircuitBreakerConfig::default(),
    }
}

#[test]
async fn round_robin_cycles_chainlist_sample() {
    let providers = vec![
        provider("eth_llamarpc", "https://eth.llamarpc.com", 300),
        provider("cloudflare_eth", "https://cloudflare-eth.com", 300),
        provider(
            "blastapi_eth",
            "https://eth-mainnet.public.blastapi.io",
            300,
        ),
    ];

    let balancer = LoadBalancer::new(BalancerStrategy::RoundRobin, providers, None);

    let mut seen = Vec::new();
    for _ in 0..6 {
        seen.push(balancer.select_any().await.unwrap().id.0);
    }

    assert_eq!(
        seen,
        vec![
            "eth_llamarpc",
            "cloudflare_eth",
            "blastapi_eth",
            "eth_llamarpc",
            "cloudflare_eth",
            "blastapi_eth",
        ]
    );
}

#[test]
async fn weighted_random_prefers_high_weight_chainlist_sample() {
    let providers = vec![
        provider("eth_llamarpc", "https://eth.llamarpc.com", 900),
        provider("cloudflare_eth", "https://cloudflare-eth.com", 100),
    ];

    let balancer = LoadBalancer::new(BalancerStrategy::WeightedRandom, providers, None);

    let mut counts = std::collections::HashMap::new();
    for _ in 0..100 {
        let selected = balancer.select_any().await.unwrap();
        *counts.entry(selected.id.0).or_insert(0usize) += 1;
    }

    let llama = counts.get("eth_llamarpc").copied().unwrap_or_default();
    let cloudflare = counts.get("cloudflare_eth").copied().unwrap_or_default();

    assert!(
        llama > cloudflare,
        "expected llama RPC to be chosen more often than cloudflare"
    );
}
