# RPC Methods Tested in Smoke Tests

## Overview

This document catalogs all JSON-RPC methods tested across the comprehensive smoke test suite for the RPCETH proxy server. The tests cover basic functionality, realistic Ethereum scenarios, method-specific routing, chain ID routing, retry/backoff behavior, and stress testing.

## Core Network Methods

### Basic Network Information
- **`eth_chainId`** - Returns the chain ID of the current network
  - Tested in: `test_proxy_comprehensive.py`, `test_realistic_rpc_scenarios.py`, `test_method_routing_phase4.py`, `test_chainid_comprehensive.py`
  - Usage: Chain identification and validation across different networks

- **`eth_blockNumber`** - Returns the latest block number
  - Tested in: `test_proxy_comprehensive.py`, `test_realistic_rpc_scenarios.py`, `test_method_routing_phase4.py`, `test_retry_backoff_phase4.py`, `test_stress_and_edge_cases.py`
  - Usage: Health monitoring, load balancing tests, performance benchmarks

- **`net_version`** - Returns the network version
  - Tested in: `test_realistic_rpc_scenarios.py`, `test_chainid_comprehensive.py`
  - Usage: Network identification and compatibility checks

- **`eth_gasPrice`** - Returns the current gas price
  - Tested in: `test_realistic_rpc_scenarios.py`, `test_chainid_comprehensive.py`, `test_stress_and_edge_cases.py`
  - Usage: Gas price monitoring and transaction cost estimation

## Block and Transaction Methods

### Block Queries
- **`eth_getBlockByNumber`** - Returns block information by number
  - Tested in: `test_method_routing_phase4.py`, `test_realistic_rpc_scenarios.py`, `test_chainid_comprehensive.py`
  - Parameters: `["latest", false]`, `["latest", true]` (with/without transactions)
  - Usage: Block analysis, transaction inspection

- **`eth_getBlockTransactionCountByNumber`** - Returns transaction count in a block
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: Block analysis and transaction counting

- **`eth_getUncleCountByBlockNumber`** - Returns uncle count for a block
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: Block validation and uncle analysis

### Transaction Methods
- **`eth_sendRawTransaction`** - Sends a raw transaction
  - Tested in: `test_method_routing_phase4.py`, `test_retry_backoff_phase4.py`
  - Parameters: `["0xdeadbeef"]` (invalid transaction for error testing)
  - Usage: Write method testing, error handling validation

## Account and Balance Methods

### Account Queries
- **`eth_getBalance`** - Returns account balance
  - Tested in: `test_realistic_rpc_scenarios.py`, `test_chainid_comprehensive.py`, `test_stress_and_edge_cases.py`
  - Parameters: `["0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "latest"]` (Vitalik's address)
  - Usage: Balance checking, account monitoring

- **`eth_getTransactionCount`** - Returns transaction count for an address
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Parameters: `["0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "latest"]`
  - Usage: Nonce calculation, account activity tracking

## Smart Contract Methods

### Contract Code and Storage
- **`eth_getCode`** - Returns contract code at an address
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Parameters: `["0xA0b86a33E6441E2a3B4E6b6A6C4B3C3B3A8B8B8B", "latest"]` (USDC contract)
  - Usage: Contract verification, code analysis

- **`eth_getStorageAt`** - Returns storage value at position
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Parameters: `["0xA0b86a33E6441E2a3B4E6b6A6C4B3C3B3A8B8B8B", "0x0", "latest"]`
  - Usage: Storage inspection, contract state analysis

### Contract Calls
- **`eth_call`** - Executes a message call without creating a transaction
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: ERC20 token queries, contract method calls

#### ERC20 Token Contract Calls
- **`totalSupply()`** - `0x18160ddd`
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: USDC total supply query

- **`decimals()`** - `0x313ce567`
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: USDC decimals query

- **`name()`** - `0x06fdde03`
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: USDC name query

- **`symbol()`** - `0x95d89b41`
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: USDC symbol query

- **`balanceOf(address)`** - `0x70a08231` + address
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: USDC balance query for Vitalik's address

## Error Handling Methods

### Invalid Methods (Expected to Fail)
- **`invalid_method`** - Non-existent method
  - Tested in: `test_proxy_comprehensive.py`
  - Usage: Error handling validation

- **`eth_totallyFakeMethod`** - Invalid Ethereum method
  - Tested in: `test_method_routing_phase4.py`, `test_retry_backoff_phase4.py`
  - Usage: Method validation testing

- **`nonexistent_method`** - Generic invalid method
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: Error scenario testing

### Invalid Parameters (Expected to Fail)
- **`eth_getBalance`** with invalid address
  - Parameters: `["0xinvalid", "latest"]`
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: Parameter validation testing

- **`eth_getBlockByNumber`** with non-existent block
  - Parameters: `["0xffffffff", false]`
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: Block validation testing

- **`eth_call`** with zero address
  - Parameters: `[{"to": "0x0000000000000000000000000000000000000000", "data": "0x12345678"}, "latest"]`
  - Tested in: `test_realistic_rpc_scenarios.py`
  - Usage: Contract call validation

## Test Categories by Method Type

### Read-Heavy Methods (Method Group: "read")
- `eth_blockNumber`
- `eth_getBlockByNumber`
- `net_version`
- `eth_chainId`
- `eth_gasPrice`
- `eth_getBalance`
- `eth_getTransactionCount`
- `eth_getCode`
- `eth_getStorageAt`
- `eth_call`

### Write Methods (Method Group: "write")
- `eth_sendRawTransaction`

### Health Check Methods
- `eth_blockNumber` - Primary health check method
- `eth_chainId` - Secondary health check method

## Test Scenarios by Complexity

### Simple Scenarios
- Basic network information queries
- Health monitoring probes
- Load balancing tests

### Medium Complexity
- Wallet balance queries
- ERC20 token interactions
- Contract code and storage queries

### Complex Scenarios
- Block and transaction analysis
- Concurrent request handling
- Multi-chain routing
- Error handling and edge cases

## Performance Testing Methods

### High-Frequency Methods
- `eth_blockNumber` - Used in load testing (100+ requests)
- `eth_gasPrice` - Used in concurrent load tests
- `eth_chainId` - Used in chain routing tests

### Stress Test Methods
- Mixed method calls under high concurrency
- Error injection scenarios
- Timeout and retry testing

## Chain-Specific Testing

### Multi-Chain Methods
All core methods tested across multiple chains:
- Ethereum Mainnet (chain ID: 1, aliases: "eth", "ethereum", "mainnet")
- Polygon (chain ID: 137, aliases: "polygon", "matic")
- Binance Smart Chain (chain ID: 56, aliases: "bsc", "binance")
- Arbitrum One (chain ID: 42161, aliases: "arbitrum", "arb")
- Optimism (chain ID: 10, aliases: "optimism", "op")
- Avalanche C-Chain (chain ID: 43114, aliases: "avalanche", "avax")

## Trace ID Testing

All methods tested with:
- Custom trace ID preservation
- Auto-generated trace ID creation
- Trace ID propagation through proxy
- OpenTelemetry integration validation

## Summary Statistics

**Total Unique RPC Methods Tested**: 15+
**Total Test Scenarios**: 50+
**Test Categories**: 8 (Basic, Network, Block, Transaction, Account, Contract, Error, Performance)
**Chain Coverage**: 6 different networks
**Method Groups**: 2 (read, write)
**Complexity Levels**: 3 (simple, medium, complex)

The comprehensive test suite ensures that all major Ethereum JSON-RPC methods are properly handled by the proxy, with appropriate routing, error handling, and performance characteristics across multiple blockchain networks.
