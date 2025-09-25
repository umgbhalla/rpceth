use std::collections::HashMap;
use std::time::Duration;

use proxy_core::{
    BalancerStrategy, LoadBalancer, MethodRegistry, ProviderConfig, ProviderHandle, ProviderId,
    ProxyConfigLoader, ToleranceLevel,
};

fn sample_config_yaml() -> &'static str {
    r#"
strategy: weighted_random
default_timeout_ms: 5000
max_retries: 3
default_tolerance: Balanced
methods:
  default:
    timeout_ms: 5000
    weight_multiplier: 1.0
    max_retries: 3
    backoff:
      min_ms: 100
      max_ms: 800
      jitter: 0.2
  groups:
    read:
      tolerance: Relaxed
      timeout_ms: 4000
      weight_multiplier: 1.2
      max_retries: 2
      backoff:
        min_ms: 50
        max_ms: 400
        jitter: 0.1
    write:
      tolerance: Strict
      timeout_ms: 7000
      weight_multiplier: 0.8
      max_retries: 4
  overrides:
    - pattern: "eth_get*"
      group: read
    - pattern: "eth_sendRawTransaction"
      group: write
      weight_multiplier: 1.5
      backoff:
        min_ms: 150
        max_ms: 1000
        jitter: 0.3
      provider_weights:
        alchemy: 900
        infura: 300
providers:
  - id: alchemy
    url: https://eth-mainnet.g.alchemy.com/v2/demo
    base_weight: 400
    max_connections: 10
    timeout_ms: 4500
  - id: infura
    url: https://mainnet.infura.io/v3/demo
    base_weight: 300
    max_connections: 10
    timeout_ms: 5500
"#
}

#[test]
fn method_registry_resolves_overrides() {
    let config = ProxyConfigLoader::load_from_str(sample_config_yaml()).expect("parse config");
    let registry = MethodRegistry::new(&config).expect("build registry");

    let read_policy = registry.resolve(Some("eth_getBalance"));
    assert_eq!(read_policy.tolerance, ToleranceLevel::Relaxed);
    assert_eq!(read_policy.timeout, Duration::from_millis(4000));
    assert_eq!(read_policy.max_retries, 2);
    assert!((read_policy.weight_multiplier - 1.2).abs() < f64::EPSILON);
    assert!(!read_policy.has_provider_override(&ProviderId::from("alchemy")));

    let write_policy = registry.resolve(Some("eth_sendRawTransaction"));
    assert_eq!(write_policy.tolerance, ToleranceLevel::Strict);
    assert_eq!(write_policy.timeout, Duration::from_millis(7000));
    assert_eq!(write_policy.max_retries, 4);
    assert!((write_policy.weight_multiplier - 1.5).abs() < f64::EPSILON);
    assert_eq!(
        write_policy.provider_weight(&ProviderId::from("alchemy")),
        Some(900.0)
    );
    assert_eq!(
        write_policy.provider_weight(&ProviderId::from("infura")),
        Some(300.0)
    );

    let default_policy = registry.resolve(Some("net_version"));
    assert_eq!(default_policy.tolerance, ToleranceLevel::Balanced);
    assert_eq!(default_policy.timeout, Duration::from_millis(5000));
    assert_eq!(default_policy.max_retries, 3);
    assert!((default_policy.weight_multiplier - 1.0).abs() < f64::EPSILON);
    let backoff = default_policy.backoff.as_ref().expect("default backoff");
    assert_eq!(backoff.min.as_millis(), 100);
    assert_eq!(backoff.max.as_millis(), 800);
    assert!((backoff.jitter - 0.2).abs() < f64::EPSILON);
}

#[tokio::test]
async fn load_balancer_respects_method_provider_overrides() {
    let config = ProxyConfigLoader::load_from_str(sample_config_yaml()).expect("parse config");
    let registry = MethodRegistry::new(&config).expect("build registry");
    let write_policy = registry.resolve(Some("eth_sendRawTransaction"));

    let providers: Vec<ProviderHandle> = config
        .providers
        .clone()
        .into_iter()
        .map(ProviderConfig::into_handle)
        .collect();

    let balancer = LoadBalancer::new(BalancerStrategy::WeightedRandom, providers, None);

    let mut counts: HashMap<ProviderId, usize> = HashMap::new();
    for _ in 0..100 {
        let provider = balancer
            .select(&Default::default(), Some(&write_policy))
            .await
            .expect("provider available");
        *counts.entry(provider.id.clone()).or_insert(0) += 1;
    }

    let alchemy_count = counts
        .get(&ProviderId::from("alchemy"))
        .copied()
        .unwrap_or(0);
    let infura_count = counts
        .get(&ProviderId::from("infura"))
        .copied()
        .unwrap_or(0);

    assert!(
        alchemy_count > infura_count,
        "override should favor alchemy"
    );
}

#[test]
fn override_picks_custom_backoff() {
    let config = ProxyConfigLoader::load_from_str(sample_config_yaml()).expect("parse config");
    let registry = MethodRegistry::new(&config).expect("build registry");

    let policy = registry.resolve(Some("eth_sendRawTransaction"));
    let backoff = policy.backoff.expect("override backoff");

    assert_eq!(backoff.min.as_millis(), 150);
    assert_eq!(backoff.max.as_millis(), 1000);
    assert!((backoff.jitter - 0.3).abs() < f64::EPSILON);

    let read_policy = registry.resolve(Some("eth_getBalance"));
    let read_backoff = read_policy.backoff.expect("read group backoff");
    assert_eq!(read_backoff.min.as_millis(), 50);
    assert_eq!(read_backoff.max.as_millis(), 400);
    assert!((read_backoff.jitter - 0.1).abs() < f64::EPSILON);
}
