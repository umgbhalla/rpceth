#!/usr/bin/env python3
"""
Comprehensive RPC Proxy Tests with Realistic Ethereum Scenarios
Tests ERC20 tokens, wallet balances, transaction data, and more complex scenarios
"""

import asyncio
import aiohttp
import json
import time
import random
from typing import Dict, List, Any
from dataclasses import dataclass

# Well-known Ethereum addresses and contracts for testing
USDC_CONTRACT = "0xA0b86a33E6441E2a3B4E6b6A6C4B3C3B3A8B8B8B"  # USDC on mainnet
VITALIK_ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"  # Vitalik's address
UNISWAP_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
WETH_CONTRACT = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

@dataclass
class TestScenario:
    name: str
    description: str
    requests: List[Dict[str, Any]]
    expected_traces: int
    complexity: str  # "simple", "medium", "complex"

class RealEthereumRPCTester:
    def __init__(self, proxy_url: str = "http://localhost:3000", api_key: str = "change-me"):
        self.proxy_url = proxy_url
        self.api_key = api_key
        self.session = None
        self.test_results = []
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def send_rpc_request(self, method: str, params: List[Any], request_id: int = None) -> Dict:
        """Send a JSON-RPC request through the proxy"""
        if request_id is None:
            request_id = random.randint(1, 1000000)
            
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id
        }
        
        headers = {
            "Content-Type": "application/json",
            "x-xray-id": f"test-{method}-{request_id}-{int(time.time())}"
        }
        
        start_time = time.time()
        async with self.session.post(f"{self.proxy_url}/?apikey={self.api_key}", json=payload, headers=headers) as response:
            result = await response.json()
            duration = time.time() - start_time
            
            return {
                "request": payload,
                "response": result,
                "duration": duration,
                "status_code": response.status,
                "trace_id": headers["x-xray-id"]
            }
    
    def create_test_scenarios(self) -> List[TestScenario]:
        """Create comprehensive test scenarios covering various Ethereum use cases"""
        
        scenarios = [
            # Simple scenarios
            TestScenario(
                name="basic_network_info",
                description="Basic network information queries",
                requests=[
                    {"method": "eth_chainId", "params": []},
                    {"method": "eth_blockNumber", "params": []},
                    {"method": "net_version", "params": []},
                    {"method": "eth_gasPrice", "params": []},
                ],
                expected_traces=4,
                complexity="simple"
            ),
            
            # Medium complexity - wallet and balance queries
            TestScenario(
                name="wallet_balance_queries",
                description="Query balances for well-known addresses",
                requests=[
                    {"method": "eth_getBalance", "params": [VITALIK_ADDRESS, "latest"]},
                    {"method": "eth_getTransactionCount", "params": [VITALIK_ADDRESS, "latest"]},
                    {"method": "eth_getCode", "params": [USDC_CONTRACT, "latest"]},
                    {"method": "eth_getStorageAt", "params": [USDC_CONTRACT, "0x0", "latest"]},
                ],
                expected_traces=4,
                complexity="medium"
            ),
            
            # ERC20 token queries
            TestScenario(
                name="erc20_token_queries",
                description="ERC20 token contract interactions",
                requests=[
                    # Get USDC total supply
                    {"method": "eth_call", "params": [{
                        "to": USDC_CONTRACT,
                        "data": "0x18160ddd"  # totalSupply()
                    }, "latest"]},
                    # Get USDC decimals
                    {"method": "eth_call", "params": [{
                        "to": USDC_CONTRACT,
                        "data": "0x313ce567"  # decimals()
                    }, "latest"]},
                    # Get USDC name
                    {"method": "eth_call", "params": [{
                        "to": USDC_CONTRACT,
                        "data": "0x06fdde03"  # name()
                    }, "latest"]},
                    # Get USDC symbol
                    {"method": "eth_call", "params": [{
                        "to": USDC_CONTRACT,
                        "data": "0x95d89b41"  # symbol()
                    }, "latest"]},
                    # Get Vitalik's USDC balance
                    {"method": "eth_call", "params": [{
                        "to": USDC_CONTRACT,
                        "data": f"0x70a08231000000000000000000000000{VITALIK_ADDRESS[2:]}"  # balanceOf(address)
                    }, "latest"]},
                ],
                expected_traces=5,
                complexity="medium"
            ),
            
            # Complex scenario - block and transaction analysis
            TestScenario(
                name="block_transaction_analysis",
                description="Analyze recent blocks and transactions",
                requests=[
                    {"method": "eth_blockNumber", "params": []},
                    # Will be filled dynamically with recent block data
                ],
                expected_traces=6,  # Will be updated based on dynamic requests
                complexity="complex"
            ),
            
            # Load testing scenario
            TestScenario(
                name="concurrent_requests",
                description="Test concurrent request handling",
                requests=[
                    {"method": "eth_blockNumber", "params": []} for _ in range(10)
                ] + [
                    {"method": "eth_gasPrice", "params": []} for _ in range(5)
                ] + [
                    {"method": "eth_getBalance", "params": [VITALIK_ADDRESS, "latest"]} for _ in range(3)
                ],
                expected_traces=18,
                complexity="complex"
            ),
            
            # Error handling scenarios
            TestScenario(
                name="error_handling",
                description="Test various error conditions",
                requests=[
                    {"method": "eth_getBalance", "params": ["0xinvalid", "latest"]},  # Invalid address
                    {"method": "eth_getBlockByNumber", "params": ["0xffffffff", False]},  # Non-existent block
                    {"method": "nonexistent_method", "params": []},  # Invalid method
                    {"method": "eth_call", "params": [{
                        "to": "0x0000000000000000000000000000000000000000",
                        "data": "0x12345678"
                    }, "latest"]},  # Call to zero address
                ],
                expected_traces=4,
                complexity="medium"
            )
        ]
        
        return scenarios
    
    async def enhance_block_scenario(self, scenario: TestScenario):
        """Enhance the block analysis scenario with real block data"""
        try:
            # Get current block number
            block_response = await self.send_rpc_request("eth_blockNumber", [])
            if "result" in block_response["response"]:
                current_block = int(block_response["response"]["result"], 16)
                recent_block = hex(current_block - 1)
                
                # Add dynamic requests
                additional_requests = [
                    {"method": "eth_getBlockByNumber", "params": [recent_block, False]},
                    {"method": "eth_getBlockByNumber", "params": [recent_block, True]},
                    {"method": "eth_getBlockTransactionCountByNumber", "params": [recent_block]},
                    {"method": "eth_getUncleCountByBlockNumber", "params": [recent_block]},
                ]
                
                scenario.requests.extend(additional_requests)
                scenario.expected_traces = len(scenario.requests)
                
        except Exception as e:
            print(f"Warning: Could not enhance block scenario: {e}")
    
    async def run_scenario(self, scenario: TestScenario) -> Dict[str, Any]:
        """Run a single test scenario"""
        print(f"\n🧪 Running scenario: {scenario.name}")
        print(f"   Description: {scenario.description}")
        print(f"   Complexity: {scenario.complexity}")
        print(f"   Requests: {len(scenario.requests)}")
        
        # Enhance dynamic scenarios
        if scenario.name == "block_transaction_analysis":
            await self.enhance_block_scenario(scenario)
        
        results = []
        start_time = time.time()
        
        # Handle concurrent vs sequential execution
        if scenario.name == "concurrent_requests":
            # Run requests concurrently
            tasks = []
            for i, req in enumerate(scenario.requests):
                task = self.send_rpc_request(req["method"], req["params"], i + 1)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            # Run requests sequentially
            for i, req in enumerate(scenario.requests):
                try:
                    result = await self.send_rpc_request(req["method"], req["params"], i + 1)
                    results.append(result)
                    
                    # Small delay between requests to see trace separation
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    results.append({"error": str(e), "request": req})
        
        total_duration = time.time() - start_time
        
        # Analyze results
        successful_requests = sum(1 for r in results if isinstance(r, dict) and "error" not in r and r.get("status_code") == 200)
        failed_requests = len(results) - successful_requests
        avg_duration = sum(r.get("duration", 0) for r in results if isinstance(r, dict) and "duration" in r) / len(results) if results else 0
        
        scenario_result = {
            "scenario": scenario.name,
            "description": scenario.description,
            "complexity": scenario.complexity,
            "total_requests": len(scenario.requests),
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "total_duration": total_duration,
            "avg_request_duration": avg_duration,
            "expected_traces": scenario.expected_traces,
            "results": results[:3] if len(results) > 3 else results,  # Limit output
            "trace_ids": [r.get("trace_id") for r in results if isinstance(r, dict) and "trace_id" in r]
        }
        
        print(f"   ✅ Completed: {successful_requests}/{len(scenario.requests)} successful")
        print(f"   ⏱️  Duration: {total_duration:.2f}s (avg: {avg_duration:.3f}s per request)")
        
        return scenario_result
    
    async def run_all_scenarios(self) -> Dict[str, Any]:
        """Run all test scenarios"""
        print("🚀 Starting Comprehensive RPC Proxy Tests")
        print("=" * 60)
        
        scenarios = self.create_test_scenarios()
        all_results = []
        
        total_start = time.time()
        
        for scenario in scenarios:
            try:
                result = await self.run_scenario(scenario)
                all_results.append(result)
                
                # Brief pause between scenarios
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"❌ Scenario {scenario.name} failed: {e}")
                all_results.append({
                    "scenario": scenario.name,
                    "error": str(e),
                    "failed": True
                })
        
        total_duration = time.time() - total_start
        
        # Summary
        successful_scenarios = sum(1 for r in all_results if not r.get("failed", False))
        total_requests = sum(r.get("total_requests", 0) for r in all_results)
        total_successful_requests = sum(r.get("successful_requests", 0) for r in all_results)
        total_traces = sum(r.get("expected_traces", 0) for r in all_results)
        
        summary = {
            "test_run_summary": {
                "total_scenarios": len(scenarios),
                "successful_scenarios": successful_scenarios,
                "failed_scenarios": len(scenarios) - successful_scenarios,
                "total_requests": total_requests,
                "successful_requests": total_successful_requests,
                "expected_traces": total_traces,
                "total_duration": total_duration,
                "timestamp": time.time()
            },
            "scenario_results": all_results
        }
        
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print(f"   Scenarios: {successful_scenarios}/{len(scenarios)} successful")
        print(f"   Requests: {total_successful_requests}/{total_requests} successful")
        print(f"   Expected traces: {total_traces}")
        print(f"   Total duration: {total_duration:.2f}s")
        print(f"   Jaeger UI: http://localhost:16686")
        
        return summary

async def main():
    """Main test runner"""
    async with RealEthereumRPCTester() as tester:
        results = await tester.run_all_scenarios()
        
        # Save results to file
        with open("realistic_rpc_test_results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: realistic_rpc_test_results.json")
        
        # Print trace IDs for easy Jaeger lookup
        print("\n🔍 Trace IDs for Jaeger investigation:")
        for scenario in results["scenario_results"]:
            if "trace_ids" in scenario and scenario["trace_ids"]:
                print(f"   {scenario['scenario']}: {len(scenario['trace_ids'])} traces")
                for trace_id in scenario["trace_ids"][:3]:  # Show first 3
                    if trace_id:
                        print(f"     - {trace_id}")

if __name__ == "__main__":
    asyncio.run(main())
