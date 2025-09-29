#!/usr/bin/env python3
"""
Multi-Chain Routing Scenarios for Chain ID Parameter Testing
Tests realistic multi-chain proxy scenarios, provider failover per chain, and cross-chain consistency
"""

import asyncio
import aiohttp
import json
import time
import random
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# Real-world chain configurations
PRODUCTION_CHAINS = {
    "ethereum": {
        "chain_id": "1",
        "aliases": ["eth", "ethereum", "mainnet"],
        "expected_chain_id": "0x1",
        "common_contracts": {
            "USDC": "0xA0b86a33E6441E2a3B4E6b6A6C4B3C3B3A8B8B8B",
            "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "Uniswap_V3": "0xE592427A0AEce92De3Edee1F18E0157C05861564"
        },
        "test_addresses": [
            "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",  # Vitalik
            "0x3f5CE5FBFe3E9af3971dD833D26bA9b5C936f0bE",  # Binance
        ]
    },
    "polygon": {
        "chain_id": "137",
        "aliases": ["polygon", "matic"],
        "expected_chain_id": "0x89",
        "common_contracts": {
            "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
            "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
        },
        "test_addresses": [
            "0x0000000000000000000000000000000000001010",  # Polygon native token
        ]
    },
    "bsc": {
        "chain_id": "56",
        "aliases": ["bsc", "binance"],
        "expected_chain_id": "0x38",
        "common_contracts": {
            "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
            "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
        },
        "test_addresses": [
            "0x8894E0a0c962CB723c1976a4421c95949bE2D4E3",  # Binance hot wallet
        ]
    }
}

@dataclass
class MultiChainScenario:
    name: str
    description: str
    chains: List[str]
    methods: List[Tuple[str, List[Any]]]
    expected_outcomes: Dict[str, Any]
    complexity: str

