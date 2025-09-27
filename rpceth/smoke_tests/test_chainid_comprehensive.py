#!/usr/bin/env python3
"""
Comprehensive Chain ID Parameter Route Testing
Tests multi-chain routing, chain-specific provider selection, and chain validation
"""

import asyncio
import aiohttp
import json
import time
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# Chain ID mappings for testing
CHAIN_MAPPINGS = {
    # Ethereum Mainnet
    "1": {"name": "ethereum", "aliases": ["eth", "ethereum", "mainnet"], "expected_chain_id": "0x1"},
    # Polygon
    "137": {"name": "polygon", "aliases": ["polygon", "matic"], "expected_chain_id": "0x89"},
    # Binance Smart Chain
    "56": {"name": "bsc", "aliases": ["bsc", "binance"], "expected_chain_id": "0x38"},
    # Arbitrum One
    "42161": {"name": "arbitrum", "aliases": ["arbitrum", "arb"], "expected_chain_id": "0xa4b1"},
    # Optimism
    "10": {"name": "optimism", "aliases": ["optimism", "op"], "expected_chain_id": "0xa"},
    # Avalanche C-Chain
    "43114": {"name": "avalanche", "aliases": ["avalanche", "avax"], "expected_chain_id": "0xa86a"},
}

@dataclass
class ChainTestScenario:
    chain_id: str
    aliases: List[str]
    expected_chain_id: str
    test_methods: List[str]
    should_succeed: bool
    description: str

