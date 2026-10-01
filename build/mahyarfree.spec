# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for MahyarFree.

    pyinstaller build/mahyarfree.spec --noconfirm --clean

Produces ``dist/MahyarFree/`` containing the executable, the bundled UI and the
two proxy cores under ``core/``.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
PACKAGE = ROOT / "mahyarfree"
BIN_DIR = PACKAGE / "bin"

datas = [
    (str(PACKAGE / "ui"), "mahyarfree/ui"),
]

# ship the cores next to the executable so paths.bundled_core_dir() finds them
binaries = []
if BIN_DIR.exists():
    for name in ("sing-box.exe", "xray.exe"):
        candidate = BIN_DIR / name
        if candidate.exists():
            binaries.append((str(candidate), "core"))

hiddenimports = [
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
    "http.server",
    "urllib.request",
    "urllib.parse",
    "ssl",
    "json",
    "socket",
    "subprocess",
    "winreg",
    "ctypes",
    "tkinter",
]

hiddenimports += collect_submodules("mahyarfree")

icon_path = PACKAGE / "ui" / "assets" / "img" / "icon.ico"

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "numpy",
        "pandas", "scipy", "PIL", "pytest", "setuptools",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MahyarFree",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MahyarFree",
)
