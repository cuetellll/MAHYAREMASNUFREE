"""Live upload / download counters.

sing-box exposes a Clash-compatible API which streams ``/traffic`` samples.
Xray-core has no such API, so its counters are read with ``xray api statsquery``
and differentiated between polls.  Both paths feed the same callback.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from typing import Any, Callable, Dict, Optional

from . import cores


class TrafficMonitor:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.download = 0
        self.upload = 0
        self.total_download = 0
        self.total_upload = 0

    # ---------------------------------------------------------------- start
    def start(self, core: str, clash_port: int, callback: Callable[[Dict[str, Any]], None],
              xray_exe: Optional[str] = None) -> None:
        self.stop()
        self._stop.clear()
        self._callback = callback
        self.download = self.upload = 0
        self.total_download = self.total_upload = 0
        if core == "xray":
            target = self._xray_loop
            args = (xray_exe or "", clash_port)
        else:
            target = self._clash_loop
            args = (clash_port,)
        self._thread = threading.Thread(target=target, args=args, daemon=True, name="mahyarfree-traffic")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    # -------------------------------------------------------------- sing-box
    def _clash_loop(self, clash_port: int) -> None:
        url = f"http://127.0.0.1:{clash_port}/traffic"
        while not self._stop.is_set():
            try:
                with urllib.request.urlopen(url, timeout=4) as response:
                    for raw in response:
                        if self._stop.is_set():
                            return
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            sample = json.loads(raw)
                        except Exception:
                            continue
                        self._publish(int(sample.get("up") or 0), int(sample.get("down") or 0))
            except Exception:
                time.sleep(1.0)

    # ------------------------------------------------------------------ xray
    def _xray_loop(self, exe: str, api_port: int) -> None:
        previous: Dict[str, int] = {}
        last_time = time.time()
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    [exe, "api", "statsquery", f"--server=127.0.0.1:{api_port}", "-pattern", ""],
                    capture_output=True, text=True, timeout=4, **cores.no_window_kwargs(),
                )
                payload = json.loads(result.stdout or "{}")
                counters = self._flatten(payload)
                now = time.time()
                elapsed = max(0.2, now - last_time)
                last_time = now
                up = self._rate(counters, previous, "uplink", elapsed)
                down = self._rate(counters, previous, "downlink", elapsed)
                previous = counters
                self._publish(up, down)
            except Exception:
                pass
            self._stop.wait(1.0)

    @staticmethod
    def _flatten(payload: Dict[str, Any]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for stat in (payload.get("stat") or []):
            name = stat.get("name") or ""
            value = stat.get("value")
            if isinstance(value, str) and value.isdigit():
                out[name] = int(value)
            elif isinstance(value, (int, float)):
                out[name] = int(value)
        return out

    @staticmethod
    def _rate(current: Dict[str, int], previous: Dict[str, int], direction: str, elapsed: float) -> int:
        total = sum(v for k, v in current.items() if k.endswith(direction) and k.startswith("outbound"))
        before = sum(v for k, v in previous.items() if k.endswith(direction) and k.startswith("outbound"))
        if not current:
            return 0
        delta = max(0, total - before)
        return int(delta / elapsed)

    # -------------------------------------------------------------- publish
    def _publish(self, up: int, down: int) -> None:
        self.upload = max(0, up)
        self.download = max(0, down)
        self.total_upload += self.upload
        self.total_download += self.download
        if self._callback:
            try:
                self._callback({
                    "up": self.upload,
                    "down": self.download,
                    "total_up": self.total_upload,
                    "total_down": self.total_download,
                })
            except Exception:
                pass


_monitor: Optional[TrafficMonitor] = None


def get_monitor() -> TrafficMonitor:
    global _monitor
    if _monitor is None:
        _monitor = TrafficMonitor()
    return _monitor
