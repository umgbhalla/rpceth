#!/usr/bin/env python3
"""
Test streamlined trace ID implementation
Verifies that response trace IDs match Jaeger trace IDs exactly
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Any

class StreamlinedTraceIDTester:
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
    
    async def send_rpc_request_and_get_trace_id(self, method: str, params: List[Any]) -> Dict:
        """Send RPC request and extract trace ID from response headers"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        headers = {"Content-Type": "application/json"}
        
        start_time = time.time()
        async with self.session.post(f"{self.proxy_url}/?apikey={self.api_key}", json=payload, headers=headers) as response:
            result = await response.json()
            duration = time.time() - start_time
            
            # Extract trace ID from response headers
            response_trace_id = response.headers.get("x-trace-id")
            
            return {
                "request": payload,
                "response": result,
                "duration": duration,
                "status_code": response.status,
                "response_trace_id": response_trace_id,
                "success": response.status == 200 and "result" in result
            }
    
    async def verify_trace_in_jaeger(self, trace_id: str) -> Dict:
        """Verify trace exists in Jaeger and extract details"""
        url = f"{self.jaeger_url}/api/traces/{trace_id}"
        
        try:
            async with self.session.get(url) as response:
                result = await response.json()
                
                if result.get("data") and len(result["data"]) > 0:
                    trace_data = result["data"][0]
                    jaeger_trace_id = trace_data.get("traceID")
                    spans = trace_data.get("spans", [])
                    
                    # Extract otel_trace_id from span tags
                    otel_trace_ids_in_spans = []
                    for span in spans:
                        for tag in span.get("tags", []):
                            if tag.get("key") == "otel_trace_id":
                                otel_trace_ids_in_spans.append(tag.get("value"))
                    
                    return {
                        "found": True,
                        "jaeger_trace_id": jaeger_trace_id,
                        "spans_count": len(spans),
                        "otel_trace_ids_in_spans": otel_trace_ids_in_spans,
                        "trace_id_matches": trace_id == jaeger_trace_id,
                        "span_tags_match": all(tid == trace_id for tid in otel_trace_ids_in_spans)
                    }
                else:
                    return {"found": False, "trace_id": trace_id}
                    
        except Exception as e:
            return {"found": False, "error": str(e), "trace_id": trace_id}
    
    async def test_trace_id_consistency(self) -> Dict:
        """Test that trace IDs are consistent across response headers, Jaeger trace ID, and span tags"""
        print("🔍 Testing trace ID consistency...")
        
        test_methods = [
            ("eth_blockNumber", []),
            ("eth_chainId", []),
            ("eth_gasPrice", []),
            ("net_version", []),
            ("eth_getBalance", ["0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "latest"]),
        ]
        
        results = []
        
        for method, params in test_methods:
            print(f"   Testing {method}...")
            
            # Send request and get trace ID from response
            rpc_result = await self.send_rpc_request_and_get_trace_id(method, params)
            
            if not rpc_result["success"] or not rpc_result["response_trace_id"]:
                results.append({
                    "method": method,
                    "success": False,
                    "error": "RPC request failed or no trace ID in response"
                })
                continue
            
            response_trace_id = rpc_result["response_trace_id"]
            
            # Wait for trace to be processed
            await asyncio.sleep(2)
            
            # Verify in Jaeger
            jaeger_result = await self.verify_trace_in_jaeger(response_trace_id)
            
            test_result = {
                "method": method,
                "rpc_success": rpc_result["success"],
                "response_trace_id": response_trace_id,
                "jaeger_found": jaeger_result.get("found", False),
                "jaeger_trace_id": jaeger_result.get("jaeger_trace_id"),
                "spans_count": jaeger_result.get("spans_count", 0),
                "trace_id_matches": jaeger_result.get("trace_id_matches", False),
                "span_tags_match": jaeger_result.get("span_tags_match", False),
                "all_consistent": (
                    jaeger_result.get("trace_id_matches", False) and 
                    jaeger_result.get("span_tags_match", False)
                )
            }
            
            results.append(test_result)
            
            status = "✅" if test_result["all_consistent"] else "❌"
            print(f"      Response: {response_trace_id[:16]}...")
            print(f"      Jaeger: {jaeger_result.get('jaeger_trace_id', 'N/A')[:16] if jaeger_result.get('jaeger_trace_id') else 'N/A'}...")
            print(f"      Consistent: {status}")
        
        return {
            "test": "trace_id_consistency",
            "results": results,
            "total_tests": len(test_methods),
            "consistent_traces": sum(1 for r in results if r.get("all_consistent", False)),
            "successful_rpcs": sum(1 for r in results if r.get("rpc_success", False))
        }
    
    async def test_metrics_endpoint_tracing(self) -> Dict:
        """Test that metrics endpoint also generates traces"""
        print("📊 Testing metrics endpoint tracing...")
        
        async with self.session.get(f"{self.proxy_url}/metrics") as response:
            content = await response.text()
            trace_id = response.headers.get("x-trace-id")
            
            result = {
                "endpoint": "/metrics",
                "status_code": response.status,
                "success": response.status == 200,
                "has_trace_id": trace_id is not None,
                "trace_id": trace_id,
                "content_length": len(content)
            }
            
            if trace_id:
                # Wait and verify in Jaeger
                await asyncio.sleep(2)
                jaeger_result = await self.verify_trace_in_jaeger(trace_id)
                result.update({
                    "jaeger_found": jaeger_result.get("found", False),
                    "spans_count": jaeger_result.get("spans_count", 0)
                })
            
            status = "✅" if result.get("jaeger_found", False) else "❌"
            print(f"   Metrics endpoint trace: {status}")
            
            return result
    
    async def run_streamlined_tests(self) -> Dict:
        """Run all streamlined trace ID tests"""
        print("🚀 Starting Streamlined Trace ID Tests")
        print("=" * 60)
        
        all_results = []
        start_time = time.time()
        
        # Test 1: Trace ID consistency
        consistency_result = await self.test_trace_id_consistency()
        all_results.append(consistency_result)
        
        await asyncio.sleep(1)
        
        # Test 2: Metrics endpoint tracing
        metrics_result = await self.test_metrics_endpoint_tracing()
        all_results.append(metrics_result)
        
        total_duration = time.time() - start_time
        
        # Summary
        summary = {
            "streamlined_test_summary": {
                "total_tests": len(all_results),
                "consistent_traces": consistency_result["consistent_traces"],
                "total_rpc_tests": consistency_result["total_tests"],
                "metrics_endpoint_working": metrics_result["success"],
                "metrics_endpoint_traced": metrics_result.get("jaeger_found", False),
                "total_duration": total_duration,
                "timestamp": time.time()
            },
            "detailed_results": all_results
        }
        
        print("\n" + "=" * 60)
        print("📊 STREAMLINED TEST SUMMARY")
        print(f"   Consistent traces: {consistency_result['consistent_traces']}/{consistency_result['total_tests']}")
        print(f"   Metrics endpoint: {'✅' if metrics_result['success'] else '❌'}")
        print(f"   Metrics traced: {'✅' if metrics_result.get('jaeger_found', False) else '❌'}")
        print(f"   Total duration: {total_duration:.2f}s")
        print(f"   Jaeger UI: {self.jaeger_url}")
        
        return summary

async def main():
    """Main test runner"""
    async with StreamlinedTraceIDTester() as tester:
        results = await tester.run_streamlined_tests()
        
        # Save results
        with open("streamlined_trace_id_results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Results saved to: streamlined_trace_id_results.json")
        
        # Show sample trace IDs for verification
        print("\n🔍 Sample trace IDs for manual verification:")
        for test_result in results["detailed_results"]:
            if "results" in test_result:
                for case in test_result["results"][:3]:  # Show first 3
                    if case.get("response_trace_id") and case.get("all_consistent"):
                        print(f"   {case['method']}: {case['response_trace_id']}")

if __name__ == "__main__":
    asyncio.run(main())
