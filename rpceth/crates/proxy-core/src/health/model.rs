use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::provider::ProviderId;

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
pub enum ToleranceLevel {
    Strict,
    Balanced,
    Relaxed,
}

impl ToleranceLevel {
    pub fn threshold(self) -> f64 {
        match self {
            ToleranceLevel::Strict => 0.1,
            ToleranceLevel::Balanced => 0.3,
            ToleranceLevel::Relaxed => 0.5,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ProviderHealthSnapshot {
    pub provider: ProviderId,
    pub score: f64,
    pub sync_score: f64,
    pub latency_score: f64,
    pub success_score: f64,
    pub method_support_score: f64,
    pub latest_block: Option<u64>,
    pub chain_id: Option<u64>,
    pub last_updated: Option<Instant>,
    pub consecutive_failures: u32,
}

impl ProviderHealthSnapshot {
    pub fn is_within_tolerance(&self, best_score: f64, tolerance: ToleranceLevel) -> bool {
        if best_score <= 0.0 {
            return true;
        }
        let delta = best_score - self.score;
        delta <= tolerance.threshold() * best_score
    }
}

#[derive(Debug, Clone)]
pub struct ProbeSuccess {
    pub provider: ProviderId,
    pub latency: Duration,
    pub block_number: u64,
    pub chain_id: u64,
    pub method_support_score: f64,
}

#[derive(Debug, Clone)]
pub struct ProbeFailureKind {
    pub provider: ProviderId,
    pub latency: Option<Duration>,
    pub reason: FailureReason,
}

#[derive(Debug, Clone)]
pub enum FailureReason {
    Timeout,
    Http(u16),
    Transport(String),
    InvalidPayload(String),
}
