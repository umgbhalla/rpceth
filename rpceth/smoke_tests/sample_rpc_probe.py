#!/usr/bin/env python3
"""
Simple RPC probe script for testing the proxy server with API key authentication
"""

import asyncio
import aiohttp
import json
import time

async def test_rpc_proxy(api_key: str = "change-me"):
    """Test basic RPC functionality"""
    
    # Test data
    test_methods = [
        ("eth_blockNumber", []),
        ("eth_chainId", []),
        ("eth_gasPrice", []),
    ]
    
    async with aiohttp.ClientSession() as session:
        print("🚀 Testing RPC Proxy Server")
        print("=" * 40)
        
        for method, params in test_methods:
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": 1
            }
            
            print(f"\n📡 Testing {method}...")
            
            try:
                start_time = time.time()
                async with session.post(f"http://localhost:3000/?apikey={api_key}", 
                                      json=payload,
                                      headers={"Content-Type": "application/json"}) as response:
                    
                    latency = (time.time() - start_time) * 1000
                    result = await response.json()
                    
                    print(f"   Status: {response.status}")
                    print(f"   Latency: {latency:.1f}ms")
                    print(f"   Result: {json.dumps(result, indent=2)}")
                    
                    # Check for trace ID
                    trace_id = response.headers.get('x-trace-id')
                    if trace_id:
                        print(f"   Trace ID: {trace_id}")
                    
            except Exception as e:
                print(f"   ❌ Error: {e}")
        
        print(f"\n✅ RPC Proxy test completed!")

if __name__ == "__main__":
    asyncio.run(test_rpc_proxy())
