"""Serve the UI over plain HTTP so the design can be reviewed in a browser.

The page loads ``mock_api.js`` instead of the real pywebview bridge, giving the
same look and feel with fake data.  Used by ``python app.py --serve``.
"""

from __future__ import annotations

import json
import os
import random
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = ROOT / "mahyarfree" / "ui"

MOCK_STATE = {
    "version": "1.0.0",
    "platform": "win32",
    "is_windows": True,
    "elevated": True,
    "settings": {
        "mode": "system-proxy",
        "routing": "rule",
        "animations": True,
        "sound": False,
        "auto_best_on_start": False,
        "block_ads": True,
        "bypass_lan": True,
        "minimize_to_tray": True,
        "autostart": False,
        "subscriptions": [
            {"id": "default", "name": "MahyarVPN", "url": "https://github.com/cuetellll/mahyarvpn-sub",
             "enabled": True},
        ],
    },
    "cores": {
        "sing-box": {"available": True, "version": "sing-box version 1.14.2", "path": "..."},
        "xray": {"available": True, "version": "Xray 25.9.11", "path": "..."},
    },
    "status": {"running": False, "core": "", "node_id": "", "node_name": "", "uptime": 0, "error": ""},
    "nodes": [],
    "last_update": time.time(),
    "errors": {},
    "data_dir": str(ROOT),
}

PROTOCOLS = ["vless", "vmess", "trojan", "hysteria2", "shadowsocks"]
COUNTRIES = ["🇩🇪", "🇳🇱", "🇫🇮", "🇫🇷", "🇬🇧", "🇺🇸", "🇹🇷", "🇦🇪", "🇸🇪", "🇵🇱", "🇦🇹", "🇯🇵"]
NAMES = ["Falcon", "Phantom", "Arvin", "Mahyar", "Storm", "Nova", "Vortex", "Blaze", "Onyx", "Titan",
         "Cipher", "Nebula", "Raptor", "Zenith", "Echo", "Pulse"]


def build_mock_nodes() -> list:
    nodes = []
    for index in range(24):
        country = COUNTRIES[index % len(COUNTRIES)]
        name = f"{NAMES[index % len(NAMES)]} {country}"
        nodes.append({
            "id": f"mock{index:03d}",
            "name": name,
            "server": f"node{index}.mahyarfree.net",
            "port": 443 + index,
            "protocol": PROTOCOLS[index % len(PROTOCOLS)],
            "group": "MahyarVPN" if index % 3 else "Sub Backup",
            "country": country,
            "core": "xray" if index % 7 == 3 else "sing-box",
            "latency": None if index % 9 == 4 else random.choice([48, 62, 87, 110, 138, 175, 220, 310, 480]),
            "favourite": index in (2, 5),
            "transport": ["ws", "tcp", "grpc", "xhttp"][index % 4],
            "tls": index % 3 != 1,
        })
    return nodes


MOCK_STATE["nodes"] = build_mock_nodes()


class PreviewHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence the console
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/mock/state"):
            self._json(MOCK_STATE)
            return
        if self.path.startswith("/mock/ping"):
            nodes = MOCK_STATE["nodes"]
            for node in nodes:
                node["latency"] = random.choice([45, 60, 78, 95, 120, 160, 210, 280, 420, None])
            self._json({"ok": True, "nodes": nodes})
            return
        super().do_GET()

    def _json(self, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 8777, host: str = "0.0.0.0") -> None:
    os.chdir(UI_DIR)
    handler = partial(PreviewHandler, directory=str(UI_DIR))
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"MahyarFree UI preview -> http://127.0.0.1:{port}/index.html")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    serve()
