#!/usr/bin/env python3
"""Condensed read-heavy smoke tests for the RPC proxy."""

import asyncio
import time
from typing import Dict, List

import aiohttp


READ_METHODS: Dict[str, List] = {
    "eth_blockNumber": [],
    "eth_chainId": [],
    "eth_gasPrice": [],
    "eth_getBalance": [
        "0x0000000000000000000000000000000000000000",
        "latest",
    ],
    "eth_getBlockByNumber": ["latest", False],
}


class ReadSmokeTester:
    def __init__(
        self,
        base_url: str = "http://localhost:3000",
        api_key: str = "change-me",
        chains: List[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.chains = chains or [
            "",  # default chain
            "eth",
            "1",
            "polygon",
            "137",
            "bsc",
            "56",
        ]
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "ReadSmokeTester":
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self.session:
            await self.session.close()

    async def call(self, chain: str, method: str, params: List) -> Dict:
        assert self.session is not None
        chain_path = f"/{chain}" if chain else "/"
        url = f"{self.base_url}{chain_path}?apikey={self.api_key}"
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": params,
        }
        start = time.perf_counter()
        async with self.session.post(url, json=payload) as resp:
            latency = (time.perf_counter() - start) * 1000
            data = await resp.json(content_type=None)
            return {
                "status": resp.status,
                "latency_ms": latency,
                "body": data,
            }

    async def run(self) -> Dict:
        results: Dict[str, Dict[str, Dict]] = {}
        for chain in self.chains:
            chain_label = chain or "default"
            chain_results: Dict[str, Dict] = {}
            for method, params in READ_METHODS.items():
                try:
                    response = await self.call(chain, method, params)
                    chain_results[method] = {
                        "ok": response["status"] == 200 and "result" in response["body"],
                        "status": response["status"],
                        "latency_ms": round(response["latency_ms"], 2),
                        "result": response["body"].get("result"),
                        "error": response["body"].get("error"),
                    }
                except Exception as exc:  # pragma: no cover - smoke diagnostics
                    chain_results[method] = {
                        "ok": False,
                        "status": "exception",
                        "latency_ms": 0.0,
                        "result": None,
                        "error": str(exc),
                    }
                await asyncio.sleep(0.05)
            results[chain_label] = chain_results
        return results


async def main() -> None:
    print("🚀 Starting condensed read-method smoke test")
    async with ReadSmokeTester() as tester:
        results = await tester.run()

    successes = sum(
        1
        for chain_results in results.values()
        for method_result in chain_results.values()
        if method_result["ok"]
    )
    total = len(results) * len(READ_METHODS)

    print(f"Completed {total} checks: {successes} succeeded, {total - successes} failed")
    for chain, chain_results in results.items():
        print(f"\nChain '{chain}':")
        for method, outcome in chain_results.items():
            status = "✅" if outcome["ok"] else "❌"
            print(
                f"  {status} {method} -> status={outcome['status']} latency={outcome['latency_ms']}ms"
            )

    with open("smoke_tests_alpha/read_smoke_results.json", "w") as f:
        import json

        json.dump(results, f, indent=2)

    if successes != total:
        raise SystemExit("Some read-method smoke checks failed")


if __name__ == "__main__":
    asyncio.run(main())

