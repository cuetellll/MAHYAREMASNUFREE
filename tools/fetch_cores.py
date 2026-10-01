"""Download the Windows core binaries into ``mahyarfree/bin``.

The build script runs this so the packaged .exe ships with sing-box and Xray
already inside, meaning the end user never waits for a download on first run.

    python3 tools/fetch_cores.py            # windows amd64 (default)
    python3 tools/fetch_cores.py --arch arm64
"""

from __future__ import annotations

import argparse
import io
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mahyarfree.core.cores import SINGBOX_PINNED, SINGBOX_REPO, XRAY_PINNED, XRAY_REPO  # noqa: E402

TARGET = ROOT / "mahyarfree" / "bin"


def download(url: str, label: str) -> bytes:
    print(f"  downloading {label}")
    request = urllib.request.Request(url, headers={"User-Agent": "MahyarFree-build"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def extract_member(payload: bytes, archive_name: str, wanted: str) -> bytes:
    buffer = io.BytesIO(payload)
    if archive_name.endswith(".zip"):
        with zipfile.ZipFile(buffer) as archive:
            for member in archive.namelist():
                if Path(member).name.lower() == wanted.lower():
                    return archive.read(member)
    else:
        with tarfile.open(fileobj=buffer) as archive:
            for member in archive.getmembers():
                if Path(member.name).name.lower() == wanted.lower():
                    handle = archive.extractfile(member)
                    if handle:
                        return handle.read()
    raise SystemExit(f"could not find {wanted} inside {archive_name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", default="amd64", choices=["amd64", "arm64", "386"])
    args = parser.parse_args()

    TARGET.mkdir(parents=True, exist_ok=True)

    singbox_version = SINGBOX_PINNED.lstrip("v")
    singbox_asset = f"sing-box-{singbox_version}-windows-{args.arch}.zip"
    singbox_url = f"https://github.com/{SINGBOX_REPO}/releases/download/{SINGBOX_PINNED}/{singbox_asset}"

    payload = download(singbox_url, singbox_asset)
    (TARGET / "sing-box.exe").write_bytes(extract_member(payload, singbox_asset, "sing-box.exe"))
    print("  -> mahyarfree/bin/sing-box.exe")

    xray_asset = "Xray-windows-64.zip" if args.arch in ("amd64", "386") else "Xray-windows-arm64-v8a.zip"
    xray_url = f"https://github.com/{XRAY_REPO}/releases/download/{XRAY_PINNED}/{xray_asset}"
    try:
        payload = download(xray_url, xray_asset)
    except Exception as error:
        print(f"  pinned Xray unavailable ({error}); falling back to latest")
        xray_url = f"https://github.com/{XRAY_REPO}/releases/latest/download/{xray_asset}"
        payload = download(xray_url, xray_asset)

    (TARGET / "xray.exe").write_bytes(extract_member(payload, xray_asset, "xray.exe"))
    print("  -> mahyarfree/bin/xray.exe")

    for name in ("sing-box.exe", "xray.exe"):
        path = TARGET / name
        print(f"  {name}: {path.stat().st_size / 1024 / 1024:.1f} MB")

    shutil.rmtree(TARGET / "__pycache__", ignore_errors=True)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
