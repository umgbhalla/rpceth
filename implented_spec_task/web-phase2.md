# Phase 2 Research Notes

- **Configuration Parsing**: `serde_yaml` remains the standard for loading provider definitions; pair with `config` crate for layered sources and type-safe deserialization.
- **Provider Metadata Structures**: `url` crate validates RPC endpoint URLs; use `nonzero_ext` or `rust_decimal` for weights if fractional weighting is required.
- **Weighted Load Balancing**: Tower-based crates such as `tower::load_shed`, `tower::buffer`, and `tower::balance::p2c::Balance` provide ready-made load balancing primitives; `tower::limit::ConcurrencyLimit` enforces per-provider connection caps.
- **Custom Weighted Selection**: `rand` (with `WeightedIndex`) or `weighted-bag` crate helps implement weighted random choices aligning with base weights.
- **Round Robin Support**: `async-broadcast` or `async-lock::RwLock` with `VecDeque` for simple round robin; alternatively, `tower::balance::power_of_two_choices` approximates even distribution.
- **Failure Detection & Retry**: `tower::retry` paired with `tower::timeout` enables retry-on-failure behaviour; `reqwest_middleware` with `reqwest_retry` offers policy-based retries for HTTP clients.
- **Structured Logging**: `tracing` layers capture provider selection events; `tracing-appender` persists logs.
- **Data Validation**: `schemars` plus `validator` crate annotate config schema and enforce constraints at startup.

