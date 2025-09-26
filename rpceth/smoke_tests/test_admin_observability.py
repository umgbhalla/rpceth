#!/usr/bin/env python3
"""
Comprehensive test for admin endpoints and enhanced observability features
Tests all admin endpoints and verifies enhanced telemetry data
"""

import asyncio
import aiohttp
import json
import time
import signal
import os
from typing import Dict, List, Any

class AdminObservabilityTester:
    def __init__(self, proxy_url: str = "http://localhost:3000", jaeger_url: str = "http://localhost:16686", api_key: str = "change-me"):
        self.proxy_url = proxy_url
        self.jaeger_url = jaeger_url
        self.api_key = api_key
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_admin_endpoints(self) -> Dict:
        """Test all admin endpoints"""
        print("🔧 Testing admin endpoints...")
        
        endpoints = [
            ("/healthz", "health check"),
            ("/readyz", "readiness check"),
            ("/admin/providers", "provider status"),
            ("/admin/config", "configuration info"),
            ("/metrics", "prometheus metrics")
        ]
        
        results = []
        
        for endpoint, description in endpoints:
            print(f"   Testing {endpoint} ({description})...")
            
            try:
                start_time = time.time()
                async with self.session.get(f"{self.proxy_url}{endpoint}") as response:
                    content = await response.text()
                    duration = time.time() - start_time
                    
                    # Try to parse as JSON for structured endpoints
                    parsed_content = None
                    if endpoint != "/metrics":
                        try:
                            parsed_content = json.loads(content)
                        except json.JSONDecodeError:
                            pass
                    
                    result = {
                        "endpoint": endpoint,
                        "description": description,
                        "status_code": response.status,
                        "success": response.status == 200,
                        "duration_ms": round(duration * 1000, 2),
                        "content_length": len(content),
                        "has_json": parsed_content is not None,
                        "trace_id": response.headers.get("x-trace-id")
                    }
                    
                    # Add specific validations for each endpoint
                    if endpoint == "/healthz" and parsed_content:
                        result["has_status"] = "status" in parsed_content
                        result["has_version"] = "version" in parsed_content
                    elif endpoint == "/readyz" and parsed_content:
                        result["has_providers"] = "providers" in parsed_content
                        result["provider_count"] = parsed_content.get("total_providers", 0)
                    elif endpoint == "/admin/providers" and parsed_content:
                        result["provider_count"] = len(parsed_content.get("providers", []))
                        result["has_strategy"] = "strategy" in parsed_content
                    elif endpoint == "/admin/config" and parsed_content:
                        result["has_circuit_breaker"] = "circuit_breaker" in parsed_content
                        result["has_load_balancing"] = "load_balancing" in parsed_content
                    elif endpoint == "/metrics":
                        result["has_rpc_metrics"] = "rpc_requests_total" in content
                        result["has_duration_metrics"] = "rpc_request_duration_seconds" in content
                    
                    results.append(result)
                    
                    status = "✅" if result["success"] else "❌"
                    print(f"      {status} {response.status} ({duration*1000:.1f}ms)")
                    
            except Exception as e:
                results.append({
                    "endpoint": endpoint,
                    "description": description,
                    "success": False,
                    "error": str(e)
                })
                print(f"      ❌ Error: {e}")
        
        return {
            "test": "admin_endpoints",
            "results": results,
            "total_endpoints": len(endpoints),
            "successful_endpoints": sum(1 for r in results if r.get("success", False))
        }
    
    async def test_enhanced_telemetry(self) -> Dict:
        """Test enhanced telemetry features"""
        print("📊 Testing enhanced telemetry...")
        
        # Send multiple requests to generate telemetry data
        test_requests = [
            {"method": "eth_blockNumber", "params": []},
            {"method": "eth_chainId", "params": []},
            {"method": "eth_gasPrice", "params": []},
            {"method": "eth_getBalance", "params": ["0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "latest"]},
        ]
        
        trace_ids = []
        request_results = []
        
        for i, req in enumerate(test_requests):
            print(f"   Sending {req['method']} request...")
            
            payload = {
                "jsonrpc": "2.0",
                "method": req["method"],
                "params": req["params"],
                "id": i + 1
            }
            
            start_time = time.time()
            async with self.session.post(f"{self.proxy_url}/?apikey={self.api_key}", json=payload) as response:
                result = await response.json()
                duration = time.time() - start_time
                trace_id = response.headers.get("x-trace-id")
                
                request_results.append({
                    "method": req["method"],
                    "success": response.status == 200 and "result" in result,
                    "duration_ms": round(duration * 1000, 2),
                    "trace_id": trace_id
                })
                
                if trace_id:
                    trace_ids.append(trace_id)
        
        # Wait for traces to be processed
        await asyncio.sleep(3)
        
        # Analyze traces for enhanced telemetry data
        telemetry_analysis = []
        
        for trace_id in trace_ids[:2]:  # Analyze first 2 traces
            try:
                async with self.session.get(f"{self.jaeger_url}/api/traces/{trace_id}") as response:
                    if response.status == 200:
                        trace_data = await response.json()
                        
                        if trace_data.get("data") and len(trace_data["data"]) > 0:
                            spans = trace_data["data"][0].get("spans", [])
                            
                            for span in spans:
                                if span.get("operationName") == "proxy.attempt":
                                    tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                                    
                                    analysis = {
                                        "trace_id": trace_id,
                                        "span_name": span.get("operationName"),
                                        "has_provider_url": "provider_url" in tags,
                                        "has_lb_overhead": "lb_selection_duration_us" in tags,
                                        "has_provider_weight": "provider_weight" in tags,
                                        "has_total_providers": "total_providers" in tags,
                                        "has_timeout_info": "timeout_ms" in tags,
                                        "provider_url": tags.get("provider_url"),
                                        "lb_overhead_us": tags.get("lb_selection_duration_us"),
                                        "provider_weight": tags.get("provider_weight"),
                                        "total_providers": tags.get("total_providers")
                                    }
                                    
                                    telemetry_analysis.append(analysis)
                                    break
                            
            except Exception as e:
                print(f"      Warning: Could not analyze trace {trace_id}: {e}")
        
        # Calculate telemetry completeness
        if telemetry_analysis:
            avg_completeness = sum([
                sum([
                    analysis["has_provider_url"],
                    analysis["has_lb_overhead"],
                    analysis["has_provider_weight"],
                    analysis["has_total_providers"],
                    analysis["has_timeout_info"]
                ]) for analysis in telemetry_analysis
            ]) / (len(telemetry_analysis) * 5)
        else:
            avg_completeness = 0
        
        return {
            "test": "enhanced_telemetry",
            "request_results": request_results,
            "telemetry_analysis": telemetry_analysis,
            "total_requests": len(test_requests),
            "successful_requests": sum(1 for r in request_results if r["success"]),
            "traces_analyzed": len(telemetry_analysis),
            "telemetry_completeness": round(avg_completeness * 100, 1)
        }
    
    async def test_load_balancer_overhead(self) -> Dict:
        """Test load balancer overhead tracking"""
        print("⚖️ Testing load balancer overhead tracking...")
        
        # Send multiple requests to get overhead statistics
        overhead_data = []
        
        for i in range(10):
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": i + 1
            }
            
            async with self.session.post(f"{self.proxy_url}/?apikey={self.api_key}", json=payload) as response:
                trace_id = response.headers.get("x-trace-id")
                if trace_id:
                    overhead_data.append(trace_id)
        
        # Wait for traces
        await asyncio.sleep(3)
        
        # Analyze overhead from traces
        overhead_measurements = []
        
        for trace_id in overhead_data[:5]:  # Analyze first 5
            try:
                async with self.session.get(f"{self.jaeger_url}/api/traces/{trace_id}") as response:
                    if response.status == 200:
                        trace_data = await response.json()
                        
                        if trace_data.get("data") and len(trace_data["data"]) > 0:
                            spans = trace_data["data"][0].get("spans", [])
                            
                            for span in spans:
                                if span.get("operationName") == "proxy.attempt":
                                    tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                                    
                                    if "lb_selection_duration_us" in tags:
                                        try:
                                            overhead_us = int(tags["lb_selection_duration_us"])
                                            overhead_measurements.append(overhead_us)
                                        except (ValueError, TypeError):
                                            pass
                                    break
            except Exception as e:
                print(f"      Warning: Could not analyze overhead for {trace_id}: {e}")
        
        # Calculate statistics
        if overhead_measurements:
            avg_overhead = sum(overhead_measurements) / len(overhead_measurements)
            min_overhead = min(overhead_measurements)
            max_overhead = max(overhead_measurements)
        else:
            avg_overhead = min_overhead = max_overhead = 0
        
        print(f"   Load balancer overhead statistics:")
        print(f"      Measurements: {len(overhead_measurements)}")
        print(f"      Average: {avg_overhead:.1f}μs")
        print(f"      Range: {min_overhead}μs - {max_overhead}μs")
        
        return {
            "test": "load_balancer_overhead",
            "measurements": overhead_measurements,
            "measurement_count": len(overhead_measurements),
            "avg_overhead_us": round(avg_overhead, 1),
            "min_overhead_us": min_overhead,
            "max_overhead_us": max_overhead
        }
    
    async def run_admin_observability_tests(self) -> Dict:
        """Run all admin and observability tests"""
        print("🚀 Starting Admin & Observability Tests")
        print("=" * 60)
        
        all_results = []
        start_time = time.time()
        
        # Test 1: Admin endpoints
        admin_result = await self.test_admin_endpoints()
        all_results.append(admin_result)
        
        await asyncio.sleep(1)
        
        # Test 2: Enhanced telemetry
        telemetry_result = await self.test_enhanced_telemetry()
        all_results.append(telemetry_result)
        
        await asyncio.sleep(1)
        
        # Test 3: Load balancer overhead
        overhead_result = await self.test_load_balancer_overhead()
        all_results.append(overhead_result)
        
        total_duration = time.time() - start_time
        
        # Summary
        summary = {
            "admin_observability_summary": {
                "total_tests": len(all_results),
                "admin_endpoints_working": admin_result["successful_endpoints"],
                "total_admin_endpoints": admin_result["total_endpoints"],
                "telemetry_completeness": telemetry_result["telemetry_completeness"],
                "overhead_measurements": overhead_result["measurement_count"],
                "avg_lb_overhead_us": overhead_result["avg_overhead_us"],
                "total_duration": total_duration,
                "timestamp": time.time()
            },
            "detailed_results": all_results
        }
        
        print("\n" + "=" * 60)
        print("📊 ADMIN & OBSERVABILITY SUMMARY")
        print(f"   Admin endpoints: {admin_result['successful_endpoints']}/{admin_result['total_endpoints']} working")
        print(f"   Telemetry completeness: {telemetry_result['telemetry_completeness']}%")
        print(f"   Load balancer overhead: {overhead_result['avg_overhead_us']:.1f}μs avg")
        print(f"   Total duration: {total_duration:.2f}s")
        
        return summary

async def main():
    """Main test runner"""
    async with AdminObservabilityTester() as tester:
        results = await tester.run_admin_observability_tests()
        
        # Save results
        with open("admin_observability_results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: admin_observability_results.json")
        print(f"🔍 Jaeger UI: http://localhost:16686")
        print(f"🔧 Admin endpoints available:")
        print(f"   Health: http://localhost:3000/healthz")
        print(f"   Readiness: http://localhost:3000/readyz")
        print(f"   Providers: http://localhost:3000/admin/providers")
        print(f"   Config: http://localhost:3000/admin/config")
        print(f"   Metrics: http://localhost:3000/metrics")

if __name__ == "__main__":
    asyncio.run(main())
