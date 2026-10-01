"""Filesystem layout for MahyarFree.

Everything the app writes lives under a single data directory so that
uninstalling is as easy as deleting one folder.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "MahyarFree"


def _base_data_dir() -> Path:
    override = os.environ.get("MAHYARFREE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        if getattr(sys, "frozen", False):
            app_dir = Path(sys.executable).resolve().parent
            if (app_dir / "portable.flag").is_file():
                return app_dir / "data"
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / APP_DIR_NAME
        return Path.home() / APP_DIR_NAME
    # Linux / macOS (used for development and CI smoke tests)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


DATA_DIR = _base_data_dir()
CORE_DIR = DATA_DIR / "core"
CONFIG_DIR = DATA_DIR / "config"
LOG_DIR = DATA_DIR / "logs"
CACHE_DIR = DATA_DIR / "cache"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
NODES_FILE = CACHE_DIR / "nodes.json"
RUNTIME_CONFIG = CONFIG_DIR / "runtime.json"
APP_LOG = LOG_DIR / "app.log"
CORE_LOG = LOG_DIR / "core.log"


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (works in PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def bundled_core_dir() -> Path:
    """Where pre-bundled core binaries live inside the package/dist."""
    if getattr(sys, "frozen", False):
        # PyInstaller onedir (v6+) stores collected binaries under _MEIPASS,
        # usually the app's _internal directory, not beside the launcher exe.
        return resource_dir() / "core"
    return resource_dir() / "bin"


def ui_dir() -> Path:
    return resource_dir() / "ui"


def ensure_dirs() -> None:
    for directory in (DATA_DIR, CORE_DIR, CONFIG_DIR, LOG_DIR, CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
