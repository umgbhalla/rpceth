#!/usr/bin/env python3
"""
Health Monitoring Analysis Script
Analyzes the health monitoring algorithms and behavior patterns
"""

import asyncio
import aiohttp
import json
import time
import statistics
from collections import defaultdict
# Removed matplotlib dependency for simpler execution

class HealthAnalyzer:
    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def make_rpc_call(self, method: str = "eth_blockNumber") -> dict:
        """Make an RPC call and collect timing/response data"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": [],
            "id": int(time.time() * 1000000)  # Microsecond precision
        }
        
        start_time = time.time()
        
        try:
            async with self.session.post(self.base_url, 
                                       json=payload,
                                       timeout=aiohttp.ClientTimeout(total=10)) as response:
                latency = time.time() - start_time
                response_data = await response.json()
                trace_id = response.headers.get('x-xray-id', 'NO_TRACE_ID')
                
                return {
                    "timestamp": start_time,
                    "latency_ms": latency * 1000,
                    "success": "result" in response_data,
                    "trace_id": trace_id,
                    "response": response_data,
                    "status_code": response.status
                }
        except Exception as e:
            return {
                "timestamp": start_time,
                "latency_ms": -1,
                "success": False,
                "error": str(e),
                "trace_id": "ERROR"
            }
    
    async def analyze_provider_distribution(self, num_requests: int = 200) -> dict:
        """Analyze how requests are distributed across providers"""
        print(f"📊 Analyzing Provider Distribution ({num_requests} requests)...")
        
        results = []
        
        # Make requests with small delays to see patterns
        for i in range(num_requests):
            result = await self.make_rpc_call()
            results.append(result)
            
            if i % 50 == 0:
                print(f"   Progress: {i}/{num_requests}")
            
            await asyncio.sleep(0.05)  # 50ms between requests
        
        # Analyze patterns
        successful_results = [r for r in results if r["success"]]
        latencies = [r["latency_ms"] for r in successful_results]
        
        # Group by latency ranges to infer provider behavior
        latency_groups = defaultdict(list)
        for result in successful_results:
            lat = result["latency_ms"]
            if lat < 500:
                latency_groups["fast"].append(result)
            elif lat < 1500:
                latency_groups["medium"].append(result)
            else:
                latency_groups["slow"].append(result)
        
        return {
            "total_requests": num_requests,
            "successful_requests": len(successful_results),
            "success_rate": len(successful_results) / num_requests * 100,
            "latency_stats": {
                "mean": statistics.mean(latencies) if latencies else 0,
                "median": statistics.median(latencies) if latencies else 0,
                "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
                "min": min(latencies) if latencies else 0,
                "max": max(latencies) if latencies else 0
            },
            "latency_groups": {
                group: {
                    "count": len(results),
                    "percentage": len(results) / len(successful_results) * 100 if successful_results else 0,
                    "avg_latency": statistics.mean([r["latency_ms"] for r in results]) if results else 0
                }
                for group, results in latency_groups.items()
            },
            "timeline": results
        }
    
    async def analyze_health_probe_timing(self, duration_minutes: int = 2) -> dict:
        """Analyze health probe timing and patterns"""
        print(f"🏥 Analyzing Health Probe Patterns ({duration_minutes} minutes)...")
        
        results = []
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        
        request_count = 0
        
        while time.time() < end_time:
            result = await self.make_rpc_call()
            results.append(result)
            request_count += 1
            
            if request_count % 20 == 0:
                elapsed = time.time() - start_time
                print(f"   {elapsed:.1f}s elapsed, {request_count} requests made")
            
            await asyncio.sleep(0.5)  # 500ms between requests
        
        # Analyze temporal patterns
        successful_results = [r for r in results if r["success"]]
        
        # Calculate moving averages
        window_size = 10
        moving_avg_latency = []
        moving_success_rate = []
        
        for i in range(window_size, len(results)):
            window = results[i-window_size:i]
            successful_in_window = [r for r in window if r["success"]]
            
            avg_latency = statistics.mean([r["latency_ms"] for r in successful_in_window]) if successful_in_window else 0
            success_rate = len(successful_in_window) / len(window) * 100
            
            moving_avg_latency.append(avg_latency)
            moving_success_rate.append(success_rate)
        
        return {
            "duration_seconds": time.time() - start_time,
            "total_requests": len(results),
            "successful_requests": len(successful_results),
            "overall_success_rate": len(successful_results) / len(results) * 100,
            "latency_trend": {
                "raw_latencies": [r["latency_ms"] for r in successful_results],
                "moving_average": moving_avg_latency,
                "moving_success_rate": moving_success_rate
            },
            "timeline": results
        }
    
    async def test_concurrent_health_impact(self) -> dict:
        """Test how concurrent load affects health monitoring"""
        print("🔄 Testing Concurrent Load Impact on Health...")
        
        # Baseline: Sequential requests
        print("   Measuring baseline (sequential)...")
        baseline_results = []
        for i in range(20):
            result = await self.make_rpc_call()
            baseline_results.append(result)
            await asyncio.sleep(0.1)
        
        # Concurrent load: Burst requests
        print("   Measuring under concurrent load...")
        concurrent_tasks = []
        for i in range(50):  # 50 concurrent requests
            task = self.make_rpc_call()
            concurrent_tasks.append(task)
        
        concurrent_results = await asyncio.gather(*concurrent_tasks, return_exceptions=True)
        concurrent_results = [r for r in concurrent_results if isinstance(r, dict)]
        
        # Recovery: Sequential requests after load
        print("   Measuring recovery...")
        await asyncio.sleep(2)  # Wait for recovery
        recovery_results = []
        for i in range(20):
            result = await self.make_rpc_call()
            recovery_results.append(result)
            await asyncio.sleep(0.1)
        
        def analyze_phase(results, phase_name):
            successful = [r for r in results if r.get("success", False)]
            return {
                "phase": phase_name,
                "total_requests": len(results),
                "successful_requests": len(successful),
                "success_rate": len(successful) / len(results) * 100 if results else 0,
                "avg_latency": statistics.mean([r["latency_ms"] for r in successful]) if successful else 0,
                "max_latency": max([r["latency_ms"] for r in successful]) if successful else 0
            }
        
        return {
            "baseline": analyze_phase(baseline_results, "baseline"),
            "concurrent_load": analyze_phase(concurrent_results, "concurrent_load"),
            "recovery": analyze_phase(recovery_results, "recovery")
        }

async def main():
    print("🔬 Health Monitoring Analysis")
    print("=" * 50)
    
    async with HealthAnalyzer() as analyzer:
        results = {}
        
        # Test 1: Provider Distribution Analysis
        results["provider_distribution"] = await analyzer.analyze_provider_distribution(150)
        
        # Test 2: Health Probe Timing Analysis
        results["health_probe_timing"] = await analyzer.analyze_health_probe_timing(1)  # 1 minute
        
        # Test 3: Concurrent Load Impact
        results["concurrent_impact"] = await analyzer.test_concurrent_health_impact()
    
    # Print Analysis Results
    print("\n" + "=" * 50)
    print("📊 HEALTH ANALYSIS RESULTS")
    print("=" * 50)
    
    # Provider Distribution
    pd = results["provider_distribution"]
    print(f"\n📊 PROVIDER DISTRIBUTION:")
    print(f"   Success Rate: {pd['success_rate']:.1f}%")
    print(f"   Average Latency: {pd['latency_stats']['mean']:.1f}ms")
    print(f"   Latency Std Dev: {pd['latency_stats']['stdev']:.1f}ms")
    print(f"   Latency Groups:")
    for group, stats in pd["latency_groups"].items():
        print(f"     {group.capitalize()}: {stats['count']} requests ({stats['percentage']:.1f}%) - avg {stats['avg_latency']:.1f}ms")
    
    # Health Probe Timing
    hpt = results["health_probe_timing"]
    print(f"\n🏥 HEALTH PROBE TIMING:")
    print(f"   Duration: {hpt['duration_seconds']:.1f}s")
    print(f"   Total Requests: {hpt['total_requests']}")
    print(f"   Success Rate: {hpt['overall_success_rate']:.1f}%")
    if hpt["latency_trend"]["moving_average"]:
        print(f"   Latency Trend: {hpt['latency_trend']['moving_average'][0]:.1f}ms → {hpt['latency_trend']['moving_average'][-1]:.1f}ms")
    
    # Concurrent Impact
    ci = results["concurrent_impact"]
    print(f"\n🔄 CONCURRENT LOAD IMPACT:")
    print(f"   Baseline: {ci['baseline']['success_rate']:.1f}% success, {ci['baseline']['avg_latency']:.1f}ms avg")
    print(f"   Under Load: {ci['concurrent_load']['success_rate']:.1f}% success, {ci['concurrent_load']['avg_latency']:.1f}ms avg")
    print(f"   Recovery: {ci['recovery']['success_rate']:.1f}% success, {ci['recovery']['avg_latency']:.1f}ms avg")
    
    # Save detailed results
    with open("health_analysis_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n📋 Detailed results saved to health_analysis_results.json")
    print("\n✅ Health analysis completed!")

if __name__ == "__main__":
    asyncio.run(main())
