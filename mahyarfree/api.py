"""The bridge between the web UI and the Python engine.

Every public method here is callable from JavaScript as
``window.pywebview.api.<name>(...)`` and must return JSON-serialisable data.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .core import cores, engine, latency, nodes_store, paths, stats, sysproxy
from .core.settings import get_settings
from .version import __version__

IS_WINDOWS = os.name == "nt"


class Api:
    def __init__(self, window=None) -> None:
        self.window = window
        # when running through webbridge.py this is replaced by the SSE hub
        self.emitter: Optional[Callable[[str, Any], None]] = None
        self.settings = get_settings()
        self.store = nodes_store.get_store()
        self.engine = engine.get_engine()
        self.monitor = stats.get_monitor()
        self._busy = threading.Lock()
        self._last_traffic: Dict[str, Any] = {"up": 0, "down": 0, "total_up": 0, "total_down": 0}

        self.engine.add_listener(self._on_engine_event)

    # ------------------------------------------------------------- plumbing
    def _emit(self, name: str, payload: Any) -> None:
        if self.emitter is not None:
            try:
                self.emitter(name, payload)
            except Exception:
                pass
            return
        if not self.window:
            return
        try:
            data = json.dumps(payload, ensure_ascii=False)
            self.window.evaluate_js(f"window.MF && window.MF.emit({json.dumps(name)}, {data})")
        except Exception:
            pass

    def _on_engine_event(self, event: Dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "log":
            self._emit("core-log", {"line": event.get("line", "")})
            return
        if kind == "started":
            self.monitor.start(
                self.engine.status().get("core", "sing-box"),
                int(self.settings.get("clash_port", 20810)),
                self._on_traffic,
                cores.core_path("xray") and str(cores.core_path("xray")),
            )
        elif kind in ("stopped", "crashed"):
            self.monitor.stop()
            self._emit("traffic", {"up": 0, "down": 0, "total_up": 0, "total_down": 0})
        self._emit("status", self.status())

    def _on_traffic(self, sample: Dict[str, Any]) -> None:
        self._last_traffic = sample
        self._emit("traffic", sample)

    # ------------------------------------------------------------ bootstrap
    def bootstrap(self) -> Dict[str, Any]:
        return {
            "version": __version__,
            "platform": sys.platform,
            "is_windows": IS_WINDOWS,
            "elevated": sysproxy.is_elevated(),
            "settings": self.settings.all(),
            "cores": cores.core_status(),
            "status": self.engine.status(),
            "nodes": self.store.view(),
            "last_update": self.store.last_update,
            "errors": self.store.errors,
            "data_dir": str(paths.DATA_DIR),
        }

    def status(self) -> Dict[str, Any]:
        state = self.engine.status()
        state["system_proxy"] = sysproxy.is_enabled()
        return state

    def get_nodes(self) -> List[Dict[str, Any]]:
        return self.store.view()

    def get_settings(self) -> Dict[str, Any]:
        return self.settings.all()

    # ------------------------------------------------------------ connecting
    def connect(self, node_id: str = "") -> Dict[str, Any]:
        with self._busy:
            specs = self.store.all()
            if not specs:
                self._emit("error", {"message": "هیچ سروری موجود نیست. ابتدا سابسکریپشن را به‌روزرسانی کنید."})
                return {"ok": False, "error": "no-nodes"}

            target = node_id or self.settings.get("selected_node_id") or ""
            if not target:
                best = latency.best_node(specs, self.store.latency)
                target = best["id"] if best else specs[0]["id"]

            node = self.store.by_id(target)
            if node is None:
                node = specs[0]
                target = node["id"]

            try:
                self._emit("connecting", {"node_id": target, "node_name": node.get("name", "")})
                state = self.engine.start(specs, target, self.settings.all())
                self.settings.set("selected_node_id", target, save=False)
                self.settings.save()
                return {"ok": True, **state}
            except engine.EngineError as error:
                message = str(error)
                self._emit("error", {"message": message})
                return {"ok": False, "error": message}
            except Exception as error:  # pragma: no cover
                self._emit("error", {"message": str(error)})
                return {"ok": False, "error": str(error)}

    def connect_best(self) -> Dict[str, Any]:
        specs = self.store.all()
        if not specs:
            return {"ok": False, "error": "no-nodes"}
        self.ping_all(wait=True)

        # cheapest first, unreachable nodes last
        ordered = sorted(
            specs,
            key=lambda s: (self.store.latency.get(s["id"]) is None,
                           self.store.latency.get(s["id"]) or 99999),
        )

        last: Dict[str, Any] = {"ok": False, "error": "no-reachable"}
        fallback: Optional[Dict[str, Any]] = None
        candidates = ordered[:4]

        for index, node in enumerate(candidates):
            self._emit("best-progress", {
                "attempt": index + 1,
                "name": node.get("name", ""),
                "count": len(candidates),
            })
            result = self.connect(node["id"])
            if not result.get("ok"):
                last = result
                continue

            # a low TCP handshake means nothing if the node cannot carry data
            probe = self._verify_node(node["id"])
            if probe is not None:
                return {**result, "verified": True, "latency": probe}

            fallback = node
            self.engine.stop()
            time.sleep(0.3)

        # nothing answered the probe: stay on the fastest node we did reach
        if fallback is not None:
            result = self.connect(fallback["id"])
            if result.get("ok"):
                return {**result, "verified": False}
        return last

    def _verify_node(self, node_id: str, attempts: int = 2, timeout_ms: int = 6000) -> Optional[int]:
        """Probe a freshly started node until it proves it can carry traffic."""
        port = int(self.settings.get("clash_port", 20810))
        for attempt in range(attempts):
            time.sleep(1.8 if attempt == 0 else 0.8)
            value = latency.clash_delay(port, "proxy", timeout_ms=timeout_ms)
            if value is not None:
                return value
        return None

    def disconnect(self) -> Dict[str, Any]:
        with self._busy:
            state = self.engine.stop()
            return {"ok": True, **state}

    def switch_node(self, node_id: str) -> Dict[str, Any]:
        return self.connect(node_id)

    # -------------------------------------------------------------- latency
    def ping_all(self, wait: bool = True) -> Dict[str, Any]:
        specs = self.store.all()
        timeout = float(self.settings.get("latency_timeout_ms", 2500)) / 1000.0

        def run() -> None:
            self._emit("ping-start", {"count": len(specs)})

            def on_result(node_id: str, value: Optional[int]) -> None:
                self.store.set_latency(node_id, value)
                self._emit("ping-result", {"id": node_id, "latency": value,
                                           "quality": latency.quality_of(value)})

            latency.test_nodes(specs, timeout=timeout, on_result=on_result)
            self.store.save_cache()
            self._emit("ping-done", {"latencies": self.store.latency})

        if wait:
            run()
            return {"ok": True, "latencies": self.store.latency}
        threading.Thread(target=run, daemon=True, name="mahyarfree-ping").start()
        return {"ok": True, "started": True}

    def ping_node(self, node_id: str) -> Dict[str, Any]:
        node = self.store.by_id(node_id)
        if node is None:
            return {"ok": False}
        timeout = float(self.settings.get("latency_timeout_ms", 2500)) / 1000.0
        value = latency.tcp_ping_best(node["server"], int(node["port"]), timeout)
        self.store.set_latency(node_id, value)
        self._emit("ping-result", {"id": node_id, "latency": value, "quality": latency.quality_of(value)})
        return {"ok": True, "latency": value}

    def real_delay(self, node_id: str = "") -> Dict[str, Any]:
        """Round-trip delay measured through the running core."""
        if not self.engine.running:
            return {"ok": False, "error": "not-running"}
        node = self.store.by_id(node_id or self.settings.get("selected_node_id", ""))
        tag = "proxy" if not node_id or node_id == self.settings.get("selected_node_id") else f"node::{node_id}"
        value = latency.clash_delay(int(self.settings.get("clash_port", 20810)), tag,
                                    timeout_ms=int(self.settings.get("latency_timeout_ms", 2500)))
        return {"ok": value is not None, "latency": value}

    # --------------------------------------------------------- subscriptions
    def refresh(self, wait: bool = True) -> Dict[str, Any]:
        def run() -> Dict[str, Any]:
            self._emit("refresh-start", {})
            result = self.store.refresh(self.settings.get("subscriptions", []),
                                        progress=lambda m, p: self._emit("refresh-progress", {"message": m, "value": p}))
            self._emit("nodes", self.store.view())
            self._emit("refresh-done", result)
            return result

        if wait:
            result = run()
            return {"ok": True, **result}
        threading.Thread(target=run, daemon=True, name="mahyarfree-refresh").start()
        return {"ok": True, "started": True}

    def add_subscription(self, name: str, url: str) -> Dict[str, Any]:
        subs = list(self.settings.get("subscriptions", []))
        subs.append({"id": f"sub{int(time.time())}", "name": name or "اشتراک جدید",
                     "url": url.strip(), "enabled": True})
        self.settings.set("subscriptions", subs)
        self.refresh(wait=False)
        return {"ok": True, "subscriptions": subs}

    def remove_subscription(self, sub_id: str) -> Dict[str, Any]:
        subs = [s for s in self.settings.get("subscriptions", []) if s.get("id") != sub_id]
        self.settings.set("subscriptions", subs)
        self.refresh(wait=False)
        return {"ok": True, "subscriptions": subs}

    def toggle_subscription(self, sub_id: str) -> Dict[str, Any]:
        subs = []
        for sub in self.settings.get("subscriptions", []):
            item = dict(sub)
            if item.get("id") == sub_id:
                item["enabled"] = not item.get("enabled", True)
            subs.append(item)
        self.settings.set("subscriptions", subs)
        self.refresh(wait=False)
        return {"ok": True, "subscriptions": subs}

    # -------------------------------------------------------------- settings
    def save_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(values, dict):
            return {"ok": False}
        allowed = set(self.settings.all().keys())
        patch = {k: v for k, v in values.items() if k in allowed}
        previous_mode = self.settings.get("mode")
        self.settings.update(patch)

        if "autostart" in patch:
            try:
                autostart_module.apply(bool(self.settings.get("autostart")))
            except Exception:
                pass

        if previous_mode != self.settings.get("mode") and self.engine.running:
            self.connect(self.settings.get("selected_node_id", ""))
        elif self.engine.running and any(
            key in patch for key in ("routing", "block_ads", "bypass_lan", "dns_remote", "dns_direct",
                                     "fragment", "mux", "udp_over_proxy")
        ):
            self.connect(self.settings.get("selected_node_id", ""))
        return {"ok": True, "settings": self.settings.all()}

    def toggle_favourite(self, node_id: str) -> Dict[str, Any]:
        state = self.store.toggle_favourite(node_id)
        return {"ok": True, "favourite": state, "nodes": self.store.view()}

    def select_node(self, node_id: str) -> Dict[str, Any]:
        self.settings.set("selected_node_id", node_id)
        if self.engine.running:
            return self.connect(node_id)
        return {"ok": True}

    # ----------------------------------------------------------------- cores
    def download_core(self, name: str) -> Dict[str, Any]:
        def run() -> None:
            self._emit("core-download-start", {"core": name})
            result = cores.ensure_core(name, progress=lambda m, p: self._emit(
                "core-download-progress", {"core": name, "message": m, "value": p}))
            self._emit("core-download-done", {"core": name, "ok": bool(result),
                                              "cores": cores.core_status()})

        threading.Thread(target=run, daemon=True, name="mahyarfree-core-dl").start()
        return {"ok": True, "started": True}

    def core_info(self) -> Dict[str, Any]:
        return cores.core_status()

    # ---------------------------------------------------------------- system
    def open_data_dir(self) -> Dict[str, Any]:
        try:
            if IS_WINDOWS:
                os.startfile(str(paths.DATA_DIR))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(paths.DATA_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(paths.DATA_DIR)])
            return {"ok": True}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def open_url(self, url: str) -> Dict[str, Any]:
        try:
            if IS_WINDOWS:
                os.startfile(url)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
            return {"ok": True}
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def copy_to_clipboard(self, text: str) -> Dict[str, Any]:
        try:
            if IS_WINDOWS:
                subprocess.run("clip", input=text.encode("utf-16le"), check=False, shell=True,
                               **cores.no_window_kwargs())
            return {"ok": True}
        except Exception:
            return {"ok": False}

    def request_elevation(self) -> Dict[str, Any]:
        if sysproxy.is_elevated():
            return {"ok": True, "already": True}
        started = sysproxy.elevate()
        return {"ok": started}

    def quit(self) -> Dict[str, Any]:
        try:
            self.engine.stop()
            self.monitor.stop()
            if self.window:
                self.window.destroy()
        except Exception:
            pass
        os._exit(0)
        return {"ok": True}

    def minimize(self) -> Dict[str, Any]:
        try:
            if self.window:
                self.window.minimize()
        except Exception:
            pass
        return {"ok": True}

    def toggle_maximize(self) -> Dict[str, Any]:
        try:
            if self.window:
                self.window.toggle_fullscreen()
        except Exception:
            pass
        return {"ok": True}

    def set_always_on_top(self, state: bool) -> Dict[str, Any]:
        try:
            if self.window:
                self.window.on_top = bool(state)
        except Exception:
            pass
        return {"ok": True}
from .core import autostart as autostart_module