class ChainIDRoutingTester:
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
                           expect_error: bool = False) -> Dict:
        """Make an RPC call with optional chain ID routing"""
        if params is None:
            params = []
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": random.randint(1, 1000000)
        }
        
        # Build URL path
        path = "/"
        if chain_id:
            path = f"/{chain_id}"
        
        # Build query parameters
        query_params = [f"apikey={self.api_key}"]
        if provider_id:
            query_params.append(f"provider_id={provider_id}")
        
        url = f"{self.proxy_url}{path}?{'&'.join(query_params)}"
        
        headers = {
            "Content-Type": "application/json",
            "x-test-id": f"chainid-{chain_id or 'default'}-{method}-{int(time.time())}"
        }
        
        start_time = time.time()
        
        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                latency = time.time() - start_time
                
                try:
                    response_data = await response.json()
                except:
                    response_data = {"error": {"code": -32700, "message": f"HTTP {response.status}"}}
                
                return {
                    "success": response.status == 200 and "result" in response_data,
                    "status_code": response.status,
                    "response": response_data,
                    "latency_ms": latency * 1000,
                    "trace_id": response.headers.get('x-trace-id', 'NO_TRACE_ID'),
                    "url": url,
                    "chain_id": chain_id,
                    "method": method,
                    "request_payload": payload
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
    
    async def test_basic_chain_routing(self) -> Dict:
        """Test basic chain ID routing functionality"""
        print("🔗 Testing Basic Chain ID Routing...")
        
        results = {}
        
        # Test default route (no chain ID)
        result = await self.make_rpc_call("eth_chainId")
        results["default_route"] = {
            "success": result["success"],
            "status_code": result["status_code"],
            "path": "/",
            "actual_chain_id": result.get("response", {}).get("result"),
            "trace_id": result.get("trace_id"),
            "latency_ms": result.get("latency_ms", 0)
        }
        
        # Test numeric chain IDs
        for chain_id, chain_info in CHAIN_MAPPINGS.items():
            result = await self.make_rpc_call("eth_chainId", chain_id=chain_id)
            results[f"numeric_chain_{chain_id}"] = {
                "success": result["success"],
                "status_code": result["status_code"],
                "requested_chain": chain_id,
                "expected_chain_id": chain_info["expected_chain_id"],
                "actual_chain_id": result.get("response", {}).get("result"),
                "chain_matches": result.get("response", {}).get("result") == chain_info["expected_chain_id"],
                "path": f"/{chain_id}",
                "trace_id": result.get("trace_id"),
                "latency_ms": result.get("latency_ms", 0)
            }
        
        return results
    
    async def test_chain_aliases(self) -> Dict:
        """Test chain ID aliases (eth, polygon, bsc, etc.)"""
        print("🏷️ Testing Chain ID Aliases...")
        
        results = {}
        
        for chain_id, chain_info in CHAIN_MAPPINGS.items():
            for alias in chain_info["aliases"]:
                result = await self.make_rpc_call("eth_chainId", chain_id=alias)
                results[f"alias_{alias}"] = {
                    "success": result["success"],
                    "status_code": result["status_code"],
                    "alias": alias,
                    "maps_to_chain": chain_id,
                    "expected_chain_id": chain_info["expected_chain_id"],
                    "actual_chain_id": result.get("response", {}).get("result"),
                    "alias_works": result.get("response", {}).get("result") == chain_info["expected_chain_id"],
                    "path": f"/{alias}",
                    "trace_id": result.get("trace_id"),
                    "latency_ms": result.get("latency_ms", 0)
                }
        
        return results
    
    async def test_chain_specific_methods(self) -> Dict:
        """Test various RPC methods with different chain IDs"""
        print("⚙️ Testing Chain-Specific RPC Methods...")
        
        results = {}
        
        # Methods to test across different chains
        test_methods = [
            ("eth_blockNumber", []),
            ("eth_gasPrice", []),
            ("net_version", []),
            ("eth_getBalance", ["0x0000000000000000000000000000000000000000", "latest"]),
            ("eth_getBlockByNumber", ["latest", False]),
        ]
        
        # Test a subset of chains to avoid too many requests
        test_chains = ["1", "137", "56", "eth", "polygon", "bsc"]
        
        for chain in test_chains:
            chain_results = {}
            
            for method, params in test_methods:
                result = await self.make_rpc_call(method, params, chain_id=chain)
                chain_results[method] = {
                    "success": result["success"],
                    "status_code": result["status_code"],
                    "has_result": "result" in result.get("response", {}),
                    "error": result.get("response", {}).get("error"),
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                }
            
            results[f"chain_{chain}"] = chain_results
        
        return results
    
    async def test_invalid_chain_ids(self) -> Dict:
        """Test behavior with invalid or unsupported chain IDs"""
        print("❌ Testing Invalid Chain IDs...")
        
        results = {}
        
        invalid_chains = [
            "999999",  # Non-existent numeric chain
            "invalid",  # Invalid string
            "eth2",     # Non-standard alias
            "0x999",    # Hex format (should be decimal)
            "",         # Empty string
            "chain-1",  # Invalid format
            "999999999999999999999",  # Extremely large number
        ]
        
        for invalid_chain in invalid_chains:
            result = await self.make_rpc_call("eth_chainId", chain_id=invalid_chain)
            results[f"invalid_{invalid_chain or 'empty'}"] = {
                "chain_id": invalid_chain,
                "success": result["success"],
                "status_code": result["status_code"],
                "response": result.get("response", {}),
                "should_fail": True,
                "actually_failed": not result["success"] or result["status_code"] >= 400,
                "trace_id": result.get("trace_id"),
                "latency_ms": result.get("latency_ms", 0)
            }
        
        return results
    
    async def test_chain_provider_combinations(self) -> Dict:
        """Test chain ID routing combined with provider overrides"""
        print("🔄 Testing Chain ID + Provider Override Combinations...")
        
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
        
        # Test combinations of chains and providers
        test_combinations = [
            {"chain": "1", "provider": available_providers[0] if available_providers else "alchemy"},
            {"chain": "eth", "provider": available_providers[1] if len(available_providers) > 1 else "nodereal_eth"},
            {"chain": "137", "provider": available_providers[0] if available_providers else "alchemy"},
            {"chain": "polygon", "provider": available_providers[1] if len(available_providers) > 1 else "nodereal_eth"},
        ]
        
        for i, combo in enumerate(test_combinations):
            result = await self.make_rpc_call(
                "eth_chainId", 
                chain_id=combo["chain"], 
                provider_id=combo["provider"]
            )
            
            results[f"combo_{i+1}"] = {
                "chain_id": combo["chain"],
                "provider_id": combo["provider"],
                "success": result["success"],
                "status_code": result["status_code"],
                "actual_chain_id": result.get("response", {}).get("result"),
                "url": result.get("url"),
                "trace_id": result.get("trace_id"),
                "latency_ms": result.get("latency_ms", 0)
            }
        
        return results
    
    async def test_chain_consistency(self) -> Dict:
        """Test that the same chain ID returns consistent results"""
        print("🔄 Testing Chain ID Consistency...")
        
        results = {}
        
        # Test consistency for a few chains
        test_chains = ["1", "eth", "137", "polygon"]
        
        for chain in test_chains:
            chain_results = []
            
            # Make multiple requests to the same chain
            for i in range(5):
                result = await self.make_rpc_call("eth_chainId", chain_id=chain)
                chain_results.append({
                    "attempt": i + 1,
                    "success": result["success"],
                    "chain_id_result": result.get("response", {}).get("result"),
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                })
                
                # Small delay between requests
                await asyncio.sleep(0.1)
            
            # Analyze consistency
            chain_ids = [r["chain_id_result"] for r in chain_results if r["success"]]
            consistent = len(set(chain_ids)) <= 1 if chain_ids else False
            
            results[f"chain_{chain}_consistency"] = {
                "chain": chain,
                "attempts": chain_results,
                "consistent_results": consistent,
                "unique_chain_ids": list(set(chain_ids)),
                "success_rate": sum(1 for r in chain_results if r["success"]) / len(chain_results),
                "avg_latency_ms": sum(r["latency_ms"] for r in chain_results) / len(chain_results)
            }
        
        return results
    
    async def test_chain_performance(self) -> Dict:
        """Test performance characteristics of chain routing"""
        print("⚡ Testing Chain Routing Performance...")
        
        results = {}
        
        # Performance test scenarios
        scenarios = [
            {"name": "default_route", "chain_id": None, "requests": 10},
            {"name": "numeric_chain", "chain_id": "1", "requests": 10},
            {"name": "alias_chain", "chain_id": "eth", "requests": 10},
            {"name": "mixed_chains", "chain_id": "random", "requests": 20},  # Will randomize
        ]
        
        for scenario in scenarios:
            scenario_results = []
            start_time = time.time()
            
            for i in range(scenario["requests"]):
                chain_id = scenario["chain_id"]
                if chain_id == "random":
                    # Randomize between different chains
                    chain_id = random.choice(["1", "137", "56", "eth", "polygon", "bsc"])
                
                result = await self.make_rpc_call("eth_blockNumber", chain_id=chain_id)
                scenario_results.append({
                    "request_num": i + 1,
                    "chain_used": chain_id,
                    "success": result["success"],
                    "latency_ms": result.get("latency_ms", 0),
                    "trace_id": result.get("trace_id")
                })
            
            total_time = time.time() - start_time
            successful_requests = [r for r in scenario_results if r["success"]]
            
            results[scenario["name"]] = {
                "total_requests": scenario["requests"],
                "successful_requests": len(successful_requests),
                "success_rate": len(successful_requests) / scenario["requests"],
                "total_time_seconds": total_time,
                "requests_per_second": scenario["requests"] / total_time,
                "avg_latency_ms": sum(r["latency_ms"] for r in successful_requests) / len(successful_requests) if successful_requests else 0,
                "min_latency_ms": min(r["latency_ms"] for r in successful_requests) if successful_requests else 0,
                "max_latency_ms": max(r["latency_ms"] for r in successful_requests) if successful_requests else 0,
                "requests": scenario_results
            }
        
        return results

async def main():
    print("🚀 Starting Comprehensive Chain ID Routing Tests")
    print("=" * 70)
    
    async with ChainIDRoutingTester() as tester:
        all_results = {}
        
        # Test 1: Basic Chain Routing
        all_results["basic_routing"] = await tester.test_basic_chain_routing()
        
        # Test 2: Chain Aliases
        all_results["chain_aliases"] = await tester.test_chain_aliases()
        
        # Test 3: Chain-Specific Methods
        all_results["chain_methods"] = await tester.test_chain_specific_methods()
        
        # Test 4: Invalid Chain IDs
        all_results["invalid_chains"] = await tester.test_invalid_chain_ids()
        
        # Test 5: Chain + Provider Combinations
        all_results["chain_provider_combos"] = await tester.test_chain_provider_combinations()
        
        # Test 6: Chain Consistency
        all_results["chain_consistency"] = await tester.test_chain_consistency()
        
        # Test 7: Performance Testing
        all_results["performance"] = await tester.test_chain_performance()
    
    # Print Results Summary
    print("\n" + "=" * 70)
    print("📊 CHAIN ID ROUTING TEST RESULTS SUMMARY")
    print("=" * 70)
    
    # Basic Routing Results
    basic = all_results["basic_routing"]
    print(f"\n🔗 BASIC CHAIN ROUTING:")
    print(f"   Default Route: {'✅' if basic.get('default_route', {}).get('success', False) else '❌'}")
    
    numeric_success = sum(1 for k, v in basic.items() 
                         if k.startswith('numeric_chain_') and v.get('success', False))
    numeric_total = sum(1 for k in basic.keys() if k.startswith('numeric_chain_'))
    print(f"   Numeric Chain IDs: {numeric_success}/{numeric_total} ({'✅' if numeric_success == numeric_total else '❌'})")
    
    # Chain Aliases Results
    aliases = all_results["chain_aliases"]
    alias_success = sum(1 for k, v in aliases.items() 
                       if k.startswith('alias_') and v.get('success', False))
    alias_total = sum(1 for k in aliases.keys() if k.startswith('alias_'))
    print(f"\n🏷️ CHAIN ALIASES:")
    print(f"   Working Aliases: {alias_success}/{alias_total} ({'✅' if alias_success > 0 else '❌'})")
    
    # Chain Methods Results
    methods = all_results["chain_methods"]
    print(f"\n⚙️ CHAIN-SPECIFIC METHODS:")
    for chain_key, chain_data in methods.items():
        if chain_key.startswith('chain_'):
            chain_name = chain_key.replace('chain_', '')
            method_success = sum(1 for method_data in chain_data.values() if method_data.get('success', False))
            method_total = len(chain_data)
            print(f"   {chain_name}: {method_success}/{method_total} methods working")
    
    # Invalid Chains Results
    invalid = all_results["invalid_chains"]
    print(f"\n❌ INVALID CHAIN HANDLING:")
    properly_failed = sum(1 for k, v in invalid.items() 
                         if k.startswith('invalid_') and v.get('actually_failed', False))
    total_invalid = sum(1 for k in invalid.keys() if k.startswith('invalid_'))
    print(f"   Properly Rejected: {properly_failed}/{total_invalid} ({'✅' if properly_failed > 0 else '❌'})")
    
    # Chain + Provider Combinations
    combos = all_results["chain_provider_combos"]
    combo_success = sum(1 for k, v in combos.items() 
                       if k.startswith('combo_') and v.get('success', False))
    combo_total = sum(1 for k in combos.keys() if k.startswith('combo_'))
    print(f"\n🔄 CHAIN + PROVIDER COMBINATIONS:")
    print(f"   Working Combinations: {combo_success}/{combo_total} ({'✅' if combo_success > 0 else '❌'})")
    
    # Consistency Results
    consistency = all_results["chain_consistency"]
    print(f"\n🔄 CHAIN CONSISTENCY:")
    for chain_key, chain_data in consistency.items():
        if chain_key.endswith('_consistency'):
            chain_name = chain_key.replace('_consistency', '').replace('chain_', '')
            is_consistent = chain_data.get('consistent_results', False)
            success_rate = chain_data.get('success_rate', 0)
            print(f"   {chain_name}: {'✅' if is_consistent and success_rate > 0.8 else '❌'} "
                  f"(consistent: {is_consistent}, success: {success_rate:.1%})")
    
    # Performance Results
    performance = all_results["performance"]
    print(f"\n⚡ PERFORMANCE:")
    for scenario_name, scenario_data in performance.items():
        success_rate = scenario_data.get('success_rate', 0)
        avg_latency = scenario_data.get('avg_latency_ms', 0)
        rps = scenario_data.get('requests_per_second', 0)
        print(f"   {scenario_name}: {'✅' if success_rate > 0.8 else '❌'} "
              f"({success_rate:.1%} success, {avg_latency:.1f}ms avg, {rps:.1f} req/s)")
    
    print(f"\n📋 Detailed results saved to chainid_comprehensive_test_results.json")
    
    # Save detailed results
    with open("chainid_comprehensive_test_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print("\n✅ All Chain ID routing tests completed!")
    
    # Summary statistics
    total_tests = sum(len(category) for category in all_results.values() if isinstance(category, dict))
    print(f"\n📈 SUMMARY: {total_tests} total test scenarios executed")

if __name__ == "__main__":
    asyncio.run(main())
