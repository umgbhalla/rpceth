use std::collections::{HashMap, HashSet};
use std::{path::Path, time::Duration};

use serde::Deserialize;
use thiserror::Error;

use crate::health::ToleranceLevel;
use crate::provider::{ProviderConfig, ProviderId};

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum BalancerStrategy {
    RoundRobin,
    #[default]
    WeightedRandom,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(default)]
pub struct BackoffConfig {
    pub min_ms: Option<u64>,
    pub max_ms: Option<u64>,
    pub jitter: Option<f64>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(default)]
pub struct MethodDefaults {
    pub tolerance: Option<ToleranceLevel>,
    pub timeout_ms: Option<u64>,
    pub weight_multiplier: Option<f64>,
    pub max_retries: Option<u8>,
    pub backoff: Option<BackoffConfig>,
    pub provider_weights: HashMap<ProviderId, u16>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(default)]
pub struct MethodGroupConfig {
    pub tolerance: Option<ToleranceLevel>,
    pub timeout_ms: Option<u64>,
    pub weight_multiplier: Option<f64>,
    pub max_retries: Option<u8>,
    pub backoff: Option<BackoffConfig>,
    pub provider_weights: HashMap<ProviderId, u16>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(default)]
pub struct MethodOverrideConfig {
    pub pattern: String,
    pub group: Option<String>,
    pub tolerance: Option<ToleranceLevel>,
    pub timeout_ms: Option<u64>,
    pub weight_multiplier: Option<f64>,
    pub max_retries: Option<u8>,
    pub backoff: Option<BackoffConfig>,
    pub provider_weights: HashMap<ProviderId, u16>,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(default)]
pub struct MethodConfig {
    pub default: MethodDefaults,
    pub groups: HashMap<String, MethodGroupConfig>,
    pub overrides: Vec<MethodOverrideConfig>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct AuthConfig {
    pub api_key: String,
}


#[derive(Debug, Clone, Deserialize, Default)]
#[serde(default)]
pub struct CircuitBreakerConfig {
    pub failure_threshold: Option<u32>,
    pub reset_timeout_ms: Option<u64>,
    pub half_open_probe: Option<u32>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ProxyConfig {
    #[serde(default)]
    pub strategy: BalancerStrategy,
    #[serde(default = "default_timeout_ms")]
    pub default_timeout_ms: u64,
    #[serde(default = "default_max_retries")]
    pub max_retries: u8,
    #[serde(default = "default_tolerance_level")]
    pub default_tolerance: ToleranceLevel,
    #[serde(default)]
    pub methods: MethodConfig,
    #[serde(default)]
    pub circuit_breaker: CircuitBreakerConfig,
    pub auth: AuthConfig,
    pub providers: Vec<ProviderConfig>,
}

fn default_timeout_ms() -> u64 {
    5_000
}

fn default_max_retries() -> u8 {
    3
}

fn default_tolerance_level() -> ToleranceLevel {
    ToleranceLevel::Balanced
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("configuration file not found: {0}")]
    MissingFile(String),
    #[error("failed to read configuration: {0}")]
    ReadFailed(String),
    #[error("failed to deserialize configuration: {0}")]
    DeserializeFailed(String),
    #[error("configuration validation error: {0}")]
    Validation(String),
}

pub struct ProxyConfigLoader;

impl ProxyConfigLoader {
    pub fn from_path(path: impl AsRef<Path>) -> Result<ProxyConfig, ConfigError> {
        let path = path.as_ref();
        let body = std::fs::read_to_string(path)
            .map_err(|err| ConfigError::ReadFailed(err.to_string()))?;
        Self::load_from_str(&body)
    }

    pub fn load_from_str(body: &str) -> Result<ProxyConfig, ConfigError> {
        let config: ProxyConfig = serde_yaml::from_str(body)
            .map_err(|err| ConfigError::DeserializeFailed(err.to_string()))?;
        validate(&config)?;
        Ok(config)
    }
}

impl ProxyConfig {
    pub fn try_new(
        strategy: BalancerStrategy,
        default_timeout_ms: u64,
        max_retries: u8,
        providers: Vec<ProviderConfig>,
        auth: AuthConfig,
    ) -> Result<Self, ConfigError> {
        let config = Self {
            strategy,
            default_timeout_ms,
            max_retries,
            default_tolerance: default_tolerance_level(),
            methods: MethodConfig::default(),
            circuit_breaker: CircuitBreakerConfig::default(),
            auth,
            providers,
        };
        validate(&config)?;
        Ok(config)
    }

    pub fn default_timeout(&self) -> Duration {
        Duration::from_millis(self.default_timeout_ms)
    }

