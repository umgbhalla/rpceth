# Phase 3 Research Notes

- **Health Check Scheduling**: `tokio-cron-scheduler` or `tokio_schedule` manage periodic probes with cron expressions or fixed intervals; `tokio::time::interval` suffices for simple loops.
- **Health Metrics Storage**: `dashmap` and `indexmap` offer concurrent-friendly maps for tracking provider stats without heavy locking; `atomic_float` can store rolling averages.
- **RPC Health Probing**: `jsonrpsee` or `ethers-providers` crate supplies Ethereum-specific RPC clients to call `eth_blockNumber` and `eth_chainId` easily.
- **Latency Measurement**: `tower::timeout` combined with `tokio::time::Instant` enables timing; `hdrhistogram` collects latency distributions for scoring.
- **Scoring & Weight Adjustment**: `ordered-float` or `float-ord` allow HashMap keys by float score; `statrs` or `average` crate provides EWMA helpers for smoothing success rates.
- **Tolerance Filtering & Backoff**: `backoff` crate implements exponential backoff strategies; `futures_retry` supports retry policies with jitter.
- **Observability**: `tracing` spans annotate health check workflows; `opentelemetry` + `tracing-opentelemetry` export health events; `metrics` crate records health scores.
- **Failure Recovery**: `governor` or `ratelimit_meter` manage probe frequencies; `async-channel` coordinates background tasks resuming providers after successful checks.

