use std::sync::Arc;
use std::time::{Duration, Instant};

use dashmap::DashMap;
use tokio::time::interval;

use crate::health::model::{
    ProbeFailureKind, ProbeSuccess, ProviderHealthSnapshot, ToleranceLevel,
};
use crate::provider::{ProviderHandle, ProviderId};

#[derive(Debug, Clone)]
pub struct ProviderHealthState {
    pub provider: ProviderHandle,
    pub latest_block: Option<u64>,
    pub chain_id: Option<u64>,
    pub latency_avg: f64,
    pub success_rate: f64,
    pub sync_score: f64,
    pub method_support_score: f64,
    pub last_updated: Option<Instant>,
    pub consecutive_failures: u32,
}

impl ProviderHealthState {
    fn new(provider: ProviderHandle) -> Self {
        Self {
            provider,
            latest_block: None,
            chain_id: None,
            latency_avg: 0.0,
            success_rate: 1.0,
            sync_score: 1.0,
            method_support_score: 1.0,
            last_updated: None,
            consecutive_failures: 0,
        }
    }

    fn apply_success(&mut self, success: &ProbeSuccess) {
        let alpha = 0.3; // smoothing factor for EWMA
        let latency_ms = success.latency.as_secs_f64() * 1_000.0;
        self.latency_avg = if self.latency_avg == 0.0 {
            latency_ms
        } else {
            (1.0 - alpha) * self.latency_avg + alpha * latency_ms
        };

        self.success_rate = (1.0 - alpha) * self.success_rate + alpha;
        self.sync_score = 1.0;
        self.method_support_score = success.method_support_score;
        self.latest_block = Some(success.block_number);
        self.chain_id = Some(success.chain_id);
        self.last_updated = Some(Instant::now());
        self.consecutive_failures = 0;
    }

    fn apply_failure(&mut self, _failure: &ProbeFailureKind) {
        let alpha = 0.3;
        self.success_rate *= 1.0 - alpha;
        self.consecutive_failures += 1;
        self.last_updated = Some(Instant::now());
    }

    fn score(&self) -> f64 {
        let sync = self.sync_score.clamp(0.0, 1.0);
        let latency = if self.latency_avg <= 0.0 {
            1.0
        } else {
            (2000.0 / self.latency_avg).clamp(0.0, 1.0)
        };
        let success = self.success_rate.clamp(0.0, 1.0);
        let method_support = self.method_support_score.clamp(0.0, 1.0);

        sync * 0.4 + latency * 0.3 + success * 0.2 + method_support * 0.1
    }

    fn snapshot(&self) -> ProviderHealthSnapshot {
        ProviderHealthSnapshot {
            provider: self.provider.id.clone(),
            score: self.score(),
            sync_score: self.sync_score,
            latency_score: if self.latency_avg <= 0.0 {
                1.0
            } else {
                (2000.0 / self.latency_avg).clamp(0.0, 1.0)
            },
            success_score: self.success_rate,
            method_support_score: self.method_support_score,
            latest_block: self.latest_block,
            chain_id: self.chain_id,
            last_updated: self.last_updated,
            consecutive_failures: self.consecutive_failures,
        }
    }
}

#[derive(Clone)]
pub struct HealthService {
    state: Arc<DashMap<ProviderId, ProviderHealthState>>,
    tolerance: ToleranceLevel,
    interval: Duration,
    probe: Arc<dyn HealthProbe + Send + Sync>,
}

impl HealthService {
    pub fn new(
        providers: Vec<ProviderHandle>,
        tolerance: ToleranceLevel,
        interval: Duration,
        probe: Arc<dyn HealthProbe + Send + Sync>,
    ) -> Self {
        let state = DashMap::new();
        for provider in providers.into_iter() {
            state.insert(provider.id.clone(), ProviderHealthState::new(provider));
        }

        Self {
            state: Arc::new(state),
            tolerance,
            interval,
            probe,
        }
    }

    pub fn snapshots(&self) -> Vec<ProviderHealthSnapshot> {
        self.state
            .iter()
            .map(|entry| entry.value().snapshot())
            .collect()
    }

    pub fn best_score(&self) -> f64 {
        self.state
            .iter()
            .map(|entry| entry.value().score())
            .fold(0.0, f64::max)
    }

    pub fn filtered_snapshots(&self) -> Vec<ProviderHealthSnapshot> {
        let best = self.best_score();
        self.snapshots()
            .into_iter()
            .filter(|snapshot| snapshot.is_within_tolerance(best, self.tolerance))
            .collect()
    }

    pub fn tolerance(&self) -> ToleranceLevel {
        self.tolerance
    }

    pub async fn spawn(self: Arc<Self>) {
        let mut ticker = interval(self.interval);
        loop {
            ticker.tick().await;
            let to_probe: Vec<ProviderHandle> = self
                .state
                .iter()
                .map(|entry| entry.value().provider.clone())
                .collect();

            for provider in to_probe {
                let service = Arc::clone(&self);
                tokio::spawn(async move {
                    match service.probe.probe(&provider).await {
                        Ok(success) => service.apply_success(success).await,
                        Err(failure) => service.apply_failure(failure).await,
                    }
                });
            }
        }
    }

    async fn apply_success(&self, success: ProbeSuccess) {
        if let Some(mut entry) = self.state.get_mut(&success.provider) {
            entry.apply_success(&success);
        }
    }

    async fn apply_failure(&self, failure: ProbeFailureKind) {
        if let Some(mut entry) = self.state.get_mut(&failure.provider) {
            entry.apply_failure(&failure);
        }
    }
}

#[async_trait::async_trait]
pub trait HealthProbe {
    async fn probe(&self, provider: &ProviderHandle) -> Result<ProbeSuccess, ProbeFailureKind>;
}
