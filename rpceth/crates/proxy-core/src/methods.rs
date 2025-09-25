use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use globset::{Glob, GlobSet, GlobSetBuilder};

use crate::config::{
    BackoffConfig, MethodDefaults, MethodGroupConfig, MethodOverrideConfig, ProxyConfig,
};
use crate::health::ToleranceLevel;
use crate::provider::ProviderId;

#[derive(Debug, Clone)]
pub struct MethodPolicy {
    pub tolerance: ToleranceLevel,
    pub timeout: Duration,
    pub weight_multiplier: f64,
    pub max_retries: usize,
    pub provider_weights: HashMap<ProviderId, f64>,
    pub backoff: Option<ResolvedBackoff>,
}

#[derive(Debug, Clone)]
pub struct ResolvedBackoff {
    pub min: Duration,
    pub max: Duration,
    pub jitter: f64,
}

impl MethodPolicy {
    pub fn provider_weight(&self, provider: &ProviderId) -> Option<f64> {
        self.provider_weights.get(provider).copied()
    }

    pub fn has_provider_override(&self, provider: &ProviderId) -> bool {
        self.provider_weights.contains_key(provider)
    }
}

#[derive(thiserror::Error, Debug)]
pub enum MethodRegistryError {
    #[error("invalid glob pattern `{pattern}`: {source}")]
    InvalidGlob {
        pattern: String,
        #[source]
        source: globset::Error,
    },
}

#[derive(Clone)]
pub struct MethodRegistry {
    default_timeout: Duration,
    default_tolerance: ToleranceLevel,
    default_max_retries: usize,
    default_weight_multiplier: f64,
    default_provider_weights: HashMap<ProviderId, f64>,
    default_backoff: Option<ResolvedBackoff>,
    groups: HashMap<String, MethodPolicy>,
    override_set: Arc<OverrideSet>,
}

#[derive(Debug)]
struct OverrideEntry {
    pattern: String,
    policy: MethodPolicy,
}

#[derive(Debug)]
struct OverrideSet {
    globset: GlobSet,
    entries: Vec<OverrideEntry>,
}

impl OverrideSet {
    fn new(overrides: &[ResolvedOverride]) -> Result<Self, MethodRegistryError> {
        let mut builder = GlobSetBuilder::new();
        for resolved in overrides {
            builder.add(Glob::new(&resolved.pattern).map_err(|source| {
                MethodRegistryError::InvalidGlob {
                    pattern: resolved.pattern.clone(),
                    source,
                }
            })?);
        }
        let globset = builder
            .build()
            .map_err(|source| MethodRegistryError::InvalidGlob {
                pattern: "<set>".to_string(),
                source,
            })?;

        let entries = overrides
            .iter()
            .map(|resolved| OverrideEntry {
                pattern: resolved.pattern.clone(),
                policy: resolved.policy.clone(),
            })
            .collect();

        Ok(Self { globset, entries })
    }

    fn matches(&self, method: &str) -> Option<&MethodPolicy> {
        if self.entries.is_empty() {
            return None;
        }

        let matches = self.globset.matches(method);
        matches
            .into_iter()
            .last()
            .and_then(|idx| self.entries.get(idx))
            .map(|entry| &entry.policy)
    }
}

#[derive(Debug)]
struct ResolvedOverride {
    pattern: String,
    policy: MethodPolicy,
}

impl MethodRegistry {
    pub fn new(config: &ProxyConfig) -> Result<Self, MethodRegistryError> {
        let methods = &config.methods;
        let defaults = resolve_defaults(&methods.default, config);

        let groups = build_group_policies(&methods.groups, &defaults);

        let overrides = build_override_policies(&methods.overrides, &groups, &defaults);

        let override_set = Arc::new(OverrideSet::new(&overrides)?);

        Ok(Self {
            default_timeout: defaults.timeout,
            default_tolerance: defaults.tolerance,
            default_max_retries: defaults.max_retries,
            default_weight_multiplier: defaults.weight_multiplier,
            default_provider_weights: defaults.provider_weights.clone(),
            default_backoff: defaults.backoff.clone(),
            groups,
            override_set,
        })
    }

    pub fn resolve(&self, method: Option<&str>) -> MethodPolicy {
        let method = method.unwrap_or("*");
        if let Some(policy) = self.override_set.matches(method) {
            return policy.clone();
        }

        MethodPolicy {
            tolerance: self.default_tolerance,
            timeout: self.default_timeout,
            weight_multiplier: self.default_weight_multiplier,
            max_retries: self.default_max_retries,
            provider_weights: self.default_provider_weights.clone(),
            backoff: self.default_backoff.clone(),
        }
    }

    pub fn group_policy(&self, group: &str) -> Option<&MethodPolicy> {
        self.groups.get(group)
    }
}

fn build_group_policies(
    groups: &HashMap<String, MethodGroupConfig>,
    defaults: &ResolvedDefaults,
) -> HashMap<String, MethodPolicy> {
    groups
        .iter()
        .map(|(name, cfg)| {
            let timeout = cfg
                .timeout_ms
                .map(Duration::from_millis)
                .unwrap_or(defaults.timeout);
            let tolerance = cfg.tolerance.unwrap_or(defaults.tolerance);
            let max_retries = cfg
                .max_retries
                .map(|value| usize::from(value))
                .unwrap_or(defaults.max_retries);
            let multiplier = cfg.weight_multiplier.unwrap_or(defaults.weight_multiplier);
            let provider_weights =
                merge_provider_weights(&defaults.provider_weights, &cfg.provider_weights);
            let backoff = cfg
                .backoff
                .as_ref()
                .map(|cfg| resolve_backoff(cfg, defaults.backoff.as_ref()))
                .or_else(|| defaults.backoff.clone());

            let policy = MethodPolicy {
                tolerance,
                timeout,
                weight_multiplier: multiplier,
                max_retries,
                provider_weights,
                backoff,
            };

            (name.clone(), policy)
        })
        .collect()
}

