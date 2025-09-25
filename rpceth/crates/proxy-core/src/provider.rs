use std::time::Duration;

use serde::Deserialize;
use url::Url;

use crate::config::{CircuitBreakerConfig, ConfigError};

#[derive(Debug, Clone, PartialEq, Eq, Hash, Deserialize)]
#[serde(transparent)]
pub struct ProviderId(pub String);

impl From<&str> for ProviderId {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ProviderConfig {
    pub id: ProviderId,
    pub url: Url,
    #[serde(default = "default_base_weight")]
    pub base_weight: u16,
    #[serde(default = "default_max_connections")]
    pub max_connections: u32,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
    #[serde(default)]
    pub circuit_breaker: CircuitBreakerConfig,
}

fn default_base_weight() -> u16 {
    100
}

fn default_max_connections() -> u32 {
    32
}

fn default_timeout_ms() -> u64 {
    5_000
}

impl ProviderConfig {
    pub fn validate(&self) -> Result<(), ConfigError> {
        if !(1..=1_000).contains(&self.base_weight) {
            return Err(ConfigError::Validation(format!(
                "provider `{}` base_weight must be between 1 and 1000",
                self.id.0
            )));
        }

        if self.max_connections == 0 {
            return Err(ConfigError::Validation(format!(
                "provider `{}` max_connections must be greater than zero",
                self.id.0
            )));
        }

        if self.timeout_ms == 0 {
            return Err(ConfigError::Validation(format!(
                "provider `{}` timeout_ms must be greater than zero",
                self.id.0
            )));
        }

        Ok(())
    }

    pub fn timeout(&self) -> Duration {
        Duration::from_millis(self.timeout_ms)
    }

    pub fn into_handle(self) -> ProviderHandle {
        ProviderHandle {
            id: self.id,
            url: self.url,
            base_weight: self.base_weight,
            max_connections: self.max_connections,
            timeout: Duration::from_millis(self.timeout_ms),
            circuit_breaker: self.circuit_breaker.clone(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct ProviderHandle {
    pub id: ProviderId,
    pub url: Url,
    pub base_weight: u16,
    pub max_connections: u32,
    pub timeout: Duration,
    pub circuit_breaker: CircuitBreakerConfig,
}
