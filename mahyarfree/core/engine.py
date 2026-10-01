"""Core process lifecycle: build a config, launch it, watch it, stop it."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import configgen_singbox, configgen_xray, cores, paths, sysproxy
from .uri_parser import sniff_core


class EngineError(RuntimeError):
    pass


class Engine:
    """Owns at most one running core process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen] = None
        self._core = ""             # "sing-box" | "xray"
        self._active_id = ""
        self._active_name = ""
        self._started_at = 0.0
        self._config_path: Optional[Path] = None
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._watcher: Optional[threading.Thread] = None
        self._stderr_tail: List[str] = []
        self._proxy_backup: Optional[Dict[str, Any]] = None
        self.last_error = ""

    # ------------------------------------------------------------ listeners
    def add_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._listeners.append(callback)

    def _emit(self, event: Dict[str, Any]) -> None:
        for callback in list(self._listeners):
            try:
                callback(event)
            except Exception:
                pass

    # ---------------------------------------------------------------- state
    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "core": self._core,
                "node_id": self._active_id,
                "node_name": self._active_name,
                "uptime": int(time.time() - self._started_at) if self.running else 0,
                "error": self.last_error,
            }

    def tail_log(self, lines: int = 60) -> List[str]:
        with self._lock:
            return self._stderr_tail[-lines:]

    # ------------------------------------------------------------- commands
    def _choose_core(self, spec: Dict[str, Any], preferred: str = "auto") -> str:
        if preferred == "xray" and cores.core_path("xray"):
            xray_protocols = {"vless", "vmess", "trojan", "shadowsocks", "shadowsocksr", "socks", "http"}
            if spec.get("protocol") in xray_protocols:
                return "xray"
        if preferred == "sing-box" and cores.core_path("sing-box") and sniff_core(spec) == "sing-box":
            return "sing-box"
        return sniff_core(spec)

    def start(self, specs: List[Dict[str, Any]], active_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            if self.running:
                self.stop()

            active = next((s for s in specs if s.get("id") == active_id), None)
            if active is None:
                active = specs[0] if specs else None
            if active is None:
                raise EngineError("هیچ سروری برای اتصال وجود ندارد")

            core_name = self._choose_core(active, settings.get("preferred_core", "auto"))
            exe = cores.core_path(core_name)
            if exe is None:
                raise EngineError(f"هستهٔ {core_name} پیدا نشد")

            paths.ensure_dirs()
            self._config_path = paths.RUNTIME_CONFIG

            # only the nodes this core can actually run
            usable = [s for s in specs if sniff_core(s) == core_name]
            if active not in usable:
                usable.insert(0, active)

            if core_name == "sing-box":
                config = configgen_singbox.build_config(
                    usable, active["id"], settings,
                    log_path=str(paths.CORE_LOG),
                    cache_path=str(paths.CACHE_DIR / "sing-box.db"),
                )
            else:
                config = configgen_xray.build_config(
                    usable, active["id"], settings, log_path=str(paths.CORE_LOG)
                )

            self._config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # validate before launching so we can show a friendly message
            check_command = (
                [str(exe), "run", "-test", "-c", str(self._config_path)]
                if core_name == "xray"
                else [str(exe), "check", "-c", str(self._config_path)]
            )
            try:
                check = subprocess.run(
                    check_command, capture_output=True, text=True, timeout=20,
                    **cores.no_window_kwargs(),
                )
            except subprocess.TimeoutExpired:
                check = None
            if check is None:
                self.last_error = "config check timed out"
                raise EngineError(f"بررسی کانفیگ {core_name} زمان‌بر شد")
            if check.returncode != 0:
                message = (check.stderr or check.stdout or "").strip().splitlines()
                self.last_error = message[-1] if message else "config check failed"
                raise EngineError(f"خطای کانفیگ: {self.last_error}")

            command = [str(exe), "run", "-c", str(self._config_path)]
            self._stderr_tail = []
            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    cwd=str(paths.DATA_DIR),
                    **cores.no_window_kwargs(),
                )
            except Exception as error:  # pragma: no cover - OS level failure
                self.last_error = str(error)
                raise EngineError(f"اجرای هسته ناموفق بود: {error}")

            self._core = core_name
            self._active_id = active["id"]
            self._active_name = active.get("name", "")
            self._started_at = time.time()
            self.last_error = ""

            # give the core a moment; a port clash or bad node kills it instantly
            time.sleep(0.7)
            if self._process.poll() is not None:
                detail = "\n".join(self._stderr_tail[-6:])
                self.last_error = detail or "core exited immediately"
                self._process = None
                raise EngineError(f"هسته بلافاصله بسته شد: {self.last_error}")

            self._start_reader()
            self._start_watcher()

            if settings.get("mode") == "system-proxy":
                self._proxy_backup = sysproxy.enable(
                    int(settings.get("socks_port", 20808)),
                    int(settings.get("http_port", 20809)),
                    bypass_lan=bool(settings.get("bypass_lan", True)),
                )

            self._emit({"type": "started", **self.status()})
            return self.status()

    def switch_node(self, specs: List[Dict[str, Any]], active_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Hot-swap the exit node by restarting the core with a new config."""
        return self.start(specs, active_id, settings)

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            process = self._process
            self._process = None
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=4)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
            if self._proxy_backup is not None:
                try:
                    sysproxy.restore(self._proxy_backup)
                except Exception:
                    pass
                self._proxy_backup = None
            self._core = ""
            self._active_id = ""
            self._active_name = ""
            self._emit({"type": "stopped"})
            return self.status()

    # -------------------------------------------------------------- helpers
    def _start_reader(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        def pump() -> None:
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    with self._lock:
                        self._stderr_tail.append(line)
                        if len(self._stderr_tail) > 400:
                            del self._stderr_tail[:200]
                    self._emit({"type": "log", "line": line})
            except Exception:
                pass

        threading.Thread(target=pump, name="mahyarfree-core-log", daemon=True).start()

    def _start_watcher(self) -> None:
        process = self._process

        def watch() -> None:
            if process is None:
                return
            code = process.wait()
            with self._lock:
                if self._process is not process:
                    return  # a deliberate restart
                self._process = None
                self.last_error = "\n".join(self._stderr_tail[-4:]) or f"core exited with code {code}"
                if self._proxy_backup is not None:
                    try:
                        sysproxy.restore(self._proxy_backup)
                    except Exception:
                        pass
                    self._proxy_backup = None
            self._emit({"type": "crashed", "code": code, "error": self.last_error})

        self._watcher = threading.Thread(target=watch, name="mahyarfree-core-watch", daemon=True)
        self._watcher.start()


_engine: Optional[Engine] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine
