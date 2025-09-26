#!/usr/bin/env python3
"""
Comprehensive test for provider override and chain ID parameter functionality
Tests API key authentication, provider_id bypassing, and chain ID routing
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional, Tuple

class ProviderOverrideAndChainIDTester:
    def __init__(self, proxy_url: str = "http://localhost:3000", api_key: str = "change-me"):
        self.proxy_url = proxy_url
        self.api_key = api_key
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def make_rpc_call(self, method: str = "eth_blockNumber", params: List = None, 
                           provider_id: str = None, chain_id: str = None, 
                           api_key: str = None, expect_error: bool = False) -> Dict:
        """Make an RPC call with optional provider override and chain ID"""
        if params is None:
            params = []
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": int(time.time() * 1000)
        }
        
        # Build URL path and query parameters
        path = "/"
        if chain_id:
            path = f"/{chain_id}"
        
        query_params = []
        if api_key is not None:
            query_params.append(f"apikey={api_key}")
        if provider_id:
            query_params.append(f"provider_id={provider_id}")
        
        query_string = "&".join(query_params)
        url = f"{self.proxy_url}{path}"
        if query_string:
            url += f"?{query_string}"
        
        headers = {"Content-Type": "application/json"}
        
        start_time = time.time()
        
        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                latency = time.time() - start_time
                
                try:
                    response_data = await response.json()
                except:
                    response_data = {"error": {"code": -32700, "message": f"HTTP {response.status}"}}
                
                trace_id = response.headers.get('x-trace-id', 'NO_TRACE_ID')
                
                return {
                    "success": response.status == 200 and "result" in response_data,
                    "status_code": response.status,
                    "response": response_data,
                    "latency_ms": latency * 1000,
                    "trace_id": trace_id,
                    "url": url,
                    "provider_id": provider_id,
                    "chain_id": chain_id
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "url": url,
                "provider_id": provider_id,
                "chain_id": chain_id
            }
    
    async def test_authentication_bypass_routes(self) -> Dict:
        """Test routes that should bypass authentication"""
        print("🔓 Testing Authentication Bypass Routes...")
        
        results = {}
        
        # Test /metrics endpoint (should not require auth)
        try:
            async with self.session.get(f"{self.proxy_url}/metrics") as response:
                results["metrics"] = {
                    "success": response.status == 200,
                    "status_code": response.status,
                    "content_type": response.headers.get('content-type', ''),
                    "requires_auth": False
                }
        except Exception as e:
            results["metrics"] = {"success": False, "error": str(e)}
        
        # Test admin endpoints (should not require auth)
        admin_endpoints = ["/healthz", "/readyz", "/admin/providers", "/admin/config"]
        
        for endpoint in admin_endpoints:
            try:
                async with self.session.get(f"{self.proxy_url}{endpoint}") as response:
                    results[endpoint.replace("/", "_")] = {
                        "success": response.status == 200,
                        "status_code": response.status,
                        "requires_auth": False
                    }
            except Exception as e:
                results[endpoint.replace("/", "_")] = {"success": False, "error": str(e)}
        
        return results
    
    async def test_api_key_authentication(self) -> Dict:
        """Test API key authentication requirements"""
        print("🔐 Testing API Key Authentication...")
        
        results = {}
        
        # Test without API key (should fail)
        result = await self.make_rpc_call(api_key=None)
        status_code = result.get("status_code", 0)
        results["no_api_key"] = {
            "success": status_code == 401,
            "status_code": status_code,
            "expected_401": True,
            "actual_401": status_code == 401,
            "error": result.get("error")
        }
        
        # Test with invalid API key (should fail)
        result = await self.make_rpc_call(api_key="invalid-key")
        status_code = result.get("status_code", 0)
        results["invalid_api_key"] = {
            "success": status_code == 401,
            "status_code": status_code,
            "expected_401": True,
            "actual_401": status_code == 401,
            "error": result.get("error")
        }
        
        # Test with valid API key (should succeed)
        result = await self.make_rpc_call(api_key=self.api_key)
        status_code = result.get("status_code", 0)
        results["valid_api_key"] = {
            "success": result.get("success", False),
            "status_code": status_code,
            "expected_200": True,
            "actual_200": status_code == 200,
            "has_result": "result" in result.get("response", {}),
            "error": result.get("error")
        }
        
        return results
    
    async def test_provider_override(self) -> Dict:
        """Test provider_id parameter for provider selection override"""
        print("🎯 Testing Provider Override Functionality...")
        
        results = {}
        
        # Get list of available providers from admin endpoint
        try:
            async with self.session.get(f"{self.proxy_url}/admin/providers") as response:
                if response.status == 200:
                    admin_data = await response.json()
                    available_providers = [p["id"] for p in admin_data.get("providers", [])]
                else:
                    available_providers = ["alchemy", "nodereal_eth", "ankr_eth", "quicknode_eth"]  # fallback
        except:
            available_providers = ["alchemy", "nodereal_eth", "ankr_eth", "quicknode_eth"]  # fallback
        
        print(f"   Available providers: {available_providers}")
        
        # Test without provider override (normal load balancing)
        result = await self.make_rpc_call(api_key=self.api_key)
        results["no_provider_override"] = {
            "success": result["success"],
            "status_code": result["status_code"],
            "trace_id": result.get("trace_id"),
            "latency_ms": result.get("latency_ms", 0)
        }
        
        # Test with specific provider overrides
        for provider_id in available_providers[:3]:  # Test first 3 providers
            result = await self.make_rpc_call(api_key=self.api_key, provider_id=provider_id)
            results[f"provider_override_{provider_id}"] = {
                "success": result["success"],
                "status_code": result["status_code"],
                "provider_id": provider_id,
                "trace_id": result.get("trace_id"),
                "latency_ms": result.get("latency_ms", 0),
                "url_used": result.get("url")
            }
        
        # Test with invalid provider ID
        result = await self.make_rpc_call(api_key=self.api_key, provider_id="invalid_provider")
        results["invalid_provider_override"] = {
            "success": result["success"],
            "status_code": result["status_code"],
            "provider_id": "invalid_provider",
            "should_fallback": True,
            "trace_id": result.get("trace_id")
        }
        
        return results
    
    async def test_chain_id_routing(self) -> Dict:
        """Test chain ID parameter in URL path"""
        print("⛓️ Testing Chain ID Routing...")
        
        results = {}
        
        # Test default route (no chain ID)
        result = await self.make_rpc_call(api_key=self.api_key)
        results["default_route"] = {
            "success": result["success"],
            "status_code": result["status_code"],
            "path": "/",
            "trace_id": result.get("trace_id")
        }
        
        # Test with various chain IDs
        chain_ids = ["1", "eth", "ethereum", "137", "polygon", "56", "bsc"]
        
        for chain_id in chain_ids:
            result = await self.make_rpc_call(api_key=self.api_key, chain_id=chain_id)
            results[f"chain_id_{chain_id}"] = {
                "success": result["success"],
                "status_code": result["status_code"],
                "chain_id": chain_id,
                "path": f"/{chain_id}",
                "trace_id": result.get("trace_id"),
                "latency_ms": result.get("latency_ms", 0)
            }
        
        return results
    
    async def test_combined_parameters(self) -> Dict:
        """Test combination of chain ID and provider override"""
        print("🔗 Testing Combined Chain ID + Provider Override...")
        
        results = {}
        
        # Get available providers
        try:
            async with self.session.get(f"{self.proxy_url}/admin/providers") as response:
                if response.status == 200:
                    admin_data = await response.json()
                    available_providers = [p["id"] for p in admin_data.get("providers", [])]
                else:
                    available_providers = ["alchemy", "nodereal_eth"]  # fallback
        except:
            available_providers = ["alchemy", "nodereal_eth"]  # fallback
        
        # Test combinations
        test_combinations = [
            {"chain_id": "1", "provider_id": available_providers[0] if available_providers else "alchemy"},
            {"chain_id": "eth", "provider_id": available_providers[1] if len(available_providers) > 1 else "nodereal_eth"},
            {"chain_id": "137", "provider_id": available_providers[0] if available_providers else "alchemy"},
        ]
        
        for i, combo in enumerate(test_combinations):
            result = await self.make_rpc_call(
                api_key=self.api_key,
                chain_id=combo["chain_id"],
                provider_id=combo["provider_id"]
            )
            results[f"combo_{i+1}"] = {
                "success": result["success"],
                "status_code": result["status_code"],
                "chain_id": combo["chain_id"],
                "provider_id": combo["provider_id"],
                "url_used": result.get("url"),
                "trace_id": result.get("trace_id"),
                "latency_ms": result.get("latency_ms", 0)
            }
        
        return results
    
    async def test_error_scenarios(self) -> Dict:
        """Test various error scenarios"""
        print("❌ Testing Error Scenarios...")
        
        results = {}
        
        # Test malformed JSON
        try:
            url = f"{self.proxy_url}/?apikey={self.api_key}"
            async with self.session.post(url, data="invalid json", 
                                       headers={"Content-Type": "application/json"}) as response:
                results["malformed_json"] = {
                    "status_code": response.status,
                    "expected_error": True,
                    "got_error": response.status >= 400
                }
        except Exception as e:
            results["malformed_json"] = {"error": str(e), "expected_error": True}
        
        # Test invalid method
        result = await self.make_rpc_call(method="invalid_method", api_key=self.api_key)
        results["invalid_method"] = {
            "success": "error" in result.get("response", {}),
            "status_code": result["status_code"],
            "has_error_response": "error" in result.get("response", {})
        }
        
        # Test missing required parameters in JSON-RPC
        try:
            url = f"{self.proxy_url}/?apikey={self.api_key}"
            payload = {"jsonrpc": "2.0", "id": 1}  # Missing method
            async with self.session.post(url, json=payload) as response:
                response_data = await response.json()
                results["missing_method"] = {
                    "status_code": response.status,
                    "has_error": "error" in response_data,
                    "expected_error": True
                }
        except Exception as e:
            results["missing_method"] = {"error": str(e), "expected_error": True}
        
        return results

async def main():
    print("🚀 Starting Provider Override and Chain ID Testing")
    print("=" * 60)
    
    async with ProviderOverrideAndChainIDTester() as tester:
        all_results = {}
        
        # Test 1: Authentication Bypass Routes
        all_results["bypass_routes"] = await tester.test_authentication_bypass_routes()
        
        # Test 2: API Key Authentication
        all_results["api_key_auth"] = await tester.test_api_key_authentication()
        
        # Test 3: Provider Override
        all_results["provider_override"] = await tester.test_provider_override()
        
        # Test 4: Chain ID Routing
        all_results["chain_id_routing"] = await tester.test_chain_id_routing()
        
        # Test 5: Combined Parameters
        all_results["combined_parameters"] = await tester.test_combined_parameters()
        
        # Test 6: Error Scenarios
        all_results["error_scenarios"] = await tester.test_error_scenarios()
    
    # Print Results Summary
    print("\n" + "=" * 60)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    
    # Authentication Bypass Routes
    bypass = all_results["bypass_routes"]
    print(f"\n🔓 AUTHENTICATION BYPASS ROUTES:")
    print(f"   /metrics: {'✅' if bypass.get('metrics', {}).get('success', False) else '❌'}")
    print(f"   /healthz: {'✅' if bypass.get('_healthz', {}).get('success', False) else '❌'}")
    print(f"   /readyz: {'✅' if bypass.get('_readyz', {}).get('success', False) else '❌'}")
    print(f"   /admin/providers: {'✅' if bypass.get('_admin_providers', {}).get('success', False) else '❌'}")
    
    # API Key Authentication
    auth = all_results["api_key_auth"]
    print(f"\n🔐 API KEY AUTHENTICATION:")
    print(f"   No API Key (401): {'✅' if auth.get('no_api_key', {}).get('actual_401', False) else '❌'}")
    print(f"   Invalid API Key (401): {'✅' if auth.get('invalid_api_key', {}).get('actual_401', False) else '❌'}")
    print(f"   Valid API Key (200): {'✅' if auth.get('valid_api_key', {}).get('actual_200', False) else '❌'}")
    
    # Provider Override
    provider = all_results["provider_override"]
    print(f"\n🎯 PROVIDER OVERRIDE:")
    successful_overrides = sum(1 for k, v in provider.items() 
                             if k.startswith('provider_override_') and v.get('success', False))
    total_overrides = sum(1 for k in provider.keys() if k.startswith('provider_override_'))
    print(f"   Successful Overrides: {successful_overrides}/{total_overrides}")
    print(f"   Normal Load Balancing: {'✅' if provider.get('no_provider_override', {}).get('success', False) else '❌'}")
    
    # Chain ID Routing
    chain = all_results["chain_id_routing"]
    print(f"\n⛓️ CHAIN ID ROUTING:")
    successful_chains = sum(1 for k, v in chain.items() 
                          if k.startswith('chain_id_') and v.get('success', False))
    total_chains = sum(1 for k in chain.keys() if k.startswith('chain_id_'))
    print(f"   Successful Chain Routes: {successful_chains}/{total_chains}")
    print(f"   Default Route: {'✅' if chain.get('default_route', {}).get('success', False) else '❌'}")
    
    # Combined Parameters
    combined = all_results["combined_parameters"]
    print(f"\n🔗 COMBINED PARAMETERS:")
    successful_combos = sum(1 for k, v in combined.items() 
                          if k.startswith('combo_') and v.get('success', False))
    total_combos = sum(1 for k in combined.keys() if k.startswith('combo_'))
    print(f"   Successful Combinations: {successful_combos}/{total_combos}")
    
    # Error Scenarios
    errors = all_results["error_scenarios"]
    print(f"\n❌ ERROR HANDLING:")
    print(f"   Malformed JSON: {'✅' if errors.get('malformed_json', {}).get('got_error', False) else '❌'}")
    print(f"   Invalid Method: {'✅' if errors.get('invalid_method', {}).get('has_error_response', False) else '❌'}")
    print(f"   Missing Method: {'✅' if errors.get('missing_method', {}).get('has_error', False) else '❌'}")
    
    print(f"\n📋 Detailed results saved to provider_override_chainid_test_results.json")
    
    # Save detailed results
    with open("provider_override_chainid_test_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print("\n✅ All tests completed!")

if __name__ == "__main__":
    asyncio.run(main())
