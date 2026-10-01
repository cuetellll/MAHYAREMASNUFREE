"""Locate / download / verify the sing-box and Xray-core binaries.

The Windows build ships both binaries next to the executable.  If they are
missing (source checkout, or the user deleted them) the app can fetch the
official releases on first run.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional

from . import paths
from ..version import USER_AGENT

SINGBOX_REPO = "SagerNet/sing-box"
XRAY_REPO = "XTLS/Xray-core"

SINGBOX_PINNED = "v1.14.2"
XRAY_PINNED = "v25.9.11"

BINARIES = {
    "sing-box": "sing-box.exe" if os.name == "nt" else "sing-box",
    "xray": "xray.exe" if os.name == "nt" else "xray",
}

ProgressFn = Optional[Callable[[str, float], None]]


def _report(progress: ProgressFn, message: str, value: float) -> None:
    if progress:
        try:
            progress(message, value)
        except Exception:
            pass


# --------------------------------------------------------------------------
# platform asset names
# --------------------------------------------------------------------------

def _singbox_asset() -> str:
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "windows":
        arch = "amd64" if machine in ("amd64", "x86_64") else ("arm64" if machine in ("arm64", "aarch64") else "386")
        return f"sing-box-{SINGBOX_PINNED.lstrip('v')}-windows-{arch}.zip"
    if system == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
        return f"sing-box-{SINGBOX_PINNED.lstrip('v')}-darwin-{arch}.tar.gz"
    arch = "amd64" if machine in ("amd64", "x86_64") else "arm64"
    return f"sing-box-{SINGBOX_PINNED.lstrip('v')}-linux-{arch}.tar.gz"


def _xray_asset() -> str:
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "windows":
        return "Xray-windows-64.zip" if machine in ("amd64", "x86_64") else "Xray-windows-32.zip"
    if system == "darwin":
        return "Xray-macos-arm64-v8a.zip" if machine in ("arm64", "aarch64") else "Xray-macos-64.zip"
    return "Xray-linux-arm64-v8a.zip" if machine in ("arm64", "aarch64") else "Xray-linux-64.zip"


def _download(url: str, target: Path, progress: ProgressFn = None, label: str = "") -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(target, "wb") as handle:
            while True:
                chunk = response.read(262144)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if total:
                    _report(progress, label or f"downloading {target.name}", done / total)
    return target


def _extract(archive: Path, destination: Path, wanted: str) -> Optional[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    found: Optional[Path] = None
    if archive.suffix == ".zip" or zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if Path(member).name.lower() == wanted.lower():
                    with zf.open(member) as src, open(destination / wanted, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found = destination / wanted
                    break
    else:
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                if Path(member.name).name.lower() == wanted.lower():
                    extracted = tf.extractfile(member)
                    if extracted:
                        with open(destination / wanted, "wb") as dst:
                            shutil.copyfileobj(extracted, dst)
                        found = destination / wanted
                    break
    if found:
        try:
            found.chmod(found.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
    return found


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def core_path(name: str) -> Optional[Path]:
    """Return the executable path for a core if it exists."""
    filename = BINARIES.get(name)
    if not filename:
        return None
    candidates = [
        paths.bundled_core_dir() / filename,
        paths.CORE_DIR / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def version_of(name: str) -> str:
    exe = core_path(name)
    if not exe:
        return ""
    try:
        result = subprocess.run(
            [str(exe), "version"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first = (result.stdout or result.stderr or "").strip().splitlines()
        return first[0].strip() if first else ""
    except Exception:
        return ""


def ensure_core(name: str, progress: ProgressFn = None) -> Optional[Path]:
    """Make sure a core exists locally, downloading it when necessary."""
    existing = core_path(name)
    if existing:
        return existing

    paths.ensure_dirs()
    with tempfile.TemporaryDirectory(prefix="mahyarfree-core-") as tmp:
        tmpdir = Path(tmp)
        if name == "sing-box":
            asset = _singbox_asset()
            url = f"https://github.com/{SINGBOX_REPO}/releases/download/{SINGBOX_PINNED}/{asset}"
            wanted = BINARIES["sing-box"]
        elif name == "xray":
            asset = _xray_asset()
            url = f"https://github.com/{XRAY_REPO}/releases/download/{XRAY_PINNED}/{asset}"
            wanted = BINARIES["xray"]
        else:
            return None

        try:
            _report(progress, f"downloading {name}", 0.02)
            archive = _download(url, tmpdir / asset, progress, label=f"downloading {name}")
            _report(progress, f"extracting {name}", 0.85)
            result = _extract(archive, paths.CORE_DIR, wanted)
            _report(progress, f"{name} ready", 1.0)
            return result
        except Exception:
            # fall back to the "latest" release if the pinned tag disappeared
            try:
                latest = f"https://github.com/{SINGBOX_REPO if name == 'sing-box' else XRAY_REPO}/releases/latest/download/{asset}"
                archive = _download(latest, tmpdir / asset, progress, label=f"downloading {name}")
                return _extract(archive, paths.CORE_DIR, wanted)
            except Exception:
                return None


def core_status() -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for name in ("sing-box", "xray"):
        path = core_path(name)
        out[name] = {
            "available": bool(path),
            "path": str(path) if path else "",
            "version": version_of(name) if path else "",
        }
    return out


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def no_window_kwargs() -> Dict[str, object]:
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return {"startupinfo": startupinfo, "creationflags": _creation_flags()}
    return {}
