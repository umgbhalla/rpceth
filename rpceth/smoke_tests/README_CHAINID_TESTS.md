# Chain ID Parameter Route Testing Suite

This directory contains comprehensive tests for the `/chainid` parameter route functionality in the RPC proxy. These tests verify multi-chain routing, provider selection, error handling, and security aspects of chain ID parameter processing.

## Test Files Overview

### 1. `test_chainid_comprehensive.py`
**Comprehensive Chain ID Routing Tests**

Tests core chain ID functionality including:
- Basic chain routing (numeric IDs and aliases)
- Chain-specific RPC method calls
- Invalid chain ID handling
- Chain + provider override combinations
- Chain consistency across multiple requests
- Performance characteristics of chain routing

**Key Features:**
- Tests 6 major blockchain networks (Ethereum, Polygon, BSC, Arbitrum, Optimism, Avalanche)
- Validates both numeric chain IDs (1, 137, 56) and aliases (eth, polygon, bsc)
- Performance testing with concurrent requests
- Consistency validation across multiple calls

### 2. `test_chainid_multichain_scenarios.py`
**Multi-Chain Routing Scenarios**

Tests realistic multi-chain proxy scenarios:
- Cross-chain consistency validation
- Concurrent requests to different chains
- Chain-specific smart contract interactions
- Provider failover per chain
- Method compatibility across chains
- Load balancing behavior per chain

**Key Features:**
- Real-world contract addresses for testing
- Concurrent multi-chain request handling (15 simultaneous requests)
- Chain-specific failover testing
- Load balancing distribution analysis

### 3. `test_chainid_edge_cases.py`
**Edge Cases and Security Testing**

Tests security and error handling:
- Malformed chain ID injection attempts
- URL encoding/decoding scenarios
- Rate limiting per chain
- Concurrent invalid request handling
- Case sensitivity testing
- Security vulnerability testing (SQL injection, XSS, path traversal)

**Key Features:**
- 80+ malformed chain ID test cases
- Security injection attempt detection
- Rate limiting validation (50 rapid requests per chain)
- Concurrent stress testing (30 invalid requests)
- Unicode and special character handling

### 4. `run_chainid_tests.py`
**Test Suite Runner**

Orchestrates all chain ID tests and provides comprehensive reporting:
- Executes all test files in sequence
- Analyzes results and generates health scores
- Provides actionable recommendations
- Creates detailed JSON reports

## Chain ID Functionality Expected

Based on research of production RPC proxies, the chain ID parameter should:

1. **Route to Different Networks**: `/1` → Ethereum, `/137` → Polygon, `/56` → BSC
2. **Support Aliases**: `/eth` → Ethereum, `/polygon` → Polygon, `/bsc` → BSC
3. **Provider Selection**: Different providers per chain based on configuration
4. **Validation**: Reject invalid/malicious chain IDs securely
5. **Consistency**: Same chain ID should always route to the same network

## Current Implementation Status

The proxy currently accepts `/:chain_id` as a route parameter but **does not implement actual chain-specific routing**. The tests will help identify:

- Whether chain IDs are properly extracted from URLs
- If chain validation is implemented
- Whether different chains route to different providers
- How errors are handled for invalid chain IDs

## Running the Tests

### Run All Tests
```bash
cd smoke_tests
python3 run_chainid_tests.py
```

### Run Individual Tests
```bash
# Comprehensive functionality tests
python3 test_chainid_comprehensive.py

# Multi-chain scenario tests  
python3 test_chainid_multichain_scenarios.py

# Edge cases and security tests
python3 test_chainid_edge_cases.py
```

### Prerequisites
- Python 3.7+
- aiohttp library: `pip install aiohttp`
- Running RPC proxy on `localhost:3000`
- Valid API key (default: "change-me")

## Test Results

Each test generates detailed JSON results:
- `chainid_comprehensive_test_results.json`
- `chainid_multichain_test_results.json` 
- `chainid_edge_cases_test_results.json`
- `chainid_test_suite_results.json` (combined summary)

## Expected Test Outcomes

### If Chain ID Routing is NOT Implemented:
- ✅ Basic URL parsing should work
- ❌ Chain-specific routing will fail
- ❌ Chain validation will be missing
- ⚠️ Security tests may pass but without proper validation

### If Chain ID Routing IS Implemented:
- ✅ All basic routing tests should pass
- ✅ Chain aliases should work
- ✅ Invalid chain IDs should be rejected
- ✅ Security tests should properly block malicious inputs

## Chain Mappings Used in Tests

| Chain ID | Name      | Aliases                | Expected Response |
| -------- | --------- | ---------------------- | ----------------- |
| 1        | Ethereum  | eth, ethereum, mainnet | 0x1               |
| 137      | Polygon   | polygon, matic         | 0x89              |
| 56       | BSC       | bsc, binance           | 0x38              |
| 42161    | Arbitrum  | arbitrum, arb          | 0xa4b1            |
| 10       | Optimism  | optimism, op           | 0xa               |
| 43114    | Avalanche | avalanche, avax        | 0xa86a            |

## Security Test Categories

1. **Input Validation**: Special characters, Unicode, control characters
2. **Injection Attacks**: SQL injection, XSS, command injection attempts
3. **Path Traversal**: Directory traversal and file access attempts
4. **DoS Protection**: Rate limiting and concurrent request handling
5. **Encoding Issues**: URL encoding/decoding edge cases

## Recommendations Based on Test Results

The test suite will provide specific recommendations:

- **Critical Issues**: Missing chain validation, security vulnerabilities
- **Performance Issues**: Slow routing, poor load balancing
- **UX Issues**: Missing aliases, poor error messages
- **Implementation Gaps**: Missing multi-chain support

## Integration with CI/CD

These tests can be integrated into CI/CD pipelines:

```bash
# Exit code 0 = all tests pass
# Exit code 1 = one or more tests failed
python3 run_chainid_tests.py
```

The comprehensive nature of these tests makes them suitable for:
- Development testing
- Pre-deployment validation
- Production monitoring
- Security auditing
- Performance benchmarking
