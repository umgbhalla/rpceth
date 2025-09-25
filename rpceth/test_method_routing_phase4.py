#!/usr/bin/env python3
"""
Phase 4 Method Routing Smoke Tests

This script exercises the proxy's method-specific routing configuration by
issuing both read-heavy and write-style JSON-RPC calls.  It assumes the proxy
server is already running locally (e.g. `cargo run -p proxy-server`) and will
report high level success metrics along with basic latency statistics.

Usage:
    source .venv/bin/activate  # if virtualenv available
    python3 test_method_routing_phase4.py --url http://localhost:3000
"""

import argparse
import asyncio
import statistics
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


Json = Dict[str, Any]


class MethodRoutingTester:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "MethodRoutingTester":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()

    async def call(
        self,
        method: str,
        params: Optional[List[Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Tuple[Json, float, str, int]:
        if params is None:
            params = []

        payload: Json = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": int(time.time() * 1000),
        }

        headers = {"content-type": "application/json"}
        if trace_id is None:
            trace_id = f"phase4-{uuid.uuid4()}"
        headers["x-xray-id"] = trace_id

        assert self._session is not None, "session not initialised"
        start = time.perf_counter()
        async with self._session.post(self.base_url, json=payload, headers=headers) as resp:
            latency = time.perf_counter() - start
            data = await resp.json(content_type=None)
            returned_trace = resp.headers.get("x-xray-id", "")
            return data, latency, returned_trace, resp.status

    async def exercise_read_methods(self) -> Dict[str, Any]:
        latencies: List[float] = []
        failures: List[str] = []

        read_methods = [
            ("eth_blockNumber", []),
            ("eth_getBlockByNumber", ["latest", False]),
            ("net_version", []),
        ]

        for name, params in read_methods:
            response, latency, trace, status = await self.call(name, params)
            if "result" in response:
                latencies.append(latency * 1000.0)
            else:
                failures.append(f"{name}: {response.get('error')}")

        summary: Dict[str, Any] = {
            "method_count": len(read_methods),
            "success_count": len(read_methods) - len(failures),
            "failures": failures,
        }
        if latencies:
            summary.update(
                {
                    "avg_latency_ms": statistics.mean(latencies),
                    "p95_latency_ms": statistics.quantiles(latencies, n=20)[18]
                    if len(latencies) > 20
                    else max(latencies),
                    "min_latency_ms": min(latencies),
                    "max_latency_ms": max(latencies),
                }
            )

        return summary

    async def exercise_write_method(self) -> Dict[str, Any]:
        """Send an invalid raw transaction to ensure the proxy returns an error quickly."""

        payload = "0xdeadbeef"
        response, latency, trace_id, status = await self.call(
            "eth_sendRawTransaction", [payload]
        )

        return {
            "status": status,
            "latency_ms": latency * 1000.0,
            "trace_id_echoed": trace_id.startswith("phase4-"),
            "has_error": "error" in response,
            "error": response.get("error"),
        }

    async def sanity_check_invalid_method(self) -> Dict[str, Any]:
        response, latency, trace_id, status = await self.call("eth_totallyFakeMethod")
        return {
            "status": status,
            "latency_ms": latency * 1000.0,
            "trace_id_echoed": trace_id.startswith("phase4-"),
            "error_present": "error" in response,
        }


async def run_tests(base_url: str) -> Dict[str, Any]:
    async with MethodRoutingTester(base_url) as tester:
        read_summary = await tester.exercise_read_methods()
        write_summary = await tester.exercise_write_method()
        invalid_summary = await tester.sanity_check_invalid_method()

    return {
        "read_methods": read_summary,
        "write_method": write_summary,
        "invalid_method": invalid_summary,
    }


def format_report(results: Dict[str, Any]) -> str:
    lines = ["\n=== Phase 4 Method Routing Smoke Test ==="]

    read = results["read_methods"]
    lines.append(
        f"Read Methods: {read['success_count']}/{read['method_count']} succeeded"
    )
    if "avg_latency_ms" in read:
        lines.append(
            "  Latency avg/p95/min/max (ms): "
            f"{read['avg_latency_ms']:.1f} / {read['p95_latency_ms']:.1f} / "
            f"{read['min_latency_ms']:.1f} / {read['max_latency_ms']:.1f}"
        )
    if read["failures"]:
        lines.append("  Failures:")
        for failure in read["failures"]:
            lines.append(f"    - {failure}")

    write = results["write_method"]
    lines.append(
        "Write Method eth_sendRawTransaction: "
        + ("error returned" if write["has_error"] else "unexpected success")
    )
    lines.append(
        f"  Status {write['status']} latency {write['latency_ms']:.1f}ms"
        f" trace echoed? {write['trace_id_echoed']}"
    )
    if write.get("error"):
        lines.append(f"  Error: {write['error']}")

    invalid = results["invalid_method"]
    lines.append(
        "Invalid Method Handling: "
        + ("error surfaced" if invalid["error_present"] else "missing error")
    )
    lines.append(
        f"  Status {invalid['status']} latency {invalid['latency_ms']:.1f}ms"
        f" trace echoed? {invalid['trace_id_echoed']}"
    )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://localhost:3000",
        help="Base URL for the running proxy server",
    )
    args = parser.parse_args()

    results = asyncio.run(run_tests(args.url))
    print(format_report(results))


if __name__ == "__main__":
    main()

