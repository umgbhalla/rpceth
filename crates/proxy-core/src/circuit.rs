use std::time::{Duration, Instant};

use dashmap::DashMap;

use crate::config::CircuitBreakerConfig;
use crate::provider::{ProviderHandle, ProviderId};

#[derive(Debug, Clone)]
pub struct ResolvedCircuitBreaker {
    pub failure_threshold: u32,
    pub reset_timeout: Duration,
    pub half_open_probe: u32,
}

impl ResolvedCircuitBreaker {
    pub fn from_configs(global: &CircuitBreakerConfig, provider: &CircuitBreakerConfig) -> Self {
        let failure_threshold = provider
            .failure_threshold
            .or(global.failure_threshold)
            .unwrap_or(3);
        let reset_timeout = provider
            .reset_timeout_ms
            .or(global.reset_timeout_ms)
            .unwrap_or(30_000);
        let half_open_probe = provider
            .half_open_probe
            .or(global.half_open_probe)
            .unwrap_or(1);

        Self {
            failure_threshold,
            reset_timeout: Duration::from_millis(reset_timeout),
            half_open_probe,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CircuitStateKind {
    Closed,
    Open,
    HalfOpen,
}

#[derive(Debug, Clone)]
pub struct CircuitSnapshot {
    pub state: CircuitStateKind,
    pub failures: u32,
    pub next_retry_in: Option<Duration>,
}

#[derive(Debug)]
pub struct CircuitBreaker {
    entries: DashMap<ProviderId, ProviderCircuit>,
}

#[derive(Debug, Clone)]
struct ProviderCircuit {
    config: ResolvedCircuitBreaker,
    state: InnerState,
}

#[derive(Debug, Clone)]
enum InnerState {
    Closed { failures: u32 },
    Open { failures: u32, retry_at: Instant },
    HalfOpen { failures: u32, attempts: u32 },
}

impl CircuitBreaker {
    pub fn new(handles: &[ProviderHandle], global: &CircuitBreakerConfig) -> Self {
        let entries = DashMap::new();
        for handle in handles {
            let config = ResolvedCircuitBreaker::from_configs(global, &handle.circuit_breaker);
            entries.insert(
                handle.id.clone(),
                ProviderCircuit {
                    config,
                    state: InnerState::Closed { failures: 0 },
                },
            );
        }

        Self { entries }
    }

    pub fn is_available(&self, provider: &ProviderId) -> bool {
        if let Some(entry) = self.entries.get(provider) {
            match &entry.state {
                InnerState::Closed { .. } => true,
                InnerState::Open { retry_at, .. } => Instant::now() >= *retry_at,
                InnerState::HalfOpen { attempts, .. } => *attempts < entry.config.half_open_probe,
            }
        } else {
            true
        }
    }

    pub fn on_request_start(&self, provider: &ProviderId) {
        if let Some(mut entry) = self.entries.get_mut(provider) {
            match &mut entry.state {
                InnerState::Closed { .. } => {}
                InnerState::Open { failures, retry_at } => {
                    if Instant::now() >= *retry_at {
                        entry.state = InnerState::HalfOpen {
                            failures: *failures,
                            attempts: 0,
                        };
                    }
                }
                InnerState::HalfOpen { attempts, .. } => {
                    *attempts = attempts.saturating_add(1);
                }
            }
        }
    }

    pub fn on_success(&self, provider: &ProviderId) {
        if let Some(mut entry) = self.entries.get_mut(provider) {
            entry.state = InnerState::Closed { failures: 0 };
        }
    }

    pub fn on_failure(&self, provider: &ProviderId) {
        if let Some(mut entry) = self.entries.get_mut(provider) {
            let failure_threshold = entry.config.failure_threshold;
            let reset_timeout = entry.config.reset_timeout;
            match &mut entry.state {
                InnerState::Closed { failures } => {
                    *failures = failures.saturating_add(1);
                    if *failures >= failure_threshold {
                        entry.state = InnerState::Open {
                            failures: *failures,
                            retry_at: Instant::now() + reset_timeout,
                        };
                    }
                }
                InnerState::HalfOpen { failures, .. } => {
                    *failures = failures.saturating_add(1);
                    entry.state = InnerState::Open {
                        failures: *failures,
                        retry_at: Instant::now() + reset_timeout,
                    };
                }
                InnerState::Open { failures, retry_at } => {
                    *failures = failures.saturating_add(1);
                    *retry_at = Instant::now() + reset_timeout;
                }
            }
        }
    }

    pub fn snapshot(&self, provider: &ProviderId) -> Option<CircuitSnapshot> {
        self.entries.get(provider).map(|entry| match &entry.state {
            InnerState::Closed { failures } => CircuitSnapshot {
                state: CircuitStateKind::Closed,
                failures: *failures,
                next_retry_in: None,
            },
            InnerState::Open { failures, retry_at } => CircuitSnapshot {
                state: CircuitStateKind::Open,
                failures: *failures,
                next_retry_in: Some(retry_at.saturating_duration_since(Instant::now())),
            },
            InnerState::HalfOpen { failures, .. } => CircuitSnapshot {
                state: CircuitStateKind::HalfOpen,
                failures: *failures,
                next_retry_in: None,
            },
        })
    }
}
