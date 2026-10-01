"""Windows "Internet Options" proxy control, with full state restore.

On non-Windows platforms this is a no-op so the app can be developed and
smoke-tested on Linux/macOS.
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Any, Dict, Optional

IS_WINDOWS = os.name == "nt"

INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37

_SETTINGS_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

DEFAULT_BYPASS = (
    "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.20.*;"
    "172.21.*;172.22.*;172.23.*;172.24.*;172.25.*;172.26.*;172.27.*;"
    "172.28.*;172.29.*;172.30.*;172.31.*;192.168.*;<local>"
)


def _winreg():
    import winreg  # type: ignore

    return winreg


def _notify_windows() -> None:
    if not IS_WINDOWS:
        return
    try:
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except Exception:
        pass


def snapshot() -> Dict[str, Any]:
    """Remember the current proxy configuration so it can be restored."""
    state: Dict[str, Any] = {"supported": IS_WINDOWS, "enable": 0, "server": "", "override": "", "autoconfig": ""}
    if not IS_WINDOWS:
        return state
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SETTINGS_KEY) as key:
            for name, field in (("ProxyEnable", "enable"), ("ProxyServer", "server"),
                                ("ProxyOverride", "override"), ("AutoConfigURL", "autoconfig")):
                try:
                    state[field] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    pass
    except Exception:
        pass
    return state


def _write(values: Dict[str, Any]) -> None:
    if not IS_WINDOWS:
        return
    winreg = _winreg()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _SETTINGS_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name, value in values.items():
            if value is None:
                continue
            if isinstance(value, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
    _notify_windows()


def _delete(names: list[str]) -> None:
    if not IS_WINDOWS:
        return
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SETTINGS_KEY, 0, winreg.KEY_SET_VALUE) as key:
            for name in names:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
    except Exception:
        pass
    _notify_windows()


def enable(socks_port: int, http_port: int, bypass_lan: bool = True) -> Dict[str, Any]:
    """Point Windows at the local mixed inbound; returns the previous state."""
    previous = snapshot()
    server = f"127.0.0.1:{http_port or socks_port}"
    if http_port and socks_port and http_port != socks_port:
        server = f"http=127.0.0.1:{http_port};socks=127.0.0.1:{socks_port}"
    _write({
        "ProxyEnable": 1,
        "ProxyServer": server,
        "ProxyOverride": DEFAULT_BYPASS if bypass_lan else "localhost;127.*;<local>",
        "AutoConfigURL": None,
    })
    return previous


def disable() -> None:
    _write({"ProxyEnable": 0})
    _delete(["AutoConfigURL"])


def restore(state: Optional[Dict[str, Any]]) -> None:
    if not state or not state.get("supported"):
        return
    try:
        _write({"ProxyEnable": int(state.get("enable") or 0)})
        if state.get("server"):
            _write({"ProxyServer": state["server"]})
        if state.get("override"):
            _write({"ProxyOverride": state["override"]})
        if state.get("autoconfig"):
            _write({"AutoConfigURL": state["autoconfig"]})
        else:
            _delete(["AutoConfigURL"])
    except Exception:
        pass


def is_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        winreg = _winreg()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _SETTINGS_KEY) as key:
            return bool(winreg.QueryValueEx(key, "ProxyEnable")[0])
    except Exception:
        return False


def is_elevated() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate() -> bool:
    """Re-launch the current executable as administrator (TUN mode needs it)."""
    if not IS_WINDOWS:
        return False
    try:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv[1:]) + " --elevated"
        else:
            executable = sys.executable
            params = " ".join(f'"{a}"' for a in [*sys.argv, "--elevated"])
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        return int(result) > 32
    except Exception:
        return False