class MultiChainRoutingTester:
    def __init__(self, proxy_url: str = "http://localhost:3000", api_key: str = "change-me"):
        self.proxy_url = proxy_url
        self.api_key = api_key
        self.session = None
        self.test_results = {}
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def make_rpc_call(self, method: str, params: List[Any] = None, 
                           chain_id: str = None, provider_id: str = None,
                           timeout: int = 10) -> Dict:
        """Make an RPC call with comprehensive error handling"""
        if params is None:
            params = []
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": random.randint(1, 1000000)
        }
        
        path = f"/{chain_id}" if chain_id else "/"
        query_params = [f"apikey={self.api_key}"]
        if provider_id:
            query_params.append(f"provider_id={provider_id}")
        
        url = f"{self.proxy_url}{path}?{'&'.join(query_params)}"
        
        headers = {
            "Content-Type": "application/json",
            "x-test-scenario": f"multichain-{chain_id or 'default'}-{method}",
            "x-request-time": str(int(time.time()))
        }
        
        start_time = time.time()
        
        try:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
                latency = time.time() - start_time
                
                try:
                    response_data = await response.json()
                except Exception as json_error:
                    response_data = {
                        "error": {
                            "code": -32700,
                            "message": f"JSON parse error: {str(json_error)}"
                        }
                    }
                
                return {
                    "success": response.status == 200 and "result" in response_data,
                    "status_code": response.status,
                    "response": response_data,
                    "latency_ms": latency * 1000,
                    "trace_id": response.headers.get('x-trace-id', 'NO_TRACE_ID'),
                    "url": url,
                    "chain_id": chain_id,
                    "method": method,
                    "provider_used": response.headers.get('x-provider-id', 'unknown'),
                    "request_payload": payload,
                    "headers": dict(response.headers)
                }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Request timeout",
                "url": url,
                "chain_id": chain_id,
                "method": method,
                "latency_ms": (time.time() - start_time) * 1000,
                "timeout": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "url": url,
                "chain_id": chain_id,
                "method": method,
                "latency_ms": (time.time() - start_time) * 1000
            }
    
    async def test_cross_chain_consistency(self) -> Dict:
        """Test that different chains return appropriate chain-specific data"""
        print("🌐 Testing Cross-Chain Consistency...")
        
        results = {}
        
        # Test eth_chainId across different chains
        for chain_name, chain_config in PRODUCTION_CHAINS.items():
            chain_tests = {}
            
            # Test numeric chain ID
            result = await self.make_rpc_call("eth_chainId", chain_id=chain_config["chain_id"])
            chain_tests["numeric_id"] = {
                "requested_chain": chain_config["chain_id"],
                "expected_chain_id": chain_config["expected_chain_id"],
                "actual_chain_id": result.get("response", {}).get("result"),
                "matches_expected": result.get("response", {}).get("result") == chain_config["expected_chain_id"],
                "success": result["success"],
                "latency_ms": result.get("latency_ms", 0),
                "trace_id": result.get("trace_id")
            }
            
            # Test aliases
            for alias in chain_config["aliases"]:
                result = await self.make_rpc_call("eth_chainId", chain_id=alias)
                chain_tests[f"alias_{alias}"] = {
                    "alias": alias,
                    "expected_chain_id": chain_config["expected_chain_id"],
                    "actual_chain_id": result.get("response", {}).get("result"),
                    "matches_expected": result.get("response", {}).get("result") == chain_config["expected_chain_id"],
                    "success": result["success"],
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                }
            
            results[chain_name] = chain_tests
        
        return results
    
    async def test_concurrent_multi_chain_requests(self) -> Dict:
        """Test concurrent requests to different chains"""
        print("⚡ Testing Concurrent Multi-Chain Requests...")
        
        results = {}
        
        # Create concurrent requests to different chains
        concurrent_tasks = []
        chain_list = list(PRODUCTION_CHAINS.keys())
        
        for i in range(15):  # 15 concurrent requests
            chain_name = random.choice(chain_list)
            chain_config = PRODUCTION_CHAINS[chain_name]
            chain_id = random.choice([chain_config["chain_id"]] + chain_config["aliases"])
            method = random.choice(["eth_chainId", "eth_blockNumber", "eth_gasPrice"])
            
            task = self.make_rpc_call(method, chain_id=chain_id)
            concurrent_tasks.append({
                "task": task,
                "chain_name": chain_name,
                "chain_id": chain_id,
                "method": method,
                "request_num": i + 1
            })
        
        # Execute all tasks concurrently
        start_time = time.time()
        task_results = await asyncio.gather(*[task_info["task"] for task_info in concurrent_tasks])
        total_time = time.time() - start_time
        
        # Analyze results
        successful_requests = 0
        chain_distribution = {}
        method_distribution = {}
        latencies = []
        
        for i, result in enumerate(task_results):
            task_info = concurrent_tasks[i]
            
            if result["success"]:
                successful_requests += 1
                latencies.append(result.get("latency_ms", 0))
            
            chain_name = task_info["chain_name"]
            method = task_info["method"]
            
            if chain_name not in chain_distribution:
                chain_distribution[chain_name] = {"total": 0, "successful": 0}
            chain_distribution[chain_name]["total"] += 1
            if result["success"]:
                chain_distribution[chain_name]["successful"] += 1
            
            if method not in method_distribution:
                method_distribution[method] = {"total": 0, "successful": 0}
            method_distribution[method]["total"] += 1
            if result["success"]:
                method_distribution[method]["successful"] += 1
        
        results["concurrent_summary"] = {
            "total_requests": len(concurrent_tasks),
            "successful_requests": successful_requests,
            "success_rate": successful_requests / len(concurrent_tasks),
            "total_time_seconds": total_time,
            "requests_per_second": len(concurrent_tasks) / total_time,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "min_latency_ms": min(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
            "chain_distribution": chain_distribution,
            "method_distribution": method_distribution
        }
        
        # Store individual results
        for i, result in enumerate(task_results):
            task_info = concurrent_tasks[i]
            results[f"request_{i+1}"] = {
                "chain_name": task_info["chain_name"],
                "chain_id": task_info["chain_id"],
                "method": task_info["method"],
                "success": result["success"],
                "latency_ms": result.get("latency_ms", 0),
                "trace_id": result.get("trace_id"),
                "error": result.get("error")
            }
        
        return results
    
    async def test_chain_specific_contract_calls(self) -> Dict:
        """Test chain-specific smart contract interactions"""
        print("📜 Testing Chain-Specific Contract Calls...")
        
        results = {}
        
        for chain_name, chain_config in PRODUCTION_CHAINS.items():
            chain_results = {}
            
            # Test contract code retrieval for chain-specific contracts
            for contract_name, contract_address in chain_config["common_contracts"].items():
                result = await self.make_rpc_call(
                    "eth_getCode", 
                    [contract_address, "latest"],
                    chain_id=chain_config["chain_id"]
                )
                
                chain_results[f"contract_{contract_name}"] = {
                    "contract_name": contract_name,
                    "contract_address": contract_address,
                    "success": result["success"],
                    "has_code": len(result.get("response", {}).get("result", "0x")) > 2,
                    "code_length": len(result.get("response", {}).get("result", "0x")),
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                }
            
            # Test balance queries for known addresses
            for i, address in enumerate(chain_config["test_addresses"]):
                result = await self.make_rpc_call(
                    "eth_getBalance",
                    [address, "latest"],
                    chain_id=chain_config["chain_id"]
                )
                
                chain_results[f"balance_check_{i+1}"] = {
                    "address": address,
                    "success": result["success"],
                    "has_balance": result.get("response", {}).get("result", "0x0") != "0x0",
                    "balance_hex": result.get("response", {}).get("result"),
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                }
            
            results[chain_name] = chain_results
        
        return results
    
    async def test_chain_failover_scenarios(self) -> Dict:
        """Test failover behavior when providers fail for specific chains"""
        print("🔄 Testing Chain-Specific Failover Scenarios...")
        
        results = {}
        
        # Get available providers
        try:
            async with self.session.get(f"{self.proxy_url}/admin/providers") as response:
                if response.status == 200:
                    admin_data = await response.json()
                    available_providers = [p["id"] for p in admin_data.get("providers", [])]
                else:
                    available_providers = ["alchemy", "nodereal_eth", "publicnode_eth"]
        except:
            available_providers = ["alchemy", "nodereal_eth", "publicnode_eth"]
        
        # Test failover by forcing provider selection
        for chain_name, chain_config in PRODUCTION_CHAINS.items():
            chain_results = {}
            
            # Test with each available provider
            for provider in available_providers[:3]:  # Test first 3 providers
                result = await self.make_rpc_call(
                    "eth_chainId",
                    chain_id=chain_config["chain_id"],
                    provider_id=provider
                )
                
                chain_results[f"provider_{provider}"] = {
                    "provider": provider,
                    "success": result["success"],
                    "expected_chain_id": chain_config["expected_chain_id"],
                    "actual_chain_id": result.get("response", {}).get("result"),
                    "chain_matches": result.get("response", {}).get("result") == chain_config["expected_chain_id"],
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id"),
                    "error": result.get("error")
                }
            
            # Test with invalid provider (should failover)
            result = await self.make_rpc_call(
                "eth_chainId",
                chain_id=chain_config["chain_id"],
                provider_id="invalid_provider_12345"
            )
            
            chain_results["invalid_provider_failover"] = {
                "provider": "invalid_provider_12345",
                "success": result["success"],
                "should_failover": True,
                "did_failover": result["success"],  # If successful, failover worked
                "expected_chain_id": chain_config["expected_chain_id"],
                "actual_chain_id": result.get("response", {}).get("result"),
                "latency_ms": result.get("latency_ms", 0),
                "trace_id": result.get("trace_id")
            }
            
            results[chain_name] = chain_results
        
        return results
    
    async def test_chain_method_compatibility(self) -> Dict:
        """Test method compatibility across different chains"""
        print("🔧 Testing Chain Method Compatibility...")
        
        results = {}
        
        # Methods that should work on all EVM chains
        universal_methods = [
            ("eth_chainId", []),
            ("eth_blockNumber", []),
            ("eth_gasPrice", []),
            ("net_version", []),
            ("eth_getBlockByNumber", ["latest", False]),
        ]
        
        # Methods that might have chain-specific behavior
        chain_specific_methods = [
            ("eth_getBalance", ["0x0000000000000000000000000000000000000000", "latest"]),
            ("eth_estimateGas", [{"to": "0x0000000000000000000000000000000000000000", "value": "0x1"}]),
        ]
        
        for chain_name, chain_config in PRODUCTION_CHAINS.items():
            chain_results = {
                "universal_methods": {},
                "chain_specific_methods": {}
            }
            
            # Test universal methods
            for method, params in universal_methods:
                result = await self.make_rpc_call(method, params, chain_id=chain_config["chain_id"])
                chain_results["universal_methods"][method] = {
                    "success": result["success"],
                    "has_result": "result" in result.get("response", {}),
                    "error": result.get("response", {}).get("error"),
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                }
            
            # Test chain-specific methods
            for method, params in chain_specific_methods:
                result = await self.make_rpc_call(method, params, chain_id=chain_config["chain_id"])
                chain_results["chain_specific_methods"][method] = {
                    "success": result["success"],
                    "has_result": "result" in result.get("response", {}),
                    "error": result.get("response", {}).get("error"),
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                }
            
            results[chain_name] = chain_results
        
        return results
    
    async def test_load_balancing_per_chain(self) -> Dict:
        """Test load balancing behavior per chain"""
        print("⚖️ Testing Load Balancing Per Chain...")
        
        results = {}
        
        for chain_name, chain_config in PRODUCTION_CHAINS.items():
            chain_results = []
            provider_usage = {}
            
            # Make multiple requests to see load balancing
            for i in range(20):
                result = await self.make_rpc_call(
                    "eth_blockNumber",
                    chain_id=chain_config["chain_id"]
                )
                
                provider_used = result.get("provider_used", "unknown")
                if provider_used not in provider_usage:
                    provider_usage[provider_used] = 0
                provider_usage[provider_used] += 1
                
                chain_results.append({
                    "request_num": i + 1,
                    "success": result["success"],
                    "provider_used": provider_used,
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                })
                
                # Small delay to avoid overwhelming
                await asyncio.sleep(0.05)
            
            successful_requests = [r for r in chain_results if r["success"]]
            
            results[chain_name] = {
                "total_requests": len(chain_results),
                "successful_requests": len(successful_requests),
                "success_rate": len(successful_requests) / len(chain_results),
                "provider_distribution": provider_usage,
                "unique_providers_used": len(provider_usage),
                "load_balanced": len(provider_usage) > 1,
                "avg_latency_ms": sum(r["latency_ms"] for r in successful_requests) / len(successful_requests) if successful_requests else 0,
                "requests": chain_results
            }
        
        return results

async def main():
    print("🚀 Starting Multi-Chain Routing Scenario Tests")
    print("=" * 70)
    
    async with MultiChainRoutingTester() as tester:
        all_results = {}
        
        # Test 1: Cross-Chain Consistency
        all_results["cross_chain_consistency"] = await tester.test_cross_chain_consistency()
        
        # Test 2: Concurrent Multi-Chain Requests
        all_results["concurrent_requests"] = await tester.test_concurrent_multi_chain_requests()
        
        # Test 3: Chain-Specific Contract Calls
        all_results["contract_calls"] = await tester.test_chain_specific_contract_calls()
        
        # Test 4: Chain Failover Scenarios
        all_results["failover_scenarios"] = await tester.test_chain_failover_scenarios()
        
        # Test 5: Chain Method Compatibility
        all_results["method_compatibility"] = await tester.test_chain_method_compatibility()
        
        # Test 6: Load Balancing Per Chain
        all_results["load_balancing"] = await tester.test_load_balancing_per_chain()
    
    # Print Results Summary
    print("\n" + "=" * 70)
    print("📊 MULTI-CHAIN ROUTING TEST RESULTS SUMMARY")
    print("=" * 70)
    
    # Cross-Chain Consistency
    consistency = all_results["cross_chain_consistency"]
    print(f"\n🌐 CROSS-CHAIN CONSISTENCY:")
    for chain_name, chain_data in consistency.items():
        numeric_match = chain_data.get("numeric_id", {}).get("matches_expected", False)
        alias_matches = sum(1 for k, v in chain_data.items() 
                           if k.startswith("alias_") and v.get("matches_expected", False))
        alias_total = sum(1 for k in chain_data.keys() if k.startswith("alias_"))
        print(f"   {chain_name}: {'✅' if numeric_match else '❌'} numeric, "
              f"{alias_matches}/{alias_total} aliases")
    
    # Concurrent Requests
    concurrent = all_results["concurrent_requests"]["concurrent_summary"]
    success_rate = concurrent.get("success_rate", 0)
    rps = concurrent.get("requests_per_second", 0)
    print(f"\n⚡ CONCURRENT REQUESTS:")
    print(f"   Success Rate: {success_rate:.1%} ({'✅' if success_rate > 0.8 else '❌'})")
    print(f"   Throughput: {rps:.1f} req/s")
    print(f"   Avg Latency: {concurrent.get('avg_latency_ms', 0):.1f}ms")
    
    # Contract Calls
    contracts = all_results["contract_calls"]
    print(f"\n📜 CHAIN-SPECIFIC CONTRACT CALLS:")
    for chain_name, chain_data in contracts.items():
        contract_success = sum(1 for k, v in chain_data.items() 
                              if k.startswith("contract_") and v.get("success", False))
        contract_total = sum(1 for k in chain_data.keys() if k.startswith("contract_"))
        balance_success = sum(1 for k, v in chain_data.items() 
                             if k.startswith("balance_") and v.get("success", False))
        balance_total = sum(1 for k in chain_data.keys() if k.startswith("balance_"))
        print(f"   {chain_name}: {contract_success}/{contract_total} contracts, "
              f"{balance_success}/{balance_total} balances")
    
    # Failover Scenarios
    failover = all_results["failover_scenarios"]
    print(f"\n🔄 FAILOVER SCENARIOS:")
    for chain_name, chain_data in failover.items():
        provider_success = sum(1 for k, v in chain_data.items() 
                              if k.startswith("provider_") and v.get("success", False))
        provider_total = sum(1 for k in chain_data.keys() if k.startswith("provider_"))
        failover_worked = chain_data.get("invalid_provider_failover", {}).get("did_failover", False)
        print(f"   {chain_name}: {provider_success}/{provider_total} providers, "
              f"failover: {'✅' if failover_worked else '❌'}")
    
    # Method Compatibility
    methods = all_results["method_compatibility"]
    print(f"\n🔧 METHOD COMPATIBILITY:")
    for chain_name, chain_data in methods.items():
        universal_success = sum(1 for v in chain_data["universal_methods"].values() 
                               if v.get("success", False))
        universal_total = len(chain_data["universal_methods"])
        specific_success = sum(1 for v in chain_data["chain_specific_methods"].values() 
                              if v.get("success", False))
        specific_total = len(chain_data["chain_specific_methods"])
        print(f"   {chain_name}: {universal_success}/{universal_total} universal, "
              f"{specific_success}/{specific_total} specific")
    
    # Load Balancing
    balancing = all_results["load_balancing"]
    print(f"\n⚖️ LOAD BALANCING:")
    for chain_name, chain_data in balancing.items():
        success_rate = chain_data.get("success_rate", 0)
        is_balanced = chain_data.get("load_balanced", False)
        unique_providers = chain_data.get("unique_providers_used", 0)
        print(f"   {chain_name}: {'✅' if success_rate > 0.8 else '❌'} "
              f"({success_rate:.1%} success, {unique_providers} providers, "
              f"balanced: {'✅' if is_balanced else '❌'})")
    
    print(f"\n📋 Detailed results saved to chainid_multichain_test_results.json")
    
    # Save detailed results
    with open("chainid_multichain_test_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print("\n✅ All multi-chain routing tests completed!")
    
    # Summary statistics
    total_scenarios = sum(len(category) if isinstance(category, dict) else 1 
                         for category in all_results.values())
    print(f"\n📈 SUMMARY: {total_scenarios} total test scenarios executed across multiple chains")

if __name__ == "__main__":
    asyncio.run(main())
