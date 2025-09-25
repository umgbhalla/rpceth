use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
};

use rand::distributions::{Distribution, WeightedIndex};
use rand::{SeedableRng, rngs::StdRng};
use tokio::sync::Mutex;

use crate::config::BalancerStrategy;
use crate::health::{HealthService, ProviderHealthSnapshot, ToleranceLevel};
use crate::methods::MethodPolicy;
use crate::provider::{ProviderHandle, ProviderId};

#[derive(Debug, Clone)]
pub struct ProviderPool {
    providers: Vec<ProviderHandle>,
}

impl ProviderPool {
    pub fn new(providers: Vec<ProviderHandle>) -> Self {
        Self { providers }
    }

    pub fn len(&self) -> usize {
        self.providers.len()
    }

    pub fn is_empty(&self) -> bool {
        self.providers.is_empty()
    }

    pub fn get(&self, index: usize) -> Option<&ProviderHandle> {
        self.providers.get(index)
    }

    pub fn all(&self) -> &[ProviderHandle] {
        &self.providers
    }
}

struct LoadBalancerInner {
    pool: ProviderPool,
    strategy: BalancerStrategy,
    round_robin_cursor: Mutex<usize>,
    rng: Mutex<StdRng>,
    health: Option<Arc<HealthService>>,
}

#[derive(Clone)]
pub struct LoadBalancer {
    inner: Arc<LoadBalancerInner>,
}

impl std::fmt::Debug for LoadBalancer {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("LoadBalancer")
            .field("strategy", &self.inner.strategy)
            .field("provider_count", &self.provider_count())
            .finish()
    }
}

impl LoadBalancer {
    pub fn new(
        strategy: BalancerStrategy,
        providers: Vec<ProviderHandle>,
        health: Option<Arc<HealthService>>,
    ) -> Self {
        Self {
            inner: Arc::new(LoadBalancerInner {
                pool: ProviderPool::new(providers),
                strategy,
                round_robin_cursor: Mutex::new(0),
                rng: Mutex::new(StdRng::seed_from_u64(0xfeed_f00d)),
                health,
            }),
        }
    }

    pub fn provider_count(&self) -> usize {
        self.inner.pool.len()
    }

    pub async fn select(
        &self,
        exclude: &HashSet<ProviderId>,
        policy: Option<&MethodPolicy>,
    ) -> Option<ProviderHandle> {
        let (health_scores, best_score, tolerance, allow_any) =
            if let Some(health) = self.inner.health.as_ref() {
                let filtered = health.filtered_snapshots();
                if filtered.is_empty() {
                    (
                        HashMap::<ProviderId, ProviderHealthSnapshot>::new(),
                        0.0,
                        policy.map(|p| p.tolerance).unwrap_or(health.tolerance()),
                        true,
                    )
                } else {
                    let map = filtered
                        .into_iter()
                        .map(|snapshot| (snapshot.provider.clone(), snapshot))
                        .collect();
                    (
                        map,
                        health.best_score(),
                        policy
                            .map(|p| p.tolerance)
                            .unwrap_or_else(|| health.tolerance()),
                        false,
                    )
                }
            } else {
                (
                    HashMap::new(),
                    0.0,
                    policy
                        .map(|p| p.tolerance)
                        .unwrap_or(ToleranceLevel::Balanced),
                    true,
                )
            };

        let mut eligible = Vec::new();
        for provider in self.inner.pool.all().iter() {
            if exclude.contains(&provider.id) {
                continue;
            }

            if !allow_any {
                if let Some(snapshot) = health_scores.get(&provider.id) {
                    if !snapshot.is_within_tolerance(best_score, tolerance) {
                        continue;
                    }
                } else {
                    continue;
                }
            }

            eligible.push(provider.clone());
        }

        if eligible.is_empty() {
            return None;
        }

        match self.inner.strategy {
            BalancerStrategy::RoundRobin => self.next_round_robin_from(eligible).await,
            BalancerStrategy::WeightedRandom => {
                self.weighted_random_from(eligible, &health_scores, policy)
                    .await
            }
        }
    }

    pub async fn select_any(&self) -> Option<ProviderHandle> {
        self.select(&HashSet::new(), None).await
    }

    async fn next_round_robin_from(&self, eligible: Vec<ProviderHandle>) -> Option<ProviderHandle> {
        let total = eligible.len();
        if total == 0 {
            return None;
        }

        let index = {
            let mut cursor = self.inner.round_robin_cursor.lock().await;
            let index = *cursor % total;
            *cursor = (*cursor + 1) % total;
            index
        };

        eligible.get(index).cloned()
    }

    async fn weighted_random_from(
        &self,
        eligible: Vec<ProviderHandle>,
        health_scores: &HashMap<ProviderId, ProviderHealthSnapshot>,
        policy: Option<&MethodPolicy>,
    ) -> Option<ProviderHandle> {
        if eligible.is_empty() {
            return None;
        }

        if eligible.len() == 1 {
            return Some(eligible.into_iter().next().unwrap());
        }

        let weights: Vec<f64> = eligible
            .iter()
            .map(|provider| {
                let health_multiplier = health_scores
                    .get(&provider.id)
                    .map(|snapshot| snapshot.score.max(0.0))
                    .unwrap_or(1.0);
                let mut weight = provider.base_weight as f64;
                if let Some(policy) = policy {
                    if let Some(override_weight) = policy.provider_weight(&provider.id) {
                        weight = override_weight;
                    } else {
                        weight *= policy.weight_multiplier;
                    }
                }

                (weight * health_multiplier).max(1.0)
            })
            .collect();

        let mut rng = self.inner.rng.lock().await;
        let distribution = WeightedIndex::new(&weights).ok()?;
        let index = distribution.sample(&mut *rng);
        Some(eligible[index].clone())
    }
}
