"""End-to-end backend smoke test.

    MAHYARFREE_DATA_DIR=/tmp/mf-test python3 tools/smoke_test.py

Exercises subscription parsing, config generation, core validation, the live
engine, the system-proxy shim, latency probing and the traffic monitor.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [ok]   {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mf-smoke-"))
    os.environ["MAHYARFREE_DATA_DIR"] = str(tmp)

    from mahyarfree.core import configgen_singbox, configgen_xray, cores, latency, paths, sysproxy, uri_parser
    from mahyarfree.core import nodes_store, stats
    from mahyarfree.core.engine import Engine, EngineError
    from mahyarfree.core.settings import Settings

    paths.ensure_dirs()
    print(f"data dir: {paths.DATA_DIR}")

    # ── 1. parsing ─────────────────────────────────────────────────────────
    print("\n[1] subscription parsing")
    sample = ROOT / "tests" / "sample_sub.txt"
    if not sample.exists():
        sample = ROOT / "recon" / "sub.txt"
    text = sample.read_text(encoding="utf-8")
    specs = uri_parser.parse_subscription_text(text)
    check("plain-text subscription parses", len(specs) >= 3, f"got {len(specs)}")

    import base64

    b64 = base64.b64encode(text.encode()).decode()
    check("base64 subscription parses", len(uri_parser.parse_subscription_text(b64)) == len(specs))

    synthetic = "\n".join([
        "vmess://" + base64.b64encode(json.dumps({
            "v": "2", "ps": "Test VMess", "add": "example.com", "port": "443",
            "id": "b831381d-6324-4d53-ad4f-8cda48b30811", "aid": "0", "scy": "auto",
            "net": "ws", "type": "none", "host": "example.com", "path": "/ws", "tls": "tls",
        }).encode()).decode(),
        "trojan://pass@example.org:443?sni=example.org&type=grpc&serviceName=grpcsvc#Trojan%20Test",
        "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ@example.net:8388#SS%20Test",
        "hysteria2://pw@example.io:443?sni=example.io&insecure=1#Hy2%20Test",
        "tuic://uuid-1:pw@example.dev:443?congestion_control=bbr#Tuic%20Test",
    ])
    multi = uri_parser.parse_subscription_text(synthetic)
    protocols = {s["protocol"] for s in multi}
    check("vmess/vless/trojan/ss/hysteria2/tuic all parse",
          {"vmess", "trojan", "shadowsocks", "hysteria2", "tuic"} <= protocols, str(protocols))

    check("reality node detected", any(s["tls"]["reality"]["enabled"] for s in specs))
    check("xhttp routed to xray core", any(uri_parser.sniff_core(s) == "xray" for s in specs))
    check("country guessing works", uri_parser.guess_country("3xui-🇸🇱Arvin🇸🇱") == "🇸🇱")
    check("flag stripping works", "🇸🇱" not in uri_parser.strip_flags("3xui-🇸🇱Arvin🇸🇱"))

    # ── 2. config generation ───────────────────────────────────────────────
    print("\n[2] config generation")
    settings = {
        "mode": "system-proxy", "routing": "rule",
        "socks_port": 21808, "http_port": 21809, "clash_port": 21810,
        "dns_remote": "https://1.1.1.1/dns-query", "dns_direct": "https://223.5.5.5/dns-query",
        "block_ads": True, "dns_hijack": True, "fragment": False, "mux": False, "bypass_lan": True,
    }
    sb_specs = [s for s in specs if uri_parser.sniff_core(s) == "sing-box"]
    xr_specs = [s for s in specs if uri_parser.sniff_core(s) == "xray"]

    sb_config = configgen_singbox.build_config(sb_specs, sb_specs[0]["id"], settings,
                                               log_path=str(paths.CORE_LOG),
                                               cache_path=str(paths.CACHE_DIR / "sb.db"))
    check("sing-box config has mixed inbound", any(i["type"] == "mixed" for i in sb_config["inbounds"]))
    check("sing-box config has selector", any(o["type"] == "selector" for o in sb_config["outbounds"]))
    check("sing-box config has urltest", any(o["type"] == "urltest" for o in sb_config["outbounds"]))

    tun_settings = dict(settings, mode="tun")
    tun_config = configgen_singbox.build_config(sb_specs, sb_specs[0]["id"], tun_settings)
    check("TUN inbound generated", any(i["type"] == "tun" for i in tun_config["inbounds"]))

    if xr_specs:
        xr_config = configgen_xray.build_config(xr_specs, xr_specs[0]["id"], settings)
        check("xray config has xhttp transport",
              xr_config["outbounds"][0]["streamSettings"].get("network") == "xhttp")
        check("xray config has reality",
              xr_config["outbounds"][0]["streamSettings"].get("security") == "reality")

    # ── 3. real core validation ────────────────────────────────────────────
    print("\n[3] core binaries")
    local_sb = ROOT / "recon" / "sing-box-1.14.2-linux-amd64" / "sing-box"
    if local_sb.exists():
        shutil.copy2(local_sb, paths.CORE_DIR / "sing-box")
        (paths.CORE_DIR / "sing-box").chmod(0o755)
    local_xr = ROOT / "recon" / "xray" / "xray"
    if local_xr.exists():
        shutil.copy2(local_xr, paths.CORE_DIR / "xray")
        (paths.CORE_DIR / "xray").chmod(0o755)

    # no local copy? exercise the real downloader instead
    if not cores.core_path("sing-box"):
        print("  downloading sing-box via the built-in downloader ...")
        cores.ensure_core("sing-box")
    if not cores.core_path("xray"):
        print("  downloading xray via the built-in downloader ...")
        cores.ensure_core("xray")

    info = cores.core_status()
    check("sing-box binary available", info["sing-box"]["available"])
    check("sing-box version readable", "sing-box" in str(info["sing-box"]["version"]))
    check("xray binary available", info["xray"]["available"])

    if info["sing-box"]["available"]:
        config_file = tmp / "check.json"
        config_file.write_text(json.dumps(sb_config), encoding="utf-8")
        result = subprocess.run([str(cores.core_path("sing-box")), "check", "-c", str(config_file)],
                                capture_output=True, text=True)
        check("sing-box accepts generated config", result.returncode == 0,
              (result.stderr or "")[:160])

    # ── 4. node store ──────────────────────────────────────────────────────
    print("\n[4] node store")
    store = nodes_store.NodeStore()
    (tmp / "local.txt").write_text(text, encoding="utf-8")
    result = store.refresh([{"id": "t", "name": "Local", "url": f"file://{tmp / 'local.txt'}", "enabled": True}])
    check("node store refresh reports count", result["count"] >= 3, str(result))
    check("node view is UI shaped", all("latency" in n and "core" in n for n in store.view()))

    # ── 5. latency ─────────────────────────────────────────────────────────
    print("\n[5] latency probing")
    lat = latency.test_nodes(store.all(), timeout=2.0, workers=8)
    check("latency probe returns an entry per node", len(lat) == len(store.all()))
    check("quality buckets work", latency.quality_of(80) == "excellent" and latency.quality_of(None) == "offline")

    # ── 6. system proxy shim ───────────────────────────────────────────────
    print("\n[6] system proxy shim")
    previous = sysproxy.enable(21808, 21809)
    check("enable() returns a snapshot", isinstance(previous, dict))
    sysproxy.restore(previous)
    check("non-windows platform is a safe no-op", sysproxy.is_enabled() is False)

    # ── 7. live engine ─────────────────────────────────────────────────────
    print("\n[7] live engine")
    settings_obj = Settings(tmp / "settings.json")
    settings_obj.update(settings)
    engine = Engine()
    if info["sing-box"]["available"]:
        try:
            status = engine.start(store.all(), sb_specs[0]["id"], settings_obj.all())
            check("engine reports running", status["running"])
            check("engine picked sing-box", status["core"] == "sing-box")

            monitor = stats.get_monitor()
            samples: list[dict] = []
            monitor.start("sing-box", 21810, lambda s: samples.append(s))
            time.sleep(3.5)
            monitor.stop()
            check("traffic monitor streams samples", len(samples) > 0, f"{len(samples)} samples")

            delay = None
            for _ in range(3):
                delay = latency.clash_delay(21810, "proxy", timeout_ms=8000)
                if delay is not None:
                    break
                time.sleep(0.7)
            check("clash api delay query works", delay is not None, f"delay={delay}")

            egress = None
            for attempt in range(3):
                try:
                    proxy = urllib.request.ProxyHandler({"http": "http://127.0.0.1:21809",
                                                         "https": "http://127.0.0.1:21809"})
                    opener = urllib.request.build_opener(proxy)
                    with opener.open("https://api.ipify.org", timeout=20) as response:
                        egress = response.read().decode().strip()
                    break
                except Exception as error:
                    egress = f"error: {error}"
                    time.sleep(2)
            check("traffic really flows through the tunnel", bool(egress) and "error" not in str(egress),
                  str(egress))
            print(f"         egress ip = {egress}")

            engine.stop()
            time.sleep(0.6)
            check("engine stops cleanly", not engine.running)
        except EngineError as error:
            check("engine start", False, str(error))
    else:
        print("  [skip] sing-box binary unavailable")

    # ── summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print(f"passed: {len(PASSED)}   failed: {len(FAILED)}")
    for item in FAILED:
        print("  FAILED:", item)
    print("=" * 62)
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
