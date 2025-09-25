use thiserror::Error;

#[derive(Debug, Error)]
pub enum ProxyError {
    #[error("provider pool exhausted")]
    ProviderPoolEmpty,

    #[error("no eligible providers for selection")]
    NoEligibleProviders,

    #[error("invalid configuration: {0}")]
    Configuration(String),

    #[error("upstream request failed: {0}")]
    UpstreamRequest(String),
}
