#!/usr/bin/env python3
"""
Chain ID Test Suite Runner
Executes all chain ID related tests and provides comprehensive reporting
"""

import asyncio
import subprocess
import sys
import time
import json
import os
from pathlib import Path
from typing import Dict, List, Any

class ChainIDTestRunner:
    def __init__(self):
        self.test_files = [
            "test_chainid_comprehensive.py",
            "test_chainid_multichain_scenarios.py", 
            "test_chainid_edge_cases.py"
        ]
        self.results = {}
        self.start_time = None
        
    def run_test_file(self, test_file: str) -> Dict[str, Any]:
        """Run a single test file and capture results"""
        print(f"\n{'='*60}")
        print(f"🧪 Running {test_file}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        try:
            # Run the test file
            result = subprocess.run(
                [sys.executable, test_file],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            duration = time.time() - start_time
            
            # Parse the output
            stdout_lines = result.stdout.split('\n')
            stderr_lines = result.stderr.split('\n')
            
            # Look for result file
            result_file = None
            if "comprehensive" in test_file:
                result_file = "chainid_comprehensive_test_results.json"
            elif "multichain" in test_file:
                result_file = "chainid_multichain_test_results.json"
            elif "edge_cases" in test_file:
                result_file = "chainid_edge_cases_test_results.json"
            
            # Try to load detailed results
            detailed_results = None
            if result_file and os.path.exists(result_file):
                try:
                    with open(result_file, 'r') as f:
                        detailed_results = json.load(f)
                except:
                    detailed_results = None
            
            return {
                "test_file": test_file,
                "success": result.returncode == 0,
                "return_code": result.returncode,
                "duration_seconds": duration,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "stdout_lines": len(stdout_lines),
                "stderr_lines": len(stderr_lines),
                "detailed_results": detailed_results,
                "result_file": result_file
            }
            
        except subprocess.TimeoutExpired:
            return {
                "test_file": test_file,
                "success": False,
                "return_code": -1,
                "duration_seconds": time.time() - start_time,
                "error": "Test timed out after 5 minutes",
                "timeout": True
            }
        except Exception as e:
            return {
                "test_file": test_file,
                "success": False,
                "return_code": -1,
                "duration_seconds": time.time() - start_time,
                "error": str(e)
            }
    
    def analyze_comprehensive_results(self, results: Dict) -> Dict:
        """Analyze comprehensive test results"""
        if not results or not results.get("detailed_results"):
            return {"error": "No detailed results available"}
        
        detailed = results["detailed_results"]
        analysis = {}
        
        # Basic routing analysis
        if "basic_routing" in detailed:
            basic = detailed["basic_routing"]
            numeric_success = sum(1 for k, v in basic.items() 
                                if k.startswith('numeric_chain_') and v.get('success', False))
            numeric_total = sum(1 for k in basic.keys() if k.startswith('numeric_chain_'))
            
            analysis["basic_routing"] = {
                "default_route_works": basic.get('default_route', {}).get('success', False),
                "numeric_chains_success_rate": numeric_success / numeric_total if numeric_total > 0 else 0,
                "numeric_chains_working": numeric_success,
                "numeric_chains_total": numeric_total
            }
        
        # Chain aliases analysis
        if "chain_aliases" in detailed:
            aliases = detailed["chain_aliases"]
            alias_success = sum(1 for k, v in aliases.items() 
                              if k.startswith('alias_') and v.get('success', False))
            alias_total = sum(1 for k in aliases.keys() if k.startswith('alias_'))
            
            analysis["chain_aliases"] = {
                "aliases_success_rate": alias_success / alias_total if alias_total > 0 else 0,
                "aliases_working": alias_success,
                "aliases_total": alias_total
            }
        
        # Performance analysis
        if "performance" in detailed:
            perf = detailed["performance"]
            analysis["performance"] = {}
            for scenario_name, scenario_data in perf.items():
                analysis["performance"][scenario_name] = {
                    "success_rate": scenario_data.get("success_rate", 0),
                    "avg_latency_ms": scenario_data.get("avg_latency_ms", 0),
                    "requests_per_second": scenario_data.get("requests_per_second", 0)
                }
        
        return analysis
    
    def analyze_multichain_results(self, results: Dict) -> Dict:
        """Analyze multi-chain test results"""
        if not results or not results.get("detailed_results"):
            return {"error": "No detailed results available"}
        
        detailed = results["detailed_results"]
        analysis = {}
        
        # Cross-chain consistency
        if "cross_chain_consistency" in detailed:
            consistency = detailed["cross_chain_consistency"]
            analysis["cross_chain_consistency"] = {}
            
            for chain_name, chain_data in consistency.items():
                numeric_match = chain_data.get("numeric_id", {}).get("matches_expected", False)
                alias_matches = sum(1 for k, v in chain_data.items() 
                                  if k.startswith("alias_") and v.get("matches_expected", False))
                alias_total = sum(1 for k in chain_data.keys() if k.startswith("alias_"))
                
                analysis["cross_chain_consistency"][chain_name] = {
                    "numeric_id_correct": numeric_match,
                    "alias_success_rate": alias_matches / alias_total if alias_total > 0 else 0
                }
        
        # Concurrent requests analysis
        if "concurrent_requests" in detailed:
            concurrent = detailed["concurrent_requests"].get("concurrent_summary", {})
            analysis["concurrent_requests"] = {
                "success_rate": concurrent.get("success_rate", 0),
                "requests_per_second": concurrent.get("requests_per_second", 0),
                "avg_latency_ms": concurrent.get("avg_latency_ms", 0)
            }
        
        return analysis
    
    def analyze_edge_cases_results(self, results: Dict) -> Dict:
        """Analyze edge cases test results"""
        if not results or not results.get("detailed_results"):
            return {"error": "No detailed results available"}
        
        detailed = results["detailed_results"]
        analysis = {}
        
        # Malformed chain IDs analysis
        if "malformed_chain_ids" in detailed:
            malformed = detailed["malformed_chain_ids"]
            properly_rejected = sum(1 for v in malformed.values() 
                                  if v.get("properly_rejected", False))
            total_malformed = len(malformed)
            
            analysis["malformed_chain_ids"] = {
                "properly_rejected_rate": properly_rejected / total_malformed if total_malformed > 0 else 0,
                "properly_rejected": properly_rejected,
                "total_tested": total_malformed
            }
        
        # Concurrent invalid requests analysis
        if "concurrent_invalid" in detailed:
            concurrent = detailed["concurrent_invalid"].get("concurrent_invalid_summary", {})
            analysis["concurrent_invalid"] = {
                "error_handling_rate": concurrent.get("error_handling_rate", 0),
                "server_errors": concurrent.get("server_errors", 0),
                "properly_rejected": concurrent.get("properly_rejected", 0)
            }
        
        return analysis
    
    def generate_summary_report(self) -> Dict:
        """Generate overall summary report"""
        summary = {
            "test_execution": {
                "total_tests": len(self.test_files),
                "successful_tests": sum(1 for r in self.results.values() if r.get("success", False)),
                "failed_tests": sum(1 for r in self.results.values() if not r.get("success", False)),
                "total_duration_seconds": sum(r.get("duration_seconds", 0) for r in self.results.values()),
                "start_time": self.start_time,
                "end_time": time.time()
            },
            "test_analyses": {}
        }
        
        # Analyze each test's results
        for test_name, test_results in self.results.items():
            if "comprehensive" in test_name:
                summary["test_analyses"][test_name] = self.analyze_comprehensive_results(test_results)
            elif "multichain" in test_name:
                summary["test_analyses"][test_name] = self.analyze_multichain_results(test_results)
            elif "edge_cases" in test_name:
                summary["test_analyses"][test_name] = self.analyze_edge_cases_results(test_results)
        
        # Overall health score
        scores = []
        
        # Basic functionality score
        comp_analysis = summary["test_analyses"].get("test_chainid_comprehensive.py", {})
        if "basic_routing" in comp_analysis:
            basic_score = comp_analysis["basic_routing"].get("numeric_chains_success_rate", 0)
            scores.append(basic_score)
        
        # Multi-chain score
        multi_analysis = summary["test_analyses"].get("test_chainid_multichain_scenarios.py", {})
        if "concurrent_requests" in multi_analysis:
            concurrent_score = multi_analysis["concurrent_requests"].get("success_rate", 0)
            scores.append(concurrent_score)
        
        # Security score
        edge_analysis = summary["test_analyses"].get("test_chainid_edge_cases.py", {})
        if "malformed_chain_ids" in edge_analysis:
            security_score = edge_analysis["malformed_chain_ids"].get("properly_rejected_rate", 0)
            scores.append(security_score)
        
        summary["overall_health_score"] = sum(scores) / len(scores) if scores else 0
        
        return summary
    
    def print_summary_report(self, summary: Dict):
        """Print a formatted summary report"""
        print("\n" + "="*80)
        print("🎯 CHAIN ID TEST SUITE SUMMARY REPORT")
        print("="*80)
        
        # Test execution summary
        exec_summary = summary["test_execution"]
        print(f"\n📊 TEST EXECUTION SUMMARY:")
        print(f"   Total Tests: {exec_summary['total_tests']}")
        print(f"   Successful: {exec_summary['successful_tests']} ✅")
        print(f"   Failed: {exec_summary['failed_tests']} {'❌' if exec_summary['failed_tests'] > 0 else '✅'}")
        print(f"   Total Duration: {exec_summary['total_duration_seconds']:.1f} seconds")
        
        # Overall health score
        health_score = summary["overall_health_score"]
        health_emoji = "✅" if health_score > 0.8 else "⚠️" if health_score > 0.6 else "❌"
        print(f"\n🏥 OVERALL HEALTH SCORE: {health_score:.1%} {health_emoji}")
        
        # Individual test analysis
        print(f"\n📋 INDIVIDUAL TEST ANALYSIS:")
        
        for test_name, analysis in summary["test_analyses"].items():
            if "error" in analysis:
                print(f"   {test_name}: ❌ {analysis['error']}")
                continue
                
            print(f"\n   📁 {test_name}:")
            
            if "comprehensive" in test_name:
                if "basic_routing" in analysis:
                    basic = analysis["basic_routing"]
                    print(f"      Basic Routing: {basic['numeric_chains_success_rate']:.1%} "
                          f"({basic['numeric_chains_working']}/{basic['numeric_chains_total']})")
                
                if "chain_aliases" in analysis:
                    aliases = analysis["chain_aliases"]
                    print(f"      Chain Aliases: {aliases['aliases_success_rate']:.1%} "
                          f"({aliases['aliases_working']}/{aliases['aliases_total']})")
                
                if "performance" in analysis:
                    perf = analysis["performance"]
                    for scenario, metrics in perf.items():
                        print(f"      {scenario}: {metrics['success_rate']:.1%} success, "
                              f"{metrics['avg_latency_ms']:.1f}ms avg")
            
            elif "multichain" in test_name:
                if "cross_chain_consistency" in analysis:
                    consistency = analysis["cross_chain_consistency"]
                    for chain, metrics in consistency.items():
                        print(f"      {chain}: numeric {'✅' if metrics['numeric_id_correct'] else '❌'}, "
                              f"aliases {metrics['alias_success_rate']:.1%}")
                
                if "concurrent_requests" in analysis:
                    concurrent = analysis["concurrent_requests"]
                    print(f"      Concurrent: {concurrent['success_rate']:.1%} success, "
                          f"{concurrent['requests_per_second']:.1f} req/s")
            
            elif "edge_cases" in test_name:
                if "malformed_chain_ids" in analysis:
                    malformed = analysis["malformed_chain_ids"]
                    print(f"      Security: {malformed['properly_rejected_rate']:.1%} properly rejected "
                          f"({malformed['properly_rejected']}/{malformed['total_tested']})")
                
                if "concurrent_invalid" in analysis:
                    invalid = analysis["concurrent_invalid"]
                    print(f"      Error Handling: {invalid['error_handling_rate']:.1%}, "
                          f"{invalid['server_errors']} server errors")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        if health_score < 0.6:
            print("   🚨 CRITICAL: Chain ID routing has significant issues")
            print("   - Review chain ID parameter extraction in proxy handler")
            print("   - Implement proper chain validation and routing logic")
            print("   - Add comprehensive error handling for invalid chain IDs")
        elif health_score < 0.8:
            print("   ⚠️  WARNING: Chain ID routing needs improvement")
            print("   - Enhance chain alias support")
            print("   - Improve error handling for edge cases")
            print("   - Consider implementing chain-specific provider routing")
        else:
            print("   ✅ GOOD: Chain ID routing is working well")
            print("   - Consider adding more chain aliases for better UX")
            print("   - Monitor performance under high load")
    
    async def run_all_tests(self):
        """Run all chain ID tests"""
        print("🚀 Starting Chain ID Test Suite")
        print(f"Tests to run: {', '.join(self.test_files)}")
        
        self.start_time = time.time()
        
        # Change to the smoke_tests directory
        original_dir = os.getcwd()
        script_dir = Path(__file__).parent
        os.chdir(script_dir)
        
        try:
            # Run each test file
            for test_file in self.test_files:
                if os.path.exists(test_file):
                    result = self.run_test_file(test_file)
                    self.results[test_file] = result
                    
                    if result["success"]:
                        print(f"✅ {test_file} completed successfully")
                    else:
                        print(f"❌ {test_file} failed")
                        if "error" in result:
                            print(f"   Error: {result['error']}")
                        if result.get("stderr"):
                            print(f"   Stderr: {result['stderr'][:200]}...")
                else:
                    print(f"❌ {test_file} not found")
                    self.results[test_file] = {
                        "test_file": test_file,
                        "success": False,
                        "error": "Test file not found"
                    }
        
        finally:
            os.chdir(original_dir)
        
        # Generate and display summary
        summary = self.generate_summary_report()
        self.print_summary_report(summary)
        
        # Save detailed results
        with open("chainid_test_suite_results.json", "w") as f:
            json.dump({
                "summary": summary,
                "detailed_results": self.results
            }, f, indent=2, default=str)
        
        print(f"\n📋 Detailed results saved to chainid_test_suite_results.json")
        
        return summary

async def main():
    runner = ChainIDTestRunner()
    summary = await runner.run_all_tests()
    
    # Exit with appropriate code
    if summary["test_execution"]["failed_tests"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