    pub fn max_retry_attempts(&self) -> usize {
        usize::from(self.max_retries.max(1))
    }
}

fn validate(config: &ProxyConfig) -> Result<(), ConfigError> {
    if config.default_timeout_ms == 0 {
        return Err(ConfigError::Validation(
            "default_timeout_ms must be greater than zero".into(),
        ));
    }

    if config.max_retries == 0 {
        return Err(ConfigError::Validation(
            "max_retries must be greater than zero".into(),
        ));
    }

    if config.auth.api_key.trim().is_empty() {
        return Err(ConfigError::Validation(
            "auth.api_key must be provided and not be empty".into(),
        ));
    }

    validate_circuit_breaker(&config.circuit_breaker)?;

    if config.providers.is_empty() {
        return Err(ConfigError::Validation(
            "at least one provider must be configured".into(),
        ));
    }

    let mut ids = HashSet::<ProviderId>::new();

    for provider in &config.providers {
        provider.validate()?;
        if !ids.insert(provider.id.clone()) {
            return Err(ConfigError::Validation(format!(
                "duplicate provider id `{}`",
                provider.id.0
            )));
        }
    }

    validate_methods(&config.methods)?;

    Ok(())
}

fn validate_circuit_breaker(config: &CircuitBreakerConfig) -> Result<(), ConfigError> {
    if let Some(threshold) = config.failure_threshold {
        if threshold == 0 {
            return Err(ConfigError::Validation(
                "circuit_breaker failure_threshold must be greater than zero".into(),
            ));
        }
    }

    if let Some(timeout) = config.reset_timeout_ms {
        if timeout == 0 {
            return Err(ConfigError::Validation(
                "circuit_breaker reset_timeout_ms must be greater than zero".into(),
            ));
        }
    }

    if let Some(probe) = config.half_open_probe {
        if probe == 0 {
            return Err(ConfigError::Validation(
                "circuit_breaker half_open_probe must be greater than zero".into(),
            ));
        }
    }

    Ok(())
}

fn validate_methods(methods: &MethodConfig) -> Result<(), ConfigError> {
    validate_backoff("default backoff", methods.default.backoff.as_ref())?;
    validate_timeout("default method timeout", methods.default.timeout_ms)?;
    validate_max_retries("default method max_retries", methods.default.max_retries)?;
    validate_multiplier(
        "default method weight multiplier",
        methods.default.weight_multiplier,
    )?;

    for (group, cfg) in &methods.groups {
        validate_timeout(&format!("group `{}` timeout", group), cfg.timeout_ms)?;
        validate_max_retries(&format!("group `{}` max_retries", group), cfg.max_retries)?;
        validate_multiplier(
            &format!("group `{}` weight multiplier", group),
            cfg.weight_multiplier,
        )?;
        validate_backoff(&format!("group `{}` backoff", group), cfg.backoff.as_ref())?;
    }

    for override_cfg in &methods.overrides {
        if override_cfg.pattern.trim().is_empty() {
            return Err(ConfigError::Validation(
                "method override pattern must not be empty".into(),
            ));
        }

        validate_timeout(
            &format!("override `{}` timeout", override_cfg.pattern),
            override_cfg.timeout_ms,
        )?;
        validate_max_retries(
            &format!("override `{}` max_retries", override_cfg.pattern),
            override_cfg.max_retries,
        )?;
        validate_multiplier(
            &format!("override `{}` weight multiplier", override_cfg.pattern),
            override_cfg.weight_multiplier,
        )?;
        validate_backoff(
            &format!("override `{}` backoff", override_cfg.pattern),
            override_cfg.backoff.as_ref(),
        )?;

        if let Some(group_name) = override_cfg.group.as_ref() {
            if !methods.groups.contains_key(group_name) {
                return Err(ConfigError::Validation(format!(
                    "override `{}` references unknown group `{}`",
                    override_cfg.pattern, group_name
                )));
            }
        }
    }

    Ok(())
}

fn validate_backoff(label: &str, config: Option<&BackoffConfig>) -> Result<(), ConfigError> {
    if let Some(cfg) = config {
        if let Some(min) = cfg.min_ms {
            if min == 0 {
                return Err(ConfigError::Validation(format!(
                    "{} min_ms must be greater than zero",
                    label
                )));
            }
        }

        if let Some(max) = cfg.max_ms {
            if max == 0 {
                return Err(ConfigError::Validation(format!(
                    "{} max_ms must be greater than zero",
                    label
                )));
            }
        }

        if let (Some(min), Some(max)) = (cfg.min_ms, cfg.max_ms) {
            if max < min {
                return Err(ConfigError::Validation(format!(
                    "{} max_ms must be greater than or equal to min_ms",
                    label
                )));
            }
        }

        if let Some(jitter) = cfg.jitter {
            if !(0.0..=1.0).contains(&jitter) {
                return Err(ConfigError::Validation(format!(
                    "{} jitter must be between 0.0 and 1.0",
                    label
                )));
            }
        }
    }

    Ok(())
}

fn validate_timeout(label: &str, value: Option<u64>) -> Result<(), ConfigError> {
    if let Some(timeout) = value {
        if timeout == 0 {
            return Err(ConfigError::Validation(format!(
                "{} must be greater than zero",
                label
            )));
        }
    }
    Ok(())
}

fn validate_max_retries(label: &str, value: Option<u8>) -> Result<(), ConfigError> {
    if let Some(retries) = value {
        if retries == 0 {
            return Err(ConfigError::Validation(format!(
                "{} must be greater than zero",
                label
            )));
        }
    }
    Ok(())
}

fn validate_multiplier(label: &str, value: Option<f64>) -> Result<(), ConfigError> {
    if let Some(multiplier) = value {
        if !(0.0..=10.0).contains(&multiplier) {
            return Err(ConfigError::Validation(format!(
                "{} must be between 0 and 10",
                label
            )));
        }
    }
    Ok(())
}