fn build_override_policies(
    overrides: &[MethodOverrideConfig],
    groups: &HashMap<String, MethodPolicy>,
    defaults: &ResolvedDefaults,
) -> Vec<ResolvedOverride> {
    overrides
        .iter()
        .map(|cfg| {
            let base_policy = cfg
                .group
                .as_ref()
                .and_then(|group| groups.get(group))
                .cloned()
                .unwrap_or(MethodPolicy {
                    tolerance: defaults.tolerance,
                    timeout: defaults.timeout,
                    weight_multiplier: defaults.weight_multiplier,
                    max_retries: defaults.max_retries,
                    provider_weights: defaults.provider_weights.clone(),
                    backoff: defaults.backoff.clone(),
                });

            let timeout = cfg
                .timeout_ms
                .map(Duration::from_millis)
                .unwrap_or(base_policy.timeout);
            let tolerance = cfg.tolerance.unwrap_or(base_policy.tolerance);
            let max_retries = cfg
                .max_retries
                .map(|value| usize::from(value))
                .unwrap_or(base_policy.max_retries);
            let weight_multiplier = cfg
                .weight_multiplier
                .unwrap_or(base_policy.weight_multiplier);

            let provider_weights =
                merge_provider_weights(&base_policy.provider_weights, &cfg.provider_weights);
            let backoff = cfg
                .backoff
                .as_ref()
                .map(|cfg| resolve_backoff(cfg, base_policy.backoff.as_ref()))
                .or_else(|| base_policy.backoff.clone());

            ResolvedOverride {
                pattern: cfg.pattern.as_str().to_string(),
                policy: MethodPolicy {
                    tolerance,
                    timeout,
                    weight_multiplier,
                    max_retries,
                    provider_weights,
                    backoff,
                },
            }
        })
        .collect()
}

fn merge_provider_weights(
    base: &HashMap<ProviderId, f64>,
    overrides: &HashMap<ProviderId, u16>,
) -> HashMap<ProviderId, f64> {
    let mut merged = base.clone();
    for (provider, weight) in overrides {
        merged.insert(provider.clone(), f64::from(*weight));
    }
    merged
}

fn normalize_provider_weights(weights: &HashMap<ProviderId, u16>) -> HashMap<ProviderId, f64> {
    weights
        .iter()
        .map(|(provider, weight)| (provider.clone(), f64::from(*weight)))
        .collect()
}

struct ResolvedDefaults {
    timeout: Duration,
    tolerance: ToleranceLevel,
    weight_multiplier: f64,
    max_retries: usize,
    provider_weights: HashMap<ProviderId, f64>,
    backoff: Option<ResolvedBackoff>,
}

fn resolve_defaults(defaults: &MethodDefaults, config: &ProxyConfig) -> ResolvedDefaults {
    let timeout = defaults
        .timeout_ms
        .map(Duration::from_millis)
        .unwrap_or(Duration::from_millis(config.default_timeout_ms));
    let tolerance = defaults.tolerance.unwrap_or(ToleranceLevel::Balanced);
    let max_retries = usize::from(defaults.max_retries.unwrap_or(config.max_retries));
    let weight_multiplier = defaults.weight_multiplier.unwrap_or(1.0);
    let provider_weights = normalize_provider_weights(&defaults.provider_weights);
    let backoff = defaults
        .backoff
        .as_ref()
        .map(|cfg| resolve_backoff(cfg, None));

    ResolvedDefaults {
        timeout,
        tolerance,
        weight_multiplier,
        max_retries,
        provider_weights,
        backoff,
    }
}

fn resolve_backoff(config: &BackoffConfig, fall_back: Option<&ResolvedBackoff>) -> ResolvedBackoff {
    let base = fall_back.cloned().unwrap_or(ResolvedBackoff {
        min: Duration::from_millis(200),
        max: Duration::from_millis(2_000),
        jitter: 0.3,
    });

    let min = config.min_ms.map(Duration::from_millis).unwrap_or(base.min);
    let max = config.max_ms.map(Duration::from_millis).unwrap_or(base.max);
    let jitter = config.jitter.unwrap_or(base.jitter);

    ResolvedBackoff { min, max, jitter }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::ProxyConfigLoader;

    fn config_fixture() -> ProxyConfig {
        ProxyConfigLoader::load_from_str(
            r#"
strategy: weighted_random
default_timeout_ms: 5000
max_retries: 3
default_tolerance: Balanced
methods:
  default:
    timeout_ms: 6000
    weight_multiplier: 1.1
    max_retries: 4
  groups:
    read:
      tolerance: Relaxed
      timeout_ms: 4500
      weight_multiplier: 1.3
      max_retries: 2
    write:
      tolerance: Strict
      timeout_ms: 7000
      weight_multiplier: 0.9
      max_retries: 5
  overrides:
    - pattern: "eth_sendRawTransaction"
      group: write
      weight_multiplier: 1.4
    - pattern: "eth_get*"
      group: read
providers:
  - id: alchemy
    url: https://example.com/alchemy
    base_weight: 500
    max_connections: 10
    timeout_ms: 4000
        "#,
        )
        .unwrap()
    }

    #[test]
    fn registry_builds() {
        let config = config_fixture();
        MethodRegistry::new(&config).expect("registry");
    }
}
