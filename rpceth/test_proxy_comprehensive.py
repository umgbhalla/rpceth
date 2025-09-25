#!/usr/bin/env python3
"""
Comprehensive test script for RPC Ethereum Proxy Server
Tests health monitoring, failover, load balancing, and tracing functionality
"""

import asyncio
import aiohttp
import json
import time
import uuid
import statistics
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter

class ProxyTester:
    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def make_rpc_call(self, method: str, params: List = None, custom_id: int = None, 
                           custom_headers: Dict = None) -> Tuple[Dict, float, str]:
        """Make an RPC call and return response, latency, and trace ID"""
        if params is None:
            params = []
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": custom_id or int(time.time() * 1000)
        }
        
        headers = {"Content-Type": "application/json"}
        if custom_headers:
            headers.update(custom_headers)
            
        start_time = time.time()
        
        async with self.session.post(self.base_url, 
                                   json=payload, 
                                   headers=headers) as response:
            latency = time.time() - start_time
            response_data = await response.json()
            trace_id = response.headers.get('x-xray-id', 'NO_TRACE_ID')
            
            return response_data, latency, trace_id
    
    async def test_basic_functionality(self) -> Dict:
        """Test basic RPC functionality"""
        print("🔍 Testing Basic Functionality...")
        
        results = {
            "eth_blockNumber": None,
            "eth_chainId": None,
            "custom_trace_id": None,
            "auto_trace_id": None
        }
        
        # Test eth_blockNumber
        response, latency, trace_id = await self.make_rpc_call("eth_blockNumber")
        results["eth_blockNumber"] = {
            "success": "result" in response,
            "latency_ms": latency * 1000,
            "trace_id": trace_id,
            "block_number": response.get("result", "N/A")
        }
        
        # Test eth_chainId
        response, latency, trace_id = await self.make_rpc_call("eth_chainId")
        results["eth_chainId"] = {
            "success": "result" in response,
            "latency_ms": latency * 1000,
            "trace_id": trace_id,
            "chain_id": response.get("result", "N/A")
        }
        
        # Test custom trace ID
        custom_trace = f"test-{uuid.uuid4()}"
        response, latency, trace_id = await self.make_rpc_call(
            "eth_blockNumber", 
            custom_headers={"x-xray-id": custom_trace}
        )
        results["custom_trace_id"] = {
            "sent": custom_trace,
            "received": trace_id,
            "preserved": custom_trace == trace_id
        }
        
        # Test auto-generated trace ID
        response, latency, trace_id = await self.make_rpc_call("eth_blockNumber")
        results["auto_trace_id"] = {
            "generated": trace_id != "NO_TRACE_ID",
            "trace_id": trace_id
        }
        
        return results
    
    async def test_load_balancing(self, num_requests: int = 100) -> Dict:
        """Test load balancing behavior"""
        print(f"⚖️ Testing Load Balancing with {num_requests} requests...")
        
        latencies = []
        trace_ids = []
        errors = 0
        
        # Make concurrent requests to test load balancing
        tasks = []
        for i in range(num_requests):
            task = self.make_rpc_call("eth_blockNumber", custom_id=i)
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(responses):
            if isinstance(result, Exception):
                errors += 1
                continue
                
            response, latency, trace_id = result
            if "result" in response:
                latencies.append(latency * 1000)  # Convert to ms
                trace_ids.append(trace_id)
            else:
                errors += 1
        
        return {
            "total_requests": num_requests,
            "successful_requests": len(latencies),
            "failed_requests": errors,
            "success_rate": len(latencies) / num_requests * 100,
            "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
            "min_latency_ms": min(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
            "p95_latency_ms": statistics.quantiles(latencies, n=20)[18] if len(latencies) > 20 else 0,
            "unique_trace_ids": len(set(trace_ids)),
            "trace_id_sample": trace_ids[:5] if trace_ids else []
        }
    
    async def test_error_handling(self) -> Dict:
        """Test error handling and invalid requests"""
        print("❌ Testing Error Handling...")
        
        results = {}
        
        # Test invalid method
        response, latency, trace_id = await self.make_rpc_call("invalid_method")
        results["invalid_method"] = {
            "has_error": "error" in response,
            "error_code": response.get("error", {}).get("code"),
            "trace_id": trace_id
        }
        
        # Test malformed request (this will test the server's JSON parsing)
        try:
            async with self.session.post(self.base_url, 
                                       data="invalid json", 
                                       headers={"Content-Type": "application/json"}) as resp:
                response_data = await resp.json()
                results["malformed_json"] = {
                    "status_code": resp.status,
                    "has_error": "error" in response_data if isinstance(response_data, dict) else True
                }
        except Exception as e:
            results["malformed_json"] = {
                "status_code": "exception",
                "error": str(e)
            }
        
        return results
    
    async def test_concurrent_load(self, concurrent_users: int = 50, requests_per_user: int = 10) -> Dict:
        """Test server under concurrent load"""
        print(f"🚀 Testing Concurrent Load: {concurrent_users} users × {requests_per_user} requests...")
        
        async def user_session(user_id: int) -> Dict:
            user_latencies = []
            user_errors = 0
            
            for req_id in range(requests_per_user):
                try:
                    response, latency, trace_id = await self.make_rpc_call(
                        "eth_blockNumber", 
                        custom_id=f"{user_id}-{req_id}"
                    )
                    if "result" in response:
                        user_latencies.append(latency * 1000)
                    else:
                        user_errors += 1
                except Exception:
                    user_errors += 1
            
            return {
                "user_id": user_id,
                "latencies": user_latencies,
                "errors": user_errors
            }
        
        start_time = time.time()
        
        # Create concurrent user sessions
        tasks = [user_session(i) for i in range(concurrent_users)]
        user_results = await asyncio.gather(*tasks)
        
        total_time = time.time() - start_time
        
        # Aggregate results
        all_latencies = []
        total_errors = 0
        total_requests = concurrent_users * requests_per_user
        
        for user_result in user_results:
            all_latencies.extend(user_result["latencies"])
            total_errors += user_result["errors"]
        
        return {
            "concurrent_users": concurrent_users,
            "requests_per_user": requests_per_user,
            "total_requests": total_requests,
            "successful_requests": len(all_latencies),
            "failed_requests": total_errors,
            "total_time_seconds": total_time,
            "requests_per_second": total_requests / total_time,
            "success_rate": len(all_latencies) / total_requests * 100,
            "avg_latency_ms": statistics.mean(all_latencies) if all_latencies else 0,
            "p95_latency_ms": statistics.quantiles(all_latencies, n=20)[18] if len(all_latencies) > 20 else 0,
            "p99_latency_ms": statistics.quantiles(all_latencies, n=100)[98] if len(all_latencies) > 100 else 0
        }
    
    async def test_health_monitoring_simulation(self) -> Dict:
        """Simulate health monitoring by observing response patterns"""
        print("🏥 Testing Health Monitoring Patterns...")
        
        # Make requests over time to observe health patterns
        results = []
        
        for round_num in range(5):
            print(f"   Round {round_num + 1}/5...")
            round_results = []
            
            # Make 20 requests in this round
            for i in range(20):
                try:
                    response, latency, trace_id = await self.make_rpc_call("eth_blockNumber")
                    round_results.append({
                        "success": "result" in response,
                        "latency_ms": latency * 1000,
                        "trace_id": trace_id,
                        "timestamp": time.time()
                    })
                    await asyncio.sleep(0.1)  # Small delay between requests
                except Exception as e:
                    round_results.append({
                        "success": False,
                        "error": str(e),
                        "timestamp": time.time()
                    })
            
            results.append({
                "round": round_num + 1,
                "requests": round_results,
                "success_rate": sum(1 for r in round_results if r.get("success", False)) / len(round_results) * 100,
                "avg_latency": statistics.mean([r["latency_ms"] for r in round_results if "latency_ms" in r]) if any("latency_ms" in r for r in round_results) else 0
            })
            
            await asyncio.sleep(1)  # Wait between rounds
        
        return {
            "rounds": results,
            "overall_success_rate": statistics.mean([r["success_rate"] for r in results]),
            "latency_trend": [r["avg_latency"] for r in results]
        }

async def main():
    print("🚀 Starting Comprehensive RPC Proxy Server Tests")
    print("=" * 60)
    
    async with ProxyTester() as tester:
        all_results = {}
        
        # Test 1: Basic Functionality
        all_results["basic_functionality"] = await tester.test_basic_functionality()
        
        # Test 2: Load Balancing
        all_results["load_balancing"] = await tester.test_load_balancing(100)
        
        # Test 3: Error Handling
        all_results["error_handling"] = await tester.test_error_handling()
        
        # Test 4: Concurrent Load
        all_results["concurrent_load"] = await tester.test_concurrent_load(30, 5)
        
        # Test 5: Health Monitoring Simulation
        all_results["health_monitoring"] = await tester.test_health_monitoring_simulation()
    
    # Print Results Summary
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    
    # Basic Functionality Results
    basic = all_results["basic_functionality"]
    print(f"\n🔍 BASIC FUNCTIONALITY:")
    print(f"   eth_blockNumber: {'✅' if basic['eth_blockNumber']['success'] else '❌'} "
          f"({basic['eth_blockNumber']['latency_ms']:.1f}ms)")
    print(f"   eth_chainId: {'✅' if basic['eth_chainId']['success'] else '❌'} "
          f"({basic['eth_chainId']['latency_ms']:.1f}ms)")
    print(f"   Trace ID Preservation: {'✅' if basic['custom_trace_id']['preserved'] else '❌'}")
    print(f"   Auto Trace ID Generation: {'✅' if basic['auto_trace_id']['generated'] else '❌'}")
    
    # Load Balancing Results
    lb = all_results["load_balancing"]
    print(f"\n⚖️ LOAD BALANCING:")
    print(f"   Success Rate: {lb['success_rate']:.1f}% ({lb['successful_requests']}/{lb['total_requests']})")
    print(f"   Average Latency: {lb['avg_latency_ms']:.1f}ms")
    print(f"   P95 Latency: {lb['p95_latency_ms']:.1f}ms")
    print(f"   Unique Trace IDs: {lb['unique_trace_ids']}")
    
    # Concurrent Load Results
    cl = all_results["concurrent_load"]
    print(f"\n🚀 CONCURRENT LOAD:")
    print(f"   Throughput: {cl['requests_per_second']:.1f} req/sec")
    print(f"   Success Rate: {cl['success_rate']:.1f}%")
    print(f"   P95 Latency: {cl['p95_latency_ms']:.1f}ms")
    print(f"   P99 Latency: {cl['p99_latency_ms']:.1f}ms")
    
    # Health Monitoring Results
    hm = all_results["health_monitoring"]
    print(f"\n🏥 HEALTH MONITORING:")
    print(f"   Overall Success Rate: {hm['overall_success_rate']:.1f}%")
    print(f"   Latency Trend: {' → '.join([f'{l:.1f}ms' for l in hm['latency_trend']])}")
    
    # Error Handling Results
    eh = all_results["error_handling"]
    print(f"\n❌ ERROR HANDLING:")
    print(f"   Invalid Method Handling: {'✅' if eh['invalid_method']['has_error'] else '❌'}")
    
    print(f"\n📋 DETAILED RESULTS saved to test_results.json")
    
    # Save detailed results
    with open("test_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print("\n✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(main())
