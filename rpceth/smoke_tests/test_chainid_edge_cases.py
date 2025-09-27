#!/usr/bin/env python3
"""
Chain ID Edge Cases and Error Scenario Testing
Tests malformed chain IDs, security scenarios, rate limiting per chain, and error handling
"""

import asyncio
import aiohttp
import json
import time
import random
import string
from typing import Dict, List, Optional, Any
from urllib.parse import quote, unquote

class ChainIDEdgeCaseTester:
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
    
    async def make_rpc_call(self, method: str = "eth_chainId", params: List[Any] = None, 
                           chain_id: str = None, raw_path: str = None,
                           expect_error: bool = False, timeout: int = 5) -> Dict:
        """Make an RPC call with support for raw path manipulation"""
        if params is None:
            params = []
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": random.randint(1, 1000000)
        }
        
        # Use raw path if provided, otherwise construct normally
        if raw_path is not None:
            url = f"{self.proxy_url}{raw_path}?apikey={self.api_key}"
        else:
            path = f"/{chain_id}" if chain_id else "/"
            url = f"{self.proxy_url}{path}?apikey={self.api_key}"
        
        headers = {
            "Content-Type": "application/json",
            "x-test-type": "edge-case",
            "x-chain-id": str(chain_id) if chain_id else "none"
        }
        
        start_time = time.time()
        
        try:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout_obj) as response:
                latency = time.time() - start_time
                
                try:
                    response_data = await response.json()
                except:
                    # Try to get text response for non-JSON responses
                    try:
                        text_response = await response.text()
                        response_data = {"error": {"code": -32700, "message": f"Non-JSON response: {text_response[:100]}"}}
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
                    "raw_path": raw_path,
                    "headers": dict(response.headers),
                    "expected_error": expect_error
                }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Request timeout",
                "url": url,
                "chain_id": chain_id,
                "method": method,
                "latency_ms": (time.time() - start_time) * 1000,
                "timeout": True,
                "expected_error": expect_error
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "url": url,
                "chain_id": chain_id,
                "method": method,
                "latency_ms": (time.time() - start_time) * 1000,
                "expected_error": expect_error
            }
    
    async def test_malformed_chain_ids(self) -> Dict:
        """Test various malformed and edge case chain IDs"""
        print("🚫 Testing Malformed Chain IDs...")
        
        results = {}
        
        # Various malformed chain ID scenarios
        malformed_cases = [
            # Empty and whitespace
            {"chain_id": "", "description": "empty_string"},
            {"chain_id": " ", "description": "single_space"},
            {"chain_id": "   ", "description": "multiple_spaces"},
            {"chain_id": "\t", "description": "tab_character"},
            {"chain_id": "\n", "description": "newline_character"},
            
            # Special characters
            {"chain_id": "!", "description": "exclamation"},
            {"chain_id": "@", "description": "at_symbol"},
            {"chain_id": "#", "description": "hash_symbol"},
            {"chain_id": "$", "description": "dollar_sign"},
            {"chain_id": "%", "description": "percent_sign"},
            {"chain_id": "^", "description": "caret"},
            {"chain_id": "&", "description": "ampersand"},
            {"chain_id": "*", "description": "asterisk"},
            {"chain_id": "(", "description": "open_paren"},
            {"chain_id": ")", "description": "close_paren"},
            {"chain_id": "-", "description": "hyphen"},
            {"chain_id": "=", "description": "equals"},
            {"chain_id": "+", "description": "plus"},
            {"chain_id": "[", "description": "open_bracket"},
            {"chain_id": "]", "description": "close_bracket"},
            {"chain_id": "{", "description": "open_brace"},
            {"chain_id": "}", "description": "close_brace"},
            {"chain_id": "|", "description": "pipe"},
            {"chain_id": "\\", "description": "backslash"},
            {"chain_id": ":", "description": "colon"},
            {"chain_id": ";", "description": "semicolon"},
            {"chain_id": "\"", "description": "double_quote"},
            {"chain_id": "'", "description": "single_quote"},
            {"chain_id": "<", "description": "less_than"},
            {"chain_id": ">", "description": "greater_than"},
            {"chain_id": ",", "description": "comma"},
            {"chain_id": ".", "description": "period"},
            {"chain_id": "?", "description": "question_mark"},
            {"chain_id": "/", "description": "forward_slash"},
            {"chain_id": "~", "description": "tilde"},
            {"chain_id": "`", "description": "backtick"},
            
            # Unicode and special encodings
            {"chain_id": "🔗", "description": "emoji_chain"},
            {"chain_id": "⛓️", "description": "emoji_chains"},
            {"chain_id": "α", "description": "greek_alpha"},
            {"chain_id": "中文", "description": "chinese_characters"},
            {"chain_id": "русский", "description": "cyrillic_characters"},
            {"chain_id": "العربية", "description": "arabic_characters"},
            
            # Very long strings
            {"chain_id": "a" * 1000, "description": "very_long_string"},
            {"chain_id": "1" * 500, "description": "very_long_numeric"},
            
            # Mixed invalid formats
            {"chain_id": "chain-1", "description": "hyphenated"},
            {"chain_id": "chain_1", "description": "underscored"},
            {"chain_id": "chain.1", "description": "dotted"},
            {"chain_id": "chain 1", "description": "spaced"},
            {"chain_id": "CHAIN1", "description": "uppercase"},
            {"chain_id": "Chain1", "description": "mixed_case"},
            
            # Hex-like but invalid
            {"chain_id": "0x", "description": "hex_prefix_only"},
            {"chain_id": "0xg", "description": "hex_invalid_char"},
            {"chain_id": "0x123g", "description": "hex_mixed_invalid"},
            
            # SQL injection attempts
            {"chain_id": "1'; DROP TABLE chains; --", "description": "sql_injection"},
            {"chain_id": "1 OR 1=1", "description": "sql_or_injection"},
            
            # XSS attempts
            {"chain_id": "<script>alert('xss')</script>", "description": "xss_script"},
            {"chain_id": "javascript:alert('xss')", "description": "javascript_protocol"},
            
            # Path traversal attempts
            {"chain_id": "../", "description": "path_traversal_up"},
            {"chain_id": "../../etc/passwd", "description": "path_traversal_file"},
            {"chain_id": "..\\..\\windows\\system32", "description": "windows_path_traversal"},
            
            # Command injection attempts
            {"chain_id": "; ls -la", "description": "command_injection_ls"},
            {"chain_id": "| cat /etc/passwd", "description": "command_injection_cat"},
            {"chain_id": "&& rm -rf /", "description": "command_injection_rm"},
            
            # Null bytes and control characters
            {"chain_id": "1\x00", "description": "null_byte"},
            {"chain_id": "1\x01\x02\x03", "description": "control_chars"},
            
            # Extremely large numbers
            {"chain_id": "999999999999999999999999999999999999999999", "description": "huge_number"},
            {"chain_id": str(2**256), "description": "power_of_2_256"},
            
            # Negative numbers
            {"chain_id": "-1", "description": "negative_one"},
            {"chain_id": "-999", "description": "negative_large"},
            
            # Floating point
            {"chain_id": "1.5", "description": "decimal_point"},
            {"chain_id": "1.0", "description": "decimal_zero"},
            {"chain_id": "3.14159", "description": "pi"},
            
            # Scientific notation
            {"chain_id": "1e10", "description": "scientific_notation"},
            {"chain_id": "1E+5", "description": "scientific_positive"},
            {"chain_id": "1e-5", "description": "scientific_negative"},
        ]
        
        for case in malformed_cases:
            result = await self.make_rpc_call(
                chain_id=case["chain_id"], 
                expect_error=True
            )
            
            results[case["description"]] = {
                "chain_id": case["chain_id"],
                "description": case["description"],
                "success": result.get("success", False),
                "status_code": result.get("status_code", 0),
                "expected_error": True,
                "properly_rejected": not result.get("success", False) or result.get("status_code", 0) >= 400,
                "response": result.get("response", {}),
                "error": result.get("error"),
                "latency_ms": result.get("latency_ms", 0),
                "trace_id": result.get("trace_id")
            }
        
        return results
    
    async def test_url_encoding_scenarios(self) -> Dict:
        """Test URL encoding and decoding scenarios"""
        print("🔗 Testing URL Encoding Scenarios...")
        
        results = {}
        
        # URL encoding test cases
        encoding_cases = [
            # Standard URL encoding
            {"original": "chain 1", "encoded": "chain%201", "description": "space_encoded"},
            {"original": "chain+1", "encoded": "chain%2B1", "description": "plus_encoded"},
            {"original": "chain&1", "encoded": "chain%261", "description": "ampersand_encoded"},
            {"original": "chain=1", "encoded": "chain%3D1", "description": "equals_encoded"},
            {"original": "chain?1", "encoded": "chain%3F1", "description": "question_encoded"},
            {"original": "chain#1", "encoded": "chain%231", "description": "hash_encoded"},
            {"original": "chain/1", "encoded": "chain%2F1", "description": "slash_encoded"},
            {"original": "chain\\1", "encoded": "chain%5C1", "description": "backslash_encoded"},
            
            # Double encoding
            {"original": "chain 1", "encoded": "chain%25201", "description": "double_encoded_space"},
            
            # Mixed encoding
            {"original": "chain 1&test=value", "encoded": "chain%201%26test%3Dvalue", "description": "complex_encoded"},
        ]
        
        for case in encoding_cases:
            # Test with encoded version
            result_encoded = await self.make_rpc_call(chain_id=case["encoded"])
            
            # Test with raw path manipulation
            raw_path = f"/{case['encoded']}"
            result_raw = await self.make_rpc_call(raw_path=raw_path)
            
            results[f"{case['description']}_encoded"] = {
                "original": case["original"],
                "encoded": case["encoded"],
                "success": result_encoded["success"],
                "status_code": result_encoded["status_code"],
                "response": result_encoded.get("response", {}),
                "latency_ms": result_encoded.get("latency_ms", 0),
                "trace_id": result_encoded.get("trace_id")
            }
            
            results[f"{case['description']}_raw_path"] = {
                "raw_path": raw_path,
                "success": result_raw["success"],
                "status_code": result_raw["status_code"],
                "response": result_raw.get("response", {}),
                "latency_ms": result_raw.get("latency_ms", 0),
                "trace_id": result_raw.get("trace_id")
            }
        
        return results
    
    async def test_rate_limiting_per_chain(self) -> Dict:
        """Test rate limiting behavior per chain"""
        print("🚦 Testing Rate Limiting Per Chain...")
        
        results = {}
        
        # Test rapid requests to the same chain
        test_chains = ["1", "eth", "137", "polygon"]
        
        for chain in test_chains:
            chain_results = []
            start_time = time.time()
            
            # Make rapid requests (50 requests as fast as possible)
            for i in range(50):
                result = await self.make_rpc_call("eth_blockNumber", chain_id=chain)
                chain_results.append({
                    "request_num": i + 1,
                    "success": result["success"],
                    "status_code": result["status_code"],
                    "latency_ms": result.get("latency_ms", 0),
                    "error": result.get("error"),
                    "trace_id": result.get("trace_id"),
                    "timestamp": time.time()
                })
                
                # Check for rate limiting indicators
                if result["status_code"] == 429:  # Too Many Requests
                    break
            
            total_time = time.time() - start_time
            successful_requests = [r for r in chain_results if r["success"]]
            rate_limited_requests = [r for r in chain_results if r["status_code"] == 429]
            
            results[f"chain_{chain}"] = {
                "chain": chain,
                "total_requests": len(chain_results),
                "successful_requests": len(successful_requests),
                "rate_limited_requests": len(rate_limited_requests),
                "success_rate": len(successful_requests) / len(chain_results) if chain_results else 0,
                "rate_limit_triggered": len(rate_limited_requests) > 0,
                "total_time_seconds": total_time,
                "requests_per_second": len(chain_results) / total_time,
                "avg_latency_ms": sum(r["latency_ms"] for r in successful_requests) / len(successful_requests) if successful_requests else 0,
                "requests": chain_results
            }
        
        return results
    
    async def test_concurrent_invalid_requests(self) -> Dict:
        """Test concurrent invalid requests to stress error handling"""
        print("💥 Testing Concurrent Invalid Requests...")
        
        results = {}
        
        # Create a mix of invalid requests
        invalid_scenarios = [
            {"chain_id": "invalid", "method": "eth_chainId"},
            {"chain_id": "999999", "method": "eth_blockNumber"},
            {"chain_id": "", "method": "eth_gasPrice"},
            {"chain_id": "🔗", "method": "invalid_method"},
            {"chain_id": "1'; DROP TABLE", "method": "eth_chainId"},
            {"chain_id": "../../../etc", "method": "eth_blockNumber"},
            {"chain_id": "null", "method": "eth_chainId"},
            {"chain_id": "undefined", "method": "eth_blockNumber"},
        ]
        
        # Create concurrent tasks
        concurrent_tasks = []
        for i in range(30):  # 30 concurrent invalid requests
            scenario = random.choice(invalid_scenarios)
            task = self.make_rpc_call(
                method=scenario["method"],
                chain_id=scenario["chain_id"],
                expect_error=True
            )
            concurrent_tasks.append({
                "task": task,
                "scenario": scenario,
                "request_num": i + 1
            })
        
        # Execute all tasks concurrently
        start_time = time.time()
        task_results = await asyncio.gather(*[task_info["task"] for task_info in concurrent_tasks])
        total_time = time.time() - start_time
        
        # Analyze results
        properly_rejected = 0
        server_errors = 0
        timeouts = 0
        unexpected_success = 0
        
        for i, result in enumerate(task_results):
            scenario = concurrent_tasks[i]["scenario"]
            
            if result.get("timeout"):
                timeouts += 1
            elif result["status_code"] >= 500:
                server_errors += 1
            elif not result["success"] or result["status_code"] >= 400:
                properly_rejected += 1
            else:
                unexpected_success += 1
        
        results["concurrent_invalid_summary"] = {
            "total_requests": len(concurrent_tasks),
            "properly_rejected": properly_rejected,
            "server_errors": server_errors,
            "timeouts": timeouts,
            "unexpected_success": unexpected_success,
            "total_time_seconds": total_time,
            "requests_per_second": len(concurrent_tasks) / total_time,
            "error_handling_rate": (properly_rejected + server_errors) / len(concurrent_tasks)
        }
        
        # Store individual results
        for i, result in enumerate(task_results):
            scenario = concurrent_tasks[i]["scenario"]
            results[f"invalid_request_{i+1}"] = {
                "chain_id": scenario["chain_id"],
                "method": scenario["method"],
                "success": result["success"],
                "status_code": result["status_code"],
                "properly_handled": not result["success"] or result["status_code"] >= 400,
                "latency_ms": result.get("latency_ms", 0),
                "error": result.get("error"),
                "trace_id": result.get("trace_id")
            }
        
        return results
    
    async def test_chain_id_case_sensitivity(self) -> Dict:
        """Test case sensitivity in chain ID handling"""
        print("🔤 Testing Chain ID Case Sensitivity...")
        
        results = {}
        
        # Case sensitivity test cases
        case_tests = [
            {"original": "eth", "variants": ["ETH", "Eth", "eTh", "etH"]},
            {"original": "polygon", "variants": ["POLYGON", "Polygon", "PoLyGoN"]},
            {"original": "bsc", "variants": ["BSC", "Bsc", "bSc", "bsC"]},
            {"original": "arbitrum", "variants": ["ARBITRUM", "Arbitrum", "ArBiTrUm"]},
        ]
        
        for test_case in case_tests:
            original_result = await self.make_rpc_call(chain_id=test_case["original"])
            
            case_results = {
                "original": {
                    "chain_id": test_case["original"],
                    "success": original_result["success"],
                    "status_code": original_result["status_code"],
                    "chain_id_result": original_result.get("response", {}).get("result"),
                    "latency_ms": original_result.get("latency_ms", 0),
                    "trace_id": original_result.get("trace_id")
                }
            }
            
            for variant in test_case["variants"]:
                variant_result = await self.make_rpc_call(chain_id=variant)
                case_results[f"variant_{variant}"] = {
                    "chain_id": variant,
                    "success": variant_result["success"],
                    "status_code": variant_result["status_code"],
                    "chain_id_result": variant_result.get("response", {}).get("result"),
                    "matches_original": (
                        variant_result.get("response", {}).get("result") == 
                        original_result.get("response", {}).get("result")
                    ),
                    "latency_ms": variant_result.get("latency_ms", 0),
                    "trace_id": variant_result.get("trace_id")
                }
            
            results[test_case["original"]] = case_results
        
        return results

