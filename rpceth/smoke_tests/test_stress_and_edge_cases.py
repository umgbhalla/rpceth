#!/usr/bin/env python3
"""
Stress Testing and Edge Cases for RPC Proxy
Tests failover, retries, timeouts, and complex scenarios
"""

import asyncio
import aiohttp
import json
import time
import random
from typing import Dict, List, Any

class StressAndEdgeCaseTester:
    def __init__(self, proxy_url: str = "http://localhost:3000", api_key: str = "change-me"):
        self.proxy_url = proxy_url
        self.api_key = api_key
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def send_rpc_request(self, method: str, params: List[Any], trace_id: str = None) -> Dict:
        """Send a JSON-RPC request through the proxy"""
        if trace_id is None:
            trace_id = f"stress-{method}-{random.randint(1000, 9999)}-{int(time.time())}"
            
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": random.randint(1, 1000000)
        }
        
        headers = {
            "Content-Type": "application/json",
            "x-xray-id": trace_id
        }
        
        start_time = time.time()
        try:
            async with self.session.post(f"{self.proxy_url}/?apikey={self.api_key}", json=payload, headers=headers) as response:
                result = await response.json()
                duration = time.time() - start_time
                
                return {
                    "request": payload,
                    "response": result,
                    "duration": duration,
                    "status_code": response.status,
                    "trace_id": trace_id,
                    "success": response.status == 200 and "result" in result
                }
        except Exception as e:
            return {
                "request": payload,
                "error": str(e),
                "duration": time.time() - start_time,
                "trace_id": trace_id,
                "success": False
            }
    
    async def test_concurrent_load(self, num_requests: int = 50) -> Dict[str, Any]:
        """Test high concurrent load"""
        print(f"🔥 Testing concurrent load with {num_requests} requests...")
        
        # Mix of different request types
        methods = [
            ("eth_blockNumber", []),
            ("eth_gasPrice", []),
            ("eth_chainId", []),
            ("net_version", []),
            ("eth_getBalance", ["0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "latest"]),
        ]
        
        tasks = []
        start_time = time.time()
        
        for i in range(num_requests):
            method, params = random.choice(methods)
            trace_id = f"load-test-{i}-{int(time.time())}"
            task = self.send_rpc_request(method, params, trace_id)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_duration = time.time() - start_time
        
        successful = sum(1 for r in results if isinstance(r, dict) and r.get("success", False))
        failed = len(results) - successful
        avg_duration = sum(r.get("duration", 0) for r in results if isinstance(r, dict)) / len(results)
        
        print(f"   ✅ Completed: {successful}/{num_requests} successful")
        print(f"   ⏱️  Total: {total_duration:.2f}s, Avg: {avg_duration:.3f}s per request")
        print(f"   🚀 Throughput: {num_requests/total_duration:.1f} req/s")
        
        return {
            "test": "concurrent_load",
            "total_requests": num_requests,
            "successful": successful,
            "failed": failed,
            "total_duration": total_duration,
            "avg_duration": avg_duration,
            "throughput": num_requests / total_duration,
            "trace_ids": [r.get("trace_id") for r in results if isinstance(r, dict)][:10]  # First 10
        }
    
    async def test_complex_eth_calls(self) -> Dict[str, Any]:
        """Test complex eth_call scenarios that might stress the system"""
        print("🧠 Testing complex eth_call scenarios...")
        
        # Complex contract calls that might take longer
        complex_calls = [
            # Uniswap V3 factory - get pool
            {
                "method": "eth_call",
                "params": [{
                    "to": "0x1F98431c8aD98523631AE4a59f267346ea31F984",  # Uniswap V3 Factory
                    "data": "0x1698ee82000000000000000000000000a0b86a33e6441e2a3b4e6b6a6c4b3c3b3a8b8b8b000000000000000000000000c02aaa39b223fe8d0a0e5c4f27ead9083c756cc20000000000000000000000000000000000000000000000000000000000000bb8"
                }, "latest"]
            },
            # ENS resolver
            {
                "method": "eth_call", 
                "params": [{
                    "to": "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e",  # ENS Registry
                    "data": "0x0178b8bf0000000000000000000000000000000000000000000000000000000000000000"
                }, "latest"]
            },
            # Large data call - get many storage slots
            {
                "method": "eth_call",
                "params": [{
                    "to": "0xA0b86a33E6441E2a3B4E6b6A6C4B3C3B3A8B8B8B",
                    "data": "0x" + "0" * 1000  # Large data payload
                }, "latest"]
            }
        ]
        
        results = []
        start_time = time.time()
        
        for i, call in enumerate(complex_calls):
            trace_id = f"complex-call-{i}-{int(time.time())}"
            result = await self.send_rpc_request(call["method"], call["params"], trace_id)
            results.append(result)
            await asyncio.sleep(0.5)  # Brief pause between complex calls
        
        total_duration = time.time() - start_time
        successful = sum(1 for r in results if r.get("success", False))
        
        print(f"   ✅ Completed: {successful}/{len(complex_calls)} successful")
        print(f"   ⏱️  Duration: {total_duration:.2f}s")
        
        return {
            "test": "complex_eth_calls",
            "total_requests": len(complex_calls),
            "successful": successful,
            "failed": len(complex_calls) - successful,
            "total_duration": total_duration,
            "trace_ids": [r.get("trace_id") for r in results]
        }
    
    async def test_error_scenarios(self) -> Dict[str, Any]:
        """Test various error scenarios to verify error handling and tracing"""
        print("❌ Testing error scenarios...")
        
        error_scenarios = [
            # Invalid JSON-RPC
            ("invalid_method", []),
            # Invalid parameters
            ("eth_getBalance", ["not_an_address", "latest"]),
            ("eth_getBlockByNumber", ["not_a_number", False]),
            # Non-existent resources
            ("eth_getTransactionByHash", ["0x" + "0" * 64]),
            ("eth_getBlockByHash", ["0x" + "f" * 64, False]),
            # Calls that should fail
            ("eth_call", [{"to": "0x0000000000000000000000000000000000000000", "data": "0xdeadbeef"}, "latest"]),
        ]
        
        results = []
        start_time = time.time()
        
        for i, (method, params) in enumerate(error_scenarios):
            trace_id = f"error-test-{i}-{int(time.time())}"
            result = await self.send_rpc_request(method, params, trace_id)
            results.append(result)
            await asyncio.sleep(0.2)
        
        total_duration = time.time() - start_time
        
        # For error scenarios, we expect some to "succeed" (return error responses) and some to fail
        responses_received = sum(1 for r in results if "response" in r)
        
        print(f"   ✅ Responses received: {responses_received}/{len(error_scenarios)}")
        print(f"   ⏱️  Duration: {total_duration:.2f}s")
        
        return {
            "test": "error_scenarios", 
            "total_requests": len(error_scenarios),
            "responses_received": responses_received,
            "total_duration": total_duration,
            "trace_ids": [r.get("trace_id") for r in results]
        }
    
    async def test_burst_patterns(self) -> Dict[str, Any]:
        """Test burst traffic patterns"""
        print("💥 Testing burst traffic patterns...")
        
        results = []
        
        # Pattern 1: Quick burst
        print("   Phase 1: Quick burst (20 requests in 2 seconds)")
        burst_tasks = []
        for i in range(20):
            trace_id = f"burst-quick-{i}-{int(time.time())}"
            task = self.send_rpc_request("eth_blockNumber", [], trace_id)
            burst_tasks.append(task)
        
        burst_start = time.time()
        burst_results = await asyncio.gather(*burst_tasks)
        burst_duration = time.time() - burst_start
        results.extend(burst_results)
        
        print(f"      ✅ Burst completed in {burst_duration:.2f}s")
        
        # Brief cooldown
        await asyncio.sleep(2)
        
        # Pattern 2: Sustained load
        print("   Phase 2: Sustained load (30 requests over 10 seconds)")
        sustained_start = time.time()
        for i in range(30):
            trace_id = f"burst-sustained-{i}-{int(time.time())}"
            result = await self.send_rpc_request("eth_gasPrice", [], trace_id)
            results.append(result)
            await asyncio.sleep(0.33)  # ~3 requests per second
        
        sustained_duration = time.time() - sustained_start
        
        total_duration = burst_duration + 2 + sustained_duration  # Include cooldown
        successful = sum(1 for r in results if isinstance(r, dict) and r.get("success", False))
        
        print(f"   ✅ Total: {successful}/{len(results)} successful")
        print(f"   ⏱️  Total duration: {total_duration:.2f}s")
        
        return {
            "test": "burst_patterns",
            "total_requests": len(results),
            "successful": successful,
            "failed": len(results) - successful,
            "total_duration": total_duration,
            "burst_duration": burst_duration,
            "sustained_duration": sustained_duration,
            "trace_ids": [r.get("trace_id") for r in results if isinstance(r, dict)][:15]  # First 15
        }
    
    async def run_all_stress_tests(self) -> Dict[str, Any]:
        """Run all stress and edge case tests"""
        print("🚀 Starting Stress Testing and Edge Cases")
        print("=" * 60)
        
        all_results = []
        total_start = time.time()
        
        # Run each test
        tests = [
            self.test_concurrent_load(30),  # Reduced from 50 to be gentler
            self.test_complex_eth_calls(),
            self.test_error_scenarios(),
            self.test_burst_patterns(),
        ]
        
        for test_coro in tests:
            try:
                result = await test_coro
                all_results.append(result)
                await asyncio.sleep(2)  # Brief pause between test phases
            except Exception as e:
                print(f"❌ Test failed: {e}")
                all_results.append({"error": str(e), "failed": True})
        
        total_duration = time.time() - total_start
        
        # Summary
        successful_tests = sum(1 for r in all_results if not r.get("failed", False))
        total_requests = sum(r.get("total_requests", 0) for r in all_results)
        total_successful = sum(r.get("successful", 0) for r in all_results)
        
        summary = {
            "stress_test_summary": {
                "total_tests": len(tests),
                "successful_tests": successful_tests,
                "total_requests": total_requests,
                "successful_requests": total_successful,
                "total_duration": total_duration,
                "timestamp": time.time()
            },
            "test_results": all_results
        }
        
        print("\n" + "=" * 60)
        print("📊 STRESS TEST SUMMARY")
        print(f"   Tests: {successful_tests}/{len(tests)} successful")
        print(f"   Requests: {total_successful}/{total_requests} successful")
        print(f"   Duration: {total_duration:.2f}s")
        print(f"   Avg throughput: {total_requests/total_duration:.1f} req/s")
        
        return summary

async def main():
    """Main stress test runner"""
    async with StressAndEdgeCaseTester() as tester:
        results = await tester.run_all_stress_tests()
        
        # Save results
        with open("stress_test_results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: stress_test_results.json")
        print(f"🔍 Check Jaeger UI: http://localhost:16686")
        
        # Show some trace IDs for investigation
        print("\n🔍 Sample trace IDs for Jaeger:")
        for test_result in results["test_results"]:
            if "trace_ids" in test_result and test_result["trace_ids"]:
                test_name = test_result.get("test", "unknown")
                trace_count = len([t for t in test_result["trace_ids"] if t])
                print(f"   {test_name}: {trace_count} traces")
                for trace_id in test_result["trace_ids"][:2]:  # Show first 2
                    if trace_id:
                        print(f"     - {trace_id}")

if __name__ == "__main__":
    asyncio.run(main())
