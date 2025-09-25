use std::time::Duration;

use reqwest::Client;
use serde::{Deserialize, Serialize};

use crate::health::model::{FailureReason, ProbeFailureKind, ProbeSuccess};
use crate::health::service::HealthProbe;
use crate::provider::ProviderHandle;

#[derive(Debug, Clone)]
pub struct JsonRpcHealthProbe {
    client: Client,
}

impl JsonRpcHealthProbe {
    pub fn new(timeout: Duration) -> Self {
        let client = Client::builder()
            .timeout(timeout)
            .build()
            .expect("failed to build reqwest client for health probe");

        Self { client }
    }
}

#[derive(Debug, Serialize)]
struct ChainIdRequest<'a> {
    jsonrpc: &'a str,
    method: &'a str,
    params: &'a [&'a str],
    id: u64,
}

#[derive(Debug, Deserialize)]
struct ChainIdResponse {
    result: Option<String>,
}

#[derive(Debug, Serialize)]
struct BlockNumberRequest<'a> {
    jsonrpc: &'a str,
    method: &'a str,
    params: &'a [&'a str],
    id: u64,
}

#[derive(Debug, Deserialize)]
struct BlockNumberResponse {
    result: Option<String>,
}

#[async_trait::async_trait]
impl HealthProbe for JsonRpcHealthProbe {
    async fn probe(&self, provider: &ProviderHandle) -> Result<ProbeSuccess, ProbeFailureKind> {
        let chain_id_req = ChainIdRequest {
            jsonrpc: "2.0",
            method: "eth_chainId",
            params: &[],
            id: 1,
        };

        let start = std::time::Instant::now();

        let chain_id_resp = self
            .client
            .post(provider.url.clone())
            .header("content-type", "application/json")
            .json(&chain_id_req)
            .send()
            .await
            .map_err(|err| ProbeFailureKind {
                provider: provider.id.clone(),
                latency: Some(start.elapsed()),
                reason: FailureReason::Transport(err.to_string()),
            })?;

        if !chain_id_resp.status().is_success() {
            return Err(ProbeFailureKind {
                provider: provider.id.clone(),
                latency: Some(start.elapsed()),
                reason: FailureReason::Http(chain_id_resp.status().as_u16()),
            });
        }

        let chain_id_body: ChainIdResponse =
            chain_id_resp.json().await.map_err(|err| ProbeFailureKind {
                provider: provider.id.clone(),
                latency: Some(start.elapsed()),
                reason: FailureReason::InvalidPayload(err.to_string()),
            })?;

        let chain_id_hex = chain_id_body.result.unwrap_or_default();
        let chain_id =
            u64::from_str_radix(chain_id_hex.trim_start_matches("0x"), 16).unwrap_or_default();

        let block_req = BlockNumberRequest {
            jsonrpc: "2.0",
            method: "eth_blockNumber",
            params: &[],
            id: 2,
        };

        let block_resp = self
            .client
            .post(provider.url.clone())
            .header("content-type", "application/json")
            .json(&block_req)
            .send()
            .await
            .map_err(|err| ProbeFailureKind {
                provider: provider.id.clone(),
                latency: Some(start.elapsed()),
                reason: FailureReason::Transport(err.to_string()),
            })?;

        if !block_resp.status().is_success() {
            return Err(ProbeFailureKind {
                provider: provider.id.clone(),
                latency: Some(start.elapsed()),
                reason: FailureReason::Http(block_resp.status().as_u16()),
            });
        }

        let block_body: BlockNumberResponse =
            block_resp.json().await.map_err(|err| ProbeFailureKind {
                provider: provider.id.clone(),
                latency: Some(start.elapsed()),
                reason: FailureReason::InvalidPayload(err.to_string()),
            })?;

        let block_hex = block_body.result.unwrap_or_default();
        let block_number =
            u64::from_str_radix(block_hex.trim_start_matches("0x"), 16).unwrap_or_default();

        let latency = start.elapsed();

        Ok(ProbeSuccess {
            provider: provider.id.clone(),
            latency,
            block_number,
            chain_id,
            method_support_score: 1.0,
        })
    }
}
