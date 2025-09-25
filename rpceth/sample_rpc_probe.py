import json
import time
from typing import List

import httpx

CHAINLIST_RPC_URL = "https://chainlist.org/rpcs.json"
SAMPLE_METHOD = "eth_blockNumber"
TIMEOUT_SECONDS = 5


def fetch_top_https_endpoints(limit: int = 10) -> List[str]:
    response = httpx.get(CHAINLIST_RPC_URL, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()

    for chain in payload:
        if chain.get("chain") == "ETH":
            endpoints = [
                entry["url"]
                for entry in chain.get("rpc", [])
                if entry.get("url", "").startswith("https://")
            ]
            return endpoints[:limit]

    raise RuntimeError("Ethereum chain entry not found in Chainlist data")


def probe(endpoint: str) -> dict:
    request_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": SAMPLE_METHOD,
        "params": [],
    }

    started = time.perf_counter()
    try:
        response = httpx.post(
            endpoint,
            json=request_body,
            timeout=TIMEOUT_SECONDS,
            headers={"content-type": "application/json"},
        )
        latency = time.perf_counter() - started
        status = response.status_code
        body = response.json()
        ok = response.is_success and "result" in body
        return {
            "endpoint": endpoint,
            "status": status,
            "latency_ms": round(latency * 1_000, 2),
            "ok": ok,
            "result": body.get("result"),
        }
    except Exception as exc:  # noqa: BLE001
        latency = time.perf_counter() - started
        return {
            "endpoint": endpoint,
            "status": "error",
            "latency_ms": round(latency * 1_000, 2),
            "ok": False,
            "error": str(exc),
        }


def main() -> None:
    endpoints = fetch_top_https_endpoints(limit=10)
    results = [probe(endpoint) for endpoint in endpoints]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

