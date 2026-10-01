"""Subscription fetching and the persisted node cache."""

from __future__ import annotations

import json
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import paths, uri_parser
from ..version import USER_AGENT


class SubscriptionError(RuntimeError):
    pass


def _fetch(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Cache-Control": "no-cache",
    })
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise SubscriptionError(f"HTTP {error.code}") from error
    except Exception as error:
        raise SubscriptionError(str(error)) from error

    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


class NodeStore:
    """Holds the merged node list from every enabled subscription."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.nodes: List[Dict[str, Any]] = []
        self.latency: Dict[str, Optional[int]] = {}
        self.favourites: set[str] = set()
        self.last_update = 0.0
        self.errors: Dict[str, str] = {}
        self._load_cache()

    # ---------------------------------------------------------------- cache
    def _load_cache(self) -> None:
        try:
            if paths.NODES_FILE.exists():
                data = json.loads(paths.NODES_FILE.read_text(encoding="utf-8"))
                self.nodes = data.get("nodes", [])
                self.favourites = set(data.get("favourites", []))
                self.last_update = float(data.get("last_update") or 0)
                self.latency = {k: v for k, v in (data.get("latency") or {}).items()}
        except Exception:
            self.nodes = []

    def save_cache(self) -> None:
        try:
            paths.ensure_dirs()
            paths.NODES_FILE.write_text(json.dumps({
                "nodes": self.nodes,
                "favourites": sorted(self.favourites),
                "last_update": self.last_update,
                "latency": self.latency,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------ updating
    def refresh(
        self,
        subscriptions: List[Dict[str, Any]],
        progress: Optional[Callable[[str, float], None]] = None,
    ) -> Dict[str, Any]:
        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()
        errors: Dict[str, str] = {}
        enabled = [s for s in subscriptions if s.get("enabled", True) and s.get("url")]

        for index, sub in enumerate(enabled):
            name = sub.get("name") or f"sub-{index + 1}"
            if progress:
                progress(f"دریافت {name}", index / max(1, len(enabled)))
            try:
                text = _fetch(sub["url"])
            except SubscriptionError as error:
                errors[name] = str(error)
                continue
            parsed = uri_parser.parse_subscription_text(text)
            if not parsed:
                errors[name] = "هیچ سروری در این لینک پیدا نشد"
                continue
            for spec in parsed:
                if spec["id"] in seen:
                    continue
                seen.add(spec["id"])
                spec["group"] = name
                spec["group_id"] = sub.get("id") or name
                spec["name"] = uri_parser.humanize_name(spec["name"])
                spec["country"] = uri_parser.guess_country(spec["name"], spec["server"])
                spec["name"] = uri_parser.humanize_name(uri_parser.strip_flags(spec["name"]))
                spec["core"] = uri_parser.sniff_core(spec)
                merged.append(spec)

        with self._lock:
            if merged:
                self.nodes = merged
                self.last_update = time.time()
            self.errors = errors
            # prune latency entries for nodes that disappeared
            valid = {n["id"] for n in self.nodes}
            self.latency = {k: v for k, v in self.latency.items() if k in valid}
        self.save_cache()
        if progress:
            progress("", 1.0)
        return {
            "count": len(self.nodes),
            "errors": errors,
            "updated": self.last_update,
        }

    # ------------------------------------------------------------- queries
    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.nodes)

    def by_id(self, node_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((n for n in self.nodes if n["id"] == node_id), None)

    def set_latency(self, node_id: str, value: Optional[int]) -> None:
        with self._lock:
            self.latency[node_id] = value

    def toggle_favourite(self, node_id: str) -> bool:
        with self._lock:
            if node_id in self.favourites:
                self.favourites.discard(node_id)
                state = False
            else:
                self.favourites.add(node_id)
                state = True
        self.save_cache()
        return state

    def view(self) -> List[Dict[str, Any]]:
        """Compact, UI-ready representation of every node."""
        with self._lock:
            out = []
            for node in self.nodes:
                out.append({
                    "id": node["id"],
                    "name": node["name"],
                    "server": node["server"],
                    "port": node["port"],
                    "protocol": node["protocol"],
                    "group": node.get("group", ""),
                    "country": node.get("country", "🌐"),
                    "core": node.get("core", "sing-box"),
                    "latency": self.latency.get(node["id"]),
                    "favourite": node["id"] in self.favourites,
                    "transport": (node.get("transport") or {}).get("type", "tcp"),
                    "tls": bool((node.get("tls") or {}).get("enabled")),
                })
            return out


_store: Optional[NodeStore] = None


def get_store() -> NodeStore:
    global _store
    if _store is None:
        paths.ensure_dirs()
        _store = NodeStore()
    return _store