async def main():
    print("🚀 Starting Chain ID Edge Cases and Error Scenario Tests")
    print("=" * 70)
    
    async with ChainIDEdgeCaseTester() as tester:
        all_results = {}
        
        # Test 1: Malformed Chain IDs
        all_results["malformed_chain_ids"] = await tester.test_malformed_chain_ids()
        
        # Test 2: URL Encoding Scenarios
        all_results["url_encoding"] = await tester.test_url_encoding_scenarios()
        
        # Test 3: Rate Limiting Per Chain
        all_results["rate_limiting"] = await tester.test_rate_limiting_per_chain()
        
        # Test 4: Concurrent Invalid Requests
        all_results["concurrent_invalid"] = await tester.test_concurrent_invalid_requests()
        
        # Test 5: Case Sensitivity
        all_results["case_sensitivity"] = await tester.test_chain_id_case_sensitivity()
    
    # Print Results Summary
    print("\n" + "=" * 70)
    print("📊 CHAIN ID EDGE CASES TEST RESULTS SUMMARY")
    print("=" * 70)
    
    # Malformed Chain IDs
    malformed = all_results["malformed_chain_ids"]
    properly_rejected = sum(1 for v in malformed.values() if v.get("properly_rejected", False))
    total_malformed = len(malformed)
    print(f"\n🚫 MALFORMED CHAIN IDS:")
    print(f"   Properly Rejected: {properly_rejected}/{total_malformed} "
          f"({'✅' if properly_rejected > total_malformed * 0.9 else '❌'})")
    
    # URL Encoding
    encoding = all_results["url_encoding"]
    encoding_success = sum(1 for k, v in encoding.items() if v.get("success", False))
    encoding_total = len(encoding)
    print(f"\n🔗 URL ENCODING:")
    print(f"   Handled Correctly: {encoding_success}/{encoding_total}")
    
    # Rate Limiting
    rate_limiting = all_results["rate_limiting"]
    print(f"\n🚦 RATE LIMITING:")
    for chain_key, chain_data in rate_limiting.items():
        if chain_key.startswith("chain_"):
            chain = chain_data["chain"]
            success_rate = chain_data["success_rate"]
            rate_limited = chain_data["rate_limit_triggered"]
            rps = chain_data["requests_per_second"]
            print(f"   {chain}: {success_rate:.1%} success, {rps:.1f} req/s, "
                  f"rate limited: {'✅' if rate_limited else '❌'}")
    
    # Concurrent Invalid Requests
    concurrent = all_results["concurrent_invalid"]["concurrent_invalid_summary"]
    error_handling_rate = concurrent.get("error_handling_rate", 0)
    server_errors = concurrent.get("server_errors", 0)
    print(f"\n💥 CONCURRENT INVALID REQUESTS:")
    print(f"   Error Handling Rate: {error_handling_rate:.1%} "
          f"({'✅' if error_handling_rate > 0.8 else '❌'})")
    print(f"   Server Errors: {server_errors} ({'✅' if server_errors == 0 else '❌'})")
    
    # Case Sensitivity
    case_sensitivity = all_results["case_sensitivity"]
    print(f"\n🔤 CASE SENSITIVITY:")
    for chain_name, chain_data in case_sensitivity.items():
        original_success = chain_data["original"]["success"]
        variant_matches = sum(1 for k, v in chain_data.items() 
                             if k.startswith("variant_") and v.get("matches_original", False))
        variant_total = sum(1 for k in chain_data.keys() if k.startswith("variant_"))
        print(f"   {chain_name}: original {'✅' if original_success else '❌'}, "
              f"{variant_matches}/{variant_total} variants match")
    
    print(f"\n📋 Detailed results saved to chainid_edge_cases_test_results.json")
    
    # Save detailed results
    with open("chainid_edge_cases_test_results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print("\n✅ All Chain ID edge case tests completed!")
    
    # Security summary
    malformed_properly_handled = properly_rejected / total_malformed if total_malformed > 0 else 0
    security_score = (malformed_properly_handled + error_handling_rate) / 2
    print(f"\n🔒 SECURITY SUMMARY:")
    print(f"   Overall Security Score: {security_score:.1%} "
          f"({'✅' if security_score > 0.8 else '⚠️' if security_score > 0.6 else '❌'})")

if __name__ == "__main__":
    asyncio.run(main())
