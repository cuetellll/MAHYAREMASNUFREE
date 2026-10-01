"""Real per-node connectivity and response-time checks.

A TCP handshake to a server endpoint only proves that *some* service is
listening. It does not prove that the V2Ray credentials, TLS, transport,
routing, or remote internet access work. This probe starts an isolated local
core for one node, sends a real HTTP(S) request through its local HTTP proxy,
and reports that end-to-end response time. It never changes the Windows system
proxy and never interrupts the user's active connection.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import configgen_singbox, configgen_xray, cores, paths
from .uri_parser import sniff_core

PROBE_URLS = (
    "https://cp.cloudflare.com/generate_204",
    "https://www.gstatic.com/generate_204",
)


def reserve_port() -> int:
    """Ask the OS for an unused loopback port (released before core startup)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_proxy_probe(port: int, timeout: float = 8.0) -> Optional[int]:
    """Measure a real HTTP(S) response through a local HTTP proxy.

    A successful status is required; a proxy socket opening alone is not
    considered connectivity. Tries two independent 204 endpoints so a single
    blocked probe host cannot incorrectly mark an otherwise-good node offline.
    """
    proxy_url = f"http://127.0.0.1:{int(port)}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    for url in PROBE_URLS:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 MahyarFree connectivity-check",
                "Cache-Control": "no-cache",
            },
        )
        started = time.perf_counter()
        try:
            with opener.open(request, timeout=max(0.5, timeout)) as response:
                status = int(getattr(response, "status", 200))
                response.read(128)
            if 200 <= status < 400:
                return max(1, int(round((time.perf_counter() - started) * 1000)))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
        except Exception:
            continue
    return None


def _validate(core_name: str, exe: Path, config_file: Path, timeout: float = 15.0) -> Tuple[bool, str]:
    if core_name == "xray":
        command = [str(exe), "run", "-test", "-c", str(config_file)]
    else:
        command = [str(exe), "check", "-c", str(config_file)]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            **cores.no_window_kwargs(),
        )
    except Exception as error:
        return False, str(error)
    if result.returncode == 0:
        return True, ""
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    return False, lines[-1] if lines else "core rejected the generated config"


def probe_node(
    spec: Dict[str, Any],
    settings: Dict[str, Any],
    timeout: float = 8.0,
    startup_timeout: float = 8.0,
) -> Optional[int]:
    """Return measured end-to-end response time, or ``None`` if unusable."""
    core_name = sniff_core(spec)
    preferred = (settings or {}).get("preferred_core", "auto")
    xray_protocols = {"vless", "vmess", "trojan", "shadowsocks", "shadowsocksr", "socks", "http"}
    if preferred == "xray" and spec.get("protocol") in xray_protocols and cores.core_path("xray"):
        core_name = "xray"
    exe = cores.core_path(core_name)
    if exe is None:
        exe = cores.ensure_core(core_name)
    if exe is None:
        return None

    socks_port, http_port, clash_port = reserve_port(), reserve_port(), reserve_port()
    while len({socks_port, http_port, clash_port}) != 3:
        socks_port, http_port, clash_port = reserve_port(), reserve_port(), reserve_port()

    test_settings = dict(settings or {})
    test_settings.update({
        "mode": "system-proxy",  # generator creates loopback inbounds only
        "routing": "global",     # force the connectivity-check request through this node
        "socks_port": socks_port,
        "http_port": http_port,
        "clash_port": clash_port,
        "block_ads": False,
        "bypass_lan": False,
        "fragment": False,
        "mux": False,
        "dns_hijack": False,
    })
    test_settings.setdefault("dns_remote", "https://1.1.1.1/dns-query")
    test_settings.setdefault("dns_direct", "https://223.5.5.5/dns-query")

    paths.ensure_dirs()
    with tempfile.TemporaryDirectory(prefix="mahyarfree-probe-") as temp_name:
        temp_dir = Path(temp_name)
        config_file = temp_dir / "probe.json"
        try:
            if core_name == "xray":
                config = configgen_xray.build_config([spec], spec["id"], test_settings)
            else:
                config = configgen_singbox.build_config(
                    [spec], spec["id"], test_settings,
                    cache_path=str(temp_dir / "cache.db"),
                )
            config_file.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return None

        valid, _reason = _validate(core_name, exe, config_file)
        if not valid:
            return None

        command = [str(exe), "run", "-c", str(config_file)]
        process: Optional[subprocess.Popen] = None
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                cwd=str(paths.DATA_DIR),
                **cores.no_window_kwargs(),
            )
            ready_until = time.monotonic() + max(1.0, startup_timeout)
            ready = False
            while time.monotonic() < ready_until:
                if process.poll() is not None:
                    break
                try:
                    with socket.create_connection(("127.0.0.1", http_port), timeout=0.15):
                        ready = True
                        break
                except OSError:
                    time.sleep(0.12)
            if not ready:
                return None
            return http_proxy_probe(http_port, timeout=timeout)
        except Exception:
            return None
        finally:
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2.5)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=1.0)
                    except Exception:
                        pass


def test_nodes(
    specs: List[Dict[str, Any]],
    settings: Dict[str, Any],
    timeout: float = 8.0,
    workers: int = 3,
    on_result: Optional[Callable[[str, Optional[int]], None]] = None,
) -> Dict[str, Optional[int]]:
    """Probe nodes independently; capped workers avoid launching too many cores."""
    if not specs:
        return {}
    results: Dict[str, Optional[int]] = {}
    max_workers = max(1, min(int(workers), len(specs), 4))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mf-real-ping") as pool:
        futures = {pool.submit(probe_node, spec, settings, timeout): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            node_id = str(spec.get("id", ""))
            try:
                value = future.result()
            except Exception:
                value = None
            results[node_id] = value
            if on_result:
                try:
                    on_result(node_id, value)
                except Exception:
                    pass
    return results
