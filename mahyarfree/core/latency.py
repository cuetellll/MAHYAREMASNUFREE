"""Latency measurement.

Two layers are used:

*   ``tcp_ping`` – a raw TCP handshake, fast enough to probe hundreds of nodes
    and the number shown in the server list.
*   ``clash_delay`` – a real HTTP request performed *through* a running core,
    used to verify that a node actually carries traffic.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional


def tcp_ping(host: str, port: int, timeout: float = 2.5) -> Optional[int]:
    if not host or not port:
        return None
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            elapsed = (time.perf_counter() - start) * 1000
        return max(1, int(round(elapsed)))
    except Exception:
        return None


def tcp_ping_best(host: str, port: int, timeout: float = 2.5, attempts: int = 2) -> Optional[int]:
    """Fastest of a couple of attempts – smoother than a single sample."""
    results = [tcp_ping(host, port, timeout) for _ in range(max(1, attempts))]
    good = [r for r in results if r is not None]
    return min(good) if good else None


def test_nodes(
    specs: List[Dict[str, Any]],
    timeout: float = 2.5,
    workers: int = 32,
    on_result: Optional[Callable[[str, Optional[int]], None]] = None,
) -> Dict[str, Optional[int]]:
    """Probe every node in parallel; returns ``{node_id: ms|None}``."""
    results: Dict[str, Optional[int]] = {}
    if not specs:
        return results

    with ThreadPoolExecutor(max_workers=max(4, min(workers, len(specs) * 2))) as pool:
        futures = {
            pool.submit(tcp_ping_best, spec.get("server", ""), int(spec.get("port") or 0), timeout): spec
            for spec in specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            try:
                value = future.result()
            except Exception:
                value = None
            results[spec.get("id", "")] = value
            if on_result:
                try:
                    on_result(spec.get("id", ""), value)
                except Exception:
                    pass
    return results


def clash_delay(clash_port: int, tag: str, url: str = "http://cp.cloudflare.com/generate_204",
                timeout_ms: int = 5000, secret: str = "") -> Optional[int]:
    """Ask a running sing-box for the real delay of one outbound tag."""
    endpoint = f"http://127.0.0.1:{clash_port}/proxies/{urllib.parse.quote(tag, safe='')}/delay"
    query = f"?url={urllib.parse.quote(url, safe='')}&timeout={int(timeout_ms)}"
    request = urllib.request.Request(endpoint + query)
    if secret:
        request.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(request, timeout=(timeout_ms / 1000) + 2) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
        delay = payload.get("delay")
        return int(delay) if delay else None
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8", "ignore"))
            if body.get("message") == "An error occurred in the delay test":
                return None
        except Exception:
            pass
        return None
    except Exception:
        return None


def best_node(specs: List[Dict[str, Any]], latencies: Dict[str, Optional[int]]) -> Optional[Dict[str, Any]]:
    """Cheapest reachable node, falling back to the first entry."""
    reachable = [(latencies.get(s["id"]), s) for s in specs if latencies.get(s["id"]) is not None]
    if reachable:
        reachable.sort(key=lambda pair: pair[0])
        return reachable[0][1]
    return specs[0] if specs else None


def quality_of(ms: Optional[int]) -> str:
    if ms is None:
        return "offline"
    if ms < 120:
        return "excellent"
    if ms < 250:
        return "good"
    if ms < 500:
        return "fair"
    return "poor"
