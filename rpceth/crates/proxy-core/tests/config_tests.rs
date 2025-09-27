use std::collections::HashMap;

use proxy_core::config::{ProxyConfig, ProxyConfigLoader};
use proxy_core::provider::ProviderConfig;
use proxy_core::{BalancerStrategy, ChainConfig, ToleranceLevel};
use serde_yaml::{Mapping, Value};

fn base_provider(id: &str) -> ProviderConfig {
    let mut map = Mapping::new();
    map.insert(Value::from("id"), Value::from(id));
    map.insert(
        Value::from("url"),
        Value::from(format!("https://example.com/{id}")),
    );
    serde_yaml::from_value(Value::Mapping(map)).expect("provider config")
}

fn load_config(yaml: &str) -> ProxyConfig {
    ProxyConfigLoader::load_from_str(yaml).expect("config should load")
}

#[test]
fn config_without_chains_keeps_legacy_behavior() {
    let yaml = r#"
strategy: round_robin
auth:
  api_key: demo
providers:
  - id: primary
    url: https://example.com/primary
"#;

    let config = load_config(yaml);
    assert!(config.chains.is_empty());
    assert!(config.default_chain.is_none());
}

#[test]
fn config_with_chains_requires_default_chain() {
    let yaml = r#"
strategy: weighted_random
auth:
  api_key: demo
providers:
  - id: primary
    url: https://example.com/primary
chains:
  mainnet:
    providers: [primary]
    aliases: ["eth"]
default_chain: mainnet
"#;

    let config = load_config(yaml);
    assert_eq!(config.default_chain.as_deref(), Some("mainnet"));
    assert!(config.chains.contains_key("mainnet"));
}

#[test]
fn duplicate_aliases_across_chains_are_rejected() {
    let yaml = r#"
strategy: weighted_random
auth:
  api_key: demo
providers:
  - id: p1
    url: https://example.com/p1
  - id: p2
    url: https://example.com/p2
chains:
  chain_a:
    providers: [p1]
    aliases: ["shared"]
  chain_b:
    providers: [p2]
    aliases: ["shared"]
default_chain: chain_a
"#;

    let err = ProxyConfigLoader::load_from_str(yaml).expect_err("should fail");
    let message = format!("{err}");
    assert!(message.contains("alias `shared`"));
}

#[test]
fn unknown_provider_in_chain_fails_validation() {
    let yaml = r#"
strategy: weighted_random
auth:
  api_key: demo
providers:
  - id: p1
    url: https://example.com/p1
chains:
  mainnet:
    providers: [p1, missing]
    aliases: ["1"]
default_chain: mainnet
"#;

    let err = ProxyConfigLoader::load_from_str(yaml).expect_err("should fail");
    assert!(format!("{err}").contains("unknown provider"));
}

#[test]
fn chain_config_uses_override_tolerance() {
    let mut config = ProxyConfig {
        strategy: BalancerStrategy::WeightedRandom,
        default_timeout_ms: 5_000,
        max_retries: 3,
        default_tolerance: ToleranceLevel::Balanced,
        methods: proxy_core::config::MethodConfig::default(),
        circuit_breaker: proxy_core::config::CircuitBreakerConfig::default(),
        auth: proxy_core::config::AuthConfig {
            api_key: "demo".into(),
        },
        providers: vec![base_provider("p1"), base_provider("p2")],
        chains: HashMap::from([(
            "mainnet".to_string(),
            ChainConfig {
                providers: vec!["p1".into(), "p2".into()],
                aliases: vec!["1".into()],
                tolerance: Some(ToleranceLevel::Strict),
            },
        )]),
        default_chain: Some("mainnet".into()),
    };

    assert_eq!(
        config.chains["mainnet"].tolerance,
        Some(ToleranceLevel::Strict)
    );
}
