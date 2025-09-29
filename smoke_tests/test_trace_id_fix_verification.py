#!/usr/bin/env python3
"""
Verification test for trace ID fixes and enhanced tracing
Tests both UUID-format and custom trace IDs, and verifies searchability in Jaeger
"""

import asyncio
import aiohttp
import json
import time
import uuid
from typing import Dict, List, Any

class TraceIDFixVerificationTester:
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
    
    async def send_rpc_request(self, method: str, params: List[Any], trace_id: str = None) -> Dict:
        """Send RPC request with optional trace ID"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        headers = {"Content-Type": "application/json"}
        if trace_id:
            headers["x-xray-id"] = trace_id
        
        start_time = time.time()
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
    
    async def search_trace_in_jaeger(self, trace_id: str) -> Dict:
        """Search for a specific trace ID in Jaeger"""
        # Convert UUID format to 32-char hex if needed
        if len(trace_id) == 36 and '-' in trace_id:
            search_trace_id = trace_id.replace('-', '')
        else:
            search_trace_id = trace_id
            
        url = f"{self.jaeger_url}/api/traces/{search_trace_id}"
        
        try:
            async with self.session.get(url) as response:
                result = await response.json()
                return {
                    "trace_id": search_trace_id,
                    "found": len(result.get("data", [])) > 0,
                    "status_code": response.status,
                    "spans_count": len(result.get("data", [{}])[0].get("spans", [])) if result.get("data") else 0,
                    "response": result
                }
        except Exception as e:
            return {
                "trace_id": search_trace_id,
                "found": False,
                "error": str(e)
            }
    
    async def test_metrics_endpoint(self) -> Dict:
        """Test the /metrics endpoint"""
        try:
            async with self.session.get(f"{self.proxy_url}/metrics") as response:
                content = await response.text()
                return {
                    "endpoint": "/metrics",
                    "status_code": response.status,
                    "success": response.status == 200,
                    "content_length": len(content),
                    "has_rpc_metrics": "rpc_requests_total" in content
                }
        except Exception as e:
            return {
                "endpoint": "/metrics",
                "success": False,
                "error": str(e)
            }
    
    async def test_trace_id_formats(self) -> Dict:
        """Test different trace ID formats"""
        print("🔍 Testing trace ID format handling...")
        
        test_cases = [
            {
                "name": "UUID format (with hyphens)",
                "trace_id": str(uuid.uuid4()),
                "method": "eth_blockNumber"
            },
            {
                "name": "32-char hex format",
                "trace_id": uuid.uuid4().hex,
                "method": "eth_chainId"
            },
            {
                "name": "Custom string format",
                "trace_id": "custom-trace-id-12345",
                "method": "eth_gasPrice"
            },
            {
                "name": "Auto-generated (no trace ID)",
                "trace_id": None,
                "method": "net_version"
            }
        ]
        
        results = []
        
        for case in test_cases:
            print(f"   Testing: {case['name']}")
            
            # Send request
            rpc_result = await self.send_rpc_request(
                case["method"], [], case["trace_id"]
            )
            
            # Wait for trace to be processed
            await asyncio.sleep(2)
            
            # Search in Jaeger if we have a trace ID
            jaeger_result = None
            if case["trace_id"]:
                jaeger_result = await self.search_trace_in_jaeger(case["trace_id"])
            else:
                # For auto-generated, we need to find the latest trace
                jaeger_result = {"found": "unknown", "note": "auto-generated trace ID"}
            
            result = {
                "test_case": case["name"],
                "original_trace_id": case["trace_id"],
                "rpc_success": rpc_result["success"],
                "rpc_duration": rpc_result["duration"],
                "jaeger_found": jaeger_result.get("found", False),
                "jaeger_spans": jaeger_result.get("spans_count", 0),
                "searchable": jaeger_result.get("found", False) and jaeger_result.get("spans_count", 0) > 0
            }
            
            results.append(result)
            
            status = "✅" if result["searchable"] else "❓" if result["jaeger_found"] == "unknown" else "❌"
            print(f"      RPC: {'✅' if result['rpc_success'] else '❌'} | Jaeger: {status}")
        
        return {
            "test": "trace_id_formats",
            "results": results,
            "total_tests": len(test_cases),
            "searchable_traces": sum(1 for r in results if r["searchable"]),
            "successful_rpcs": sum(1 for r in results if r["rpc_success"])
        }
    
    async def test_enhanced_tracing_data(self) -> Dict:
        """Test that enhanced tracing data is captured"""
        print("📊 Testing enhanced tracing data...")
        
        # Send a request
        trace_id = uuid.uuid4().hex
        rpc_result = await self.send_rpc_request("eth_call", [{
            "to": "0xA0b86a33E6441E2a3B4E6b6A6C4B3C3B3A8B8B8B",
            "data": "0x18160ddd"  # totalSupply()
        }, "latest"], trace_id)
        
        # Wait for processing
        await asyncio.sleep(3)
        
        # Search for the trace
        jaeger_result = await self.search_trace_in_jaeger(trace_id)
        
        enhanced_fields = []
        if jaeger_result.get("found") and jaeger_result.get("response", {}).get("data"):
            spans = jaeger_result["response"]["data"][0].get("spans", [])
            for span in spans:
                if span.get("operationName") == "proxy.attempt":
                    tags = {tag["key"]: tag["value"] for tag in span.get("tags", [])}
                    enhanced_fields = [
                        {"field": "provider_url", "present": "provider_url" in tags, "value": tags.get("provider_url")},
                        {"field": "timeout_ms", "present": "timeout_ms" in tags, "value": tags.get("timeout_ms")},
                        {"field": "method", "present": "method" in tags, "value": tags.get("method")},
                        {"field": "request_id", "present": "request_id" in tags, "value": tags.get("request_id")},
                        {"field": "trace_id", "present": "trace_id" in tags, "value": tags.get("trace_id")},
                    ]
                    break
        
        enhanced_count = sum(1 for field in enhanced_fields if field["present"])
        
        print(f"   Enhanced fields found: {enhanced_count}/{len(enhanced_fields)}")
        for field in enhanced_fields:
            status = "✅" if field["present"] else "❌"
            print(f"      {field['field']}: {status} {field.get('value', '')}")
        
        return {
            "test": "enhanced_tracing_data",
            "trace_id": trace_id,
            "rpc_success": rpc_result["success"],
            "jaeger_found": jaeger_result.get("found", False),
            "enhanced_fields": enhanced_fields,
            "enhanced_fields_count": enhanced_count,
            "total_expected_fields": len(enhanced_fields)
        }
    
    async def run_verification_tests(self) -> Dict:
        """Run all verification tests"""
        print("🚀 Starting Trace ID Fix and Enhancement Verification")
        print("=" * 60)
        
        all_results = []
        start_time = time.time()
        
        # Test 1: Metrics endpoint
        print("📊 Testing metrics endpoint...")
        metrics_result = await self.test_metrics_endpoint()
        all_results.append(metrics_result)
        print(f"   Status: {'✅' if metrics_result['success'] else '❌'}")
        
        await asyncio.sleep(1)
        
        # Test 2: Trace ID formats
        trace_formats_result = await self.test_trace_id_formats()
        all_results.append(trace_formats_result)
        
        await asyncio.sleep(2)
        
        # Test 3: Enhanced tracing data
        enhanced_data_result = await self.test_enhanced_tracing_data()
        all_results.append(enhanced_data_result)
        
        total_duration = time.time() - start_time
        
        # Summary
        summary = {
            "verification_summary": {
                "total_tests": len(all_results),
                "metrics_endpoint_working": metrics_result["success"],
                "trace_formats_working": trace_formats_result["searchable_traces"],
                "enhanced_tracing_working": enhanced_data_result["enhanced_fields_count"],
                "total_duration": total_duration,
                "timestamp": time.time()
            },
            "detailed_results": all_results
        }
        
        print("\n" + "=" * 60)
        print("📊 VERIFICATION SUMMARY")
        print(f"   Metrics endpoint: {'✅' if metrics_result['success'] else '❌'}")
        print(f"   Searchable traces: {trace_formats_result['searchable_traces']}/{trace_formats_result['total_tests']}")
        print(f"   Enhanced fields: {enhanced_data_result['enhanced_fields_count']}/{enhanced_data_result['total_expected_fields']}")
        print(f"   Total duration: {total_duration:.2f}s")
        print(f"   Jaeger UI: {self.jaeger_url}")
        
        return summary

async def main():
    """Main verification runner"""
    async with TraceIDFixVerificationTester() as tester:
        results = await tester.run_verification_tests()
        
        # Save results
        with open("trace_id_fix_verification_results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: trace_id_fix_verification_results.json")
        
        # Show specific trace IDs for manual verification
        print("\n🔍 Trace IDs for manual Jaeger verification:")
        for test_result in results["detailed_results"]:
            if "results" in test_result:
                for case in test_result["results"]:
                    if case.get("original_trace_id") and case.get("searchable"):
                        original = case["original_trace_id"]
                        converted = original.replace("-", "") if "-" in original else original
                        print(f"   {case['test_case']}: {converted}")

if __name__ == "__main__":
    asyncio.run(main())
