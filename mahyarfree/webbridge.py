"""HTTP transport for the UI.

pywebview is the primary shell, but WebView2 is not guaranteed to exist on
every Windows machine (and cannot exist on Linux at all).  This module serves
the exact same interface over plain HTTP, so the app still works:

    GET  /                -> the UI (static files)
    POST /api/<method>    -> calls Api.<method>(*args) and returns JSON
    GET  /events          -> Server-Sent Events stream pushed from Python
"""

from __future__ import annotations

import json
import mimetypes
import queue
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .core import paths

MAX_BODY = 4 * 1024 * 1024


class EventHub:
    """Fan-out of engine events to every connected browser tab."""

    def __init__(self) -> None:
        self._subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, name: str, payload: Any) -> None:
        message = json.dumps({"name": name, "payload": payload}, ensure_ascii=False)
        with self._lock:
            dead = []
            for box in self._subscribers:
                try:
                    box.put_nowait(message)
                except queue.Full:
                    dead.append(box)
            for box in dead:
                self._subscribers.remove(box)

    def subscribe(self) -> queue.Queue:
        box: queue.Queue = queue.Queue(maxsize=512)
        with self._lock:
            self._subscribers.append(box)
        return box

    def unsubscribe(self, box: queue.Queue) -> None:
        with self._lock:
            if box in self._subscribers:
                self._subscribers.remove(box)


HUB = EventHub()


def make_handler(api: Any, ui_root: Path) -> type:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MahyarFree/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # keep the console quiet
            pass

        # ------------------------------------------------------------ helpers
        def _send(self, status: int, body: bytes, content_type: str,
                  extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _json(self, payload: Any, status: int = 200) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        # ---------------------------------------------------------------- GET
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            route = urllib.parse.unquote(parsed.path)

            if route in ("/", "/index.html"):
                route = "/index.html"

            if route == "/events":
                self._serve_events()
                return

            if route == "/health":
                self._json({"ok": True, "app": "MahyarFree"})
                return

            if route.startswith("/api/"):
                self._call_api(route[len("/api/"):], [])
                return

            target = (ui_root / route.lstrip("/")).resolve()
            try:
                target.relative_to(ui_root.resolve())
            except ValueError:
                self._json({"error": "forbidden"}, 403)
                return

            if not target.is_file():
                self._json({"error": "not found", "path": route}, 404)
                return

            content_type, _ = mimetypes.guess_type(str(target))
            self._send(200, target.read_bytes(), content_type or "application/octet-stream")

        # --------------------------------------------------------------- POST
        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                self._json({"error": "not found"}, 404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json({"error": "payload too large"}, 413)
                return
            raw = self.rfile.read(length) if length else b"[]"
            try:
                args = json.loads(raw.decode("utf-8") or "[]")
            except Exception:
                args = []
            if not isinstance(args, list):
                args = [args]
            self._call_api(parsed.path[len("/api/"):], args)

        # ------------------------------------------------------------ plumbing
        def _call_api(self, method: str, args: List[Any]) -> None:
            function = getattr(api, method, None)
            if function is None or method.startswith("_") or not callable(function):
                self._json({"error": f"unknown method {method}"}, 404)
                return
            try:
                result = function(*args)
                self._json(result if result is not None else {"ok": True})
            except Exception as error:  # never let the UI die on a backend error
                self._json({"ok": False, "error": str(error)}, 500)

        def _serve_events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            box = HUB.subscribe()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        message = box.get(timeout=15)
                        self.wfile.write(f"data: {message}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                HUB.unsubscribe(box)

    return Handler


class WebServer:
    def __init__(self, api: Any, host: str = "127.0.0.1", port: int = 0) -> None:
        self.api = api
        self.ui_root = paths.ui_dir()
        handler = make_handler(api, self.ui_root)
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.host = host

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/index.html"

    def start(self) -> "WebServer":
        threading.Thread(target=self.httpd.serve_forever, daemon=True,
                         name="mahyarfree-http").start()
        return self

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
        except Exception:
            pass


def run(api: Any, port: int = 0, open_browser: bool = True,
        on_ready: Optional[Callable[[str], None]] = None) -> WebServer:
    """Start the HTTP UI and (optionally) open it in the default browser."""
    server = WebServer(api, port=port).start()

    # route every engine event into the SSE hub instead of evaluate_js
    api.emitter = HUB.publish

    if on_ready:
        on_ready(server.url)
    if open_browser:
        webbrowser.open(server.url)
    return server


def serve_blocking(api: Any, port: int = 0, open_browser: bool = True) -> int:
    server = run(api, port=port, open_browser=open_browser,
                 on_ready=lambda url: print(f"MahyarFree is running at {url}"))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0
