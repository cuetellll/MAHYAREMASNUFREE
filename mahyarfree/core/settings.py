"""Persistent application settings (plain JSON, atomic writes)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

from . import paths

DEFAULTS: Dict[str, Any] = {
    "language": "fa",
    "theme": "neon",
    "animations": True,
    "sound": False,

    # subscription
    "subscriptions": [
        {
            "id": "default",
            "name": "MahyarVPN",
            "url": "https://raw.githubusercontent.com/cuetellll/mahyarvpn-sub/main/sub.txt",
            "enabled": True,
        }
    ],
    "auto_update_minutes": 60,
    "update_on_start": True,

    # connection
    "mode": "system-proxy",        # "system-proxy" | "tun"
    "routing": "rule",             # "global" | "rule" | "direct"
    "socks_port": 20808,
    "http_port": 20809,
    "clash_port": 20810,
    "dns_remote": "https://1.1.1.1/dns-query",
    "dns_direct": "https://223.5.5.5/dns-query",
    "bypass_lan": True,
    "block_ads": True,
    "dns_hijack": True,
    "udp_over_proxy": False,
    "fragment": False,
    "mux": False,
    "mux_concurrency": 8,

    # selection
    "selected_node_id": "",
    "auto_best_on_start": False,
    "latency_timeout_ms": 2500,
    "sort_by": "latency",           # "latency" | "name" | "group"

    # system integration
    "autostart": False,
    "start_minimized": False,
    "minimize_to_tray": True,
    "kill_switch": False,
    "preferred_core": "auto",       # "auto" | "sing-box" | "xray"

    # window
    "window_width": 1180,
    "window_height": 760,
}

_LOCK = threading.RLock()


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else paths.SETTINGS_FILE
        self._data: Dict[str, Any] = dict(DEFAULTS)
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> Dict[str, Any]:
        with _LOCK:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        merged = dict(DEFAULTS)
                        merged.update(raw)
                        self._data = merged
                except Exception:
                    # corrupt settings should never brick the app
                    self._data = dict(DEFAULTS)
            return self._data

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self._data, handle, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    # --------------------------------------------------------------- access
    def get(self, key: str, default: Any = None) -> Any:
        with _LOCK:
            return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with _LOCK:
            self._data[key] = value
        if save:
            self.save()

    def update(self, values: Dict[str, Any], save: bool = True) -> None:
        with _LOCK:
            self._data.update(values or {})
        if save:
            self.save()

    def all(self) -> Dict[str, Any]:
        with _LOCK:
            return dict(self._data)

    def reset(self) -> None:
        with _LOCK:
            self._data = dict(DEFAULTS)
        self.save()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        paths.ensure_dirs()
        _settings = Settings()
    return _settings
