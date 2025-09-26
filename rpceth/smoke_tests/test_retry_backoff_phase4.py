#!/usr/bin/env python3
"""Phase 4 retry/backoff smoke test.

This helper issues a mix of JSON-RPC requests against a running proxy server
and prints a compact summary covering success paths and expected failure paths.

Usage::

    source .venv/bin/activate  # optional virtualenv
    python3 test_retry_backoff_phase4.py --url http://localhost:3000

The proxy should already be running with a configuration that exercises retry
logic (e.g. one slow/failing provider and one healthy provider).  The script
does not attempt to manipulate provider responses; it simply records the
observed statuses and latencies so you can verify behaviour manually.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

Json = Dict[str, Any]


class RetryProbe:
    def __init__(self, base_url: str, timeout: float, api_key: str = "change-me") -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "RetryProbe":
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()

    async def call(
        self,
        method: str,
        params: Optional[List[Any]] = None,
        *,
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
            trace_id = f"retry-probe-{uuid.uuid4()}"
        headers["x-xray-id"] = trace_id

        assert self._session is not None, "session not initialised"

        start = time.perf_counter()
        async with self._session.post(f"{self.base_url}/?apikey={self.api_key}", json=payload, headers=headers) as resp:
            latency = time.perf_counter() - start
            returned_trace = resp.headers.get("x-xray-id", "")
            try:
                data = await resp.json(content_type=None)
            except aiohttp.ContentTypeError:
                text = await resp.text()
                data = {"_raw": text}

            return data, latency, returned_trace, resp.status


async def run_suite(base_url: str, timeout: float, batch: int) -> Dict[str, Any]:
    async with RetryProbe(base_url, timeout) as probe:
        success_latencies: List[float] = []
        failure_latencies: List[float] = []
        successes = 0
        failures: List[str] = []

        for _ in range(batch):
            response, latency, trace, status = await probe.call("eth_blockNumber")
            if status == 200 and "result" in response:
                success_latencies.append(latency * 1000.0)
                successes += 1
            else:
                failure_latencies.append(latency * 1000.0)
                failures.append(f"unexpected blockNumber response {status}: {response}")

        # Exercise a write-style method that should surface an error quickly.
        tx_payload = "0xdeadbeef"
        write_resp, write_latency, write_trace, write_status = await probe.call(
            "eth_sendRawTransaction", [tx_payload]
        )

        invalid_resp, invalid_latency, invalid_trace, invalid_status = await probe.call(
            "eth_totallyFakeMethod"
        )

    summary: Dict[str, Any] = {
        "base_url": base_url,
        "successes": successes,
        "batch": batch,
        "trace_roundtrip_ok": successes == 0 or write_trace.startswith("retry-probe-"),
        "write_call": {
            "status": write_status,
            "latency_ms": write_latency * 1000.0,
            "trace_echoed": write_trace.startswith("retry-probe-"),
            "error_present": "error" in write_resp,
            "response": write_resp,
        },
        "invalid_call": {
            "status": invalid_status,
            "latency_ms": invalid_latency * 1000.0,
            "trace_echoed": invalid_trace.startswith("retry-probe-"),
            "response": invalid_resp,
        },
        "failures": failures,
    }

    if success_latencies:
        summary["success_latency_ms"] = {
            "avg": statistics.mean(success_latencies),
            "p95": statistics.quantiles(success_latencies, n=20)[18]
            if len(success_latencies) > 20
            else max(success_latencies),
            "min": min(success_latencies),
            "max": max(success_latencies),
        }

    if failure_latencies:
        summary["failure_latency_ms"] = {
            "avg": statistics.mean(failure_latencies),
            "count": len(failure_latencies),
        }

    return summary


def format_summary(summary: Dict[str, Any]) -> str:
    lines = ["\n=== Retry/Backoff Smoke Test ==="]
    lines.append(f"Target URL           : {summary['base_url']}")
    lines.append(f"Successful block calls: {summary['successes']}/{summary['batch']}")

    if "success_latency_ms" in summary:
        lat = summary["success_latency_ms"]
        lines.append(
            "  Latency avg/p95/min/max (ms): "
            f"{lat['avg']:.1f} / {lat['p95']:.1f} / {lat['min']:.1f} / {lat['max']:.1f}"
        )

    if summary["failures"]:
        lines.append("  Unexpected failures:")
        for item in summary["failures"]:
            lines.append(f"    - {item}")

    write = summary["write_call"]
    lines.append("\nWrite (eth_sendRawTransaction) probe:")
    lines.append(
        f"  status={write['status']} latency={write['latency_ms']:.1f}ms error? {write['error_present']}"
    )
    if not write["trace_echoed"]:
        lines.append("  warning: trace header not echoed back")

    invalid = summary["invalid_call"]
    lines.append("Invalid method probe:")
    lines.append(
        f"  status={invalid['status']} latency={invalid['latency_ms']:.1f}ms"
        f" trace echoed? {invalid['trace_echoed']}"
    )

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:3000", help="Proxy base URL")
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Request timeout in seconds for the aiohttp client",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=5,
        help="Number of eth_blockNumber probes to issue before exercising failure cases",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = asyncio.run(run_suite(args.url, args.timeout, args.batch))
    print(format_summary(results))


if __name__ == "__main__":
    main()


