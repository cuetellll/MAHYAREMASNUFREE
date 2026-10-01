"""MahyarFree – application entry point.

Run with:  python app.py
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time
from pathlib import Path

# make "python app.py" work from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mahyarfree.api import Api                      # noqa: E402
from mahyarfree.core import paths                   # noqa: E402
from mahyarfree.core.settings import get_settings   # noqa: E402
from mahyarfree.version import APP_NAME, __version__  # noqa: E402

WINDOW_BG = "#05060e"


def _set_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MahyarFree.VPN.1")
    except Exception:
        pass


def _single_instance_guard() -> bool:
    """Return False when another MahyarFree instance already owns the mutex."""
    if os.name != "nt":
        return True
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\MahyarFreeSingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        globals()["_MUTEX_HANDLE"] = handle
    except Exception:
        pass
    return True


def build_window(api: Api, settings) -> "object":
    import webview  # imported lazily so --help works without the dependency

    ui_file = paths.ui_dir() / "index.html"
    if not ui_file.exists():
        raise SystemExit(f"UI files are missing: {ui_file}")

    window = webview.create_window(
        title=APP_NAME,
        url=str(ui_file),
        js_api=api,
        width=int(settings.get("window_width", 1180)),
        height=int(settings.get("window_height", 760)),
        min_size=(980, 640),
        frameless=True,
        easy_drag=False,
        background_color=WINDOW_BG,
        resizable=True,
        text_select=False,
    )
    api.window = window
    return window


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {__version__}")
    parser.add_argument("--elevated", action="store_true", help="internal: relaunched with admin rights")
    parser.add_argument("--debug", action="store_true", help="open the developer console")
    parser.add_argument("--serve", action="store_true", help="serve the UI over HTTP for design work")
    parser.add_argument("--port", type=int, default=8777, help="port used with --serve")
    parser.add_argument("--browser", action="store_true",
                        help="force the browser UI instead of the native window")
    parser.add_argument("--no-open", action="store_true", help="do not auto-open the browser")
    args = parser.parse_args()

    paths.ensure_dirs()
    settings = get_settings()

    if args.serve:
        from tools.preview_server import serve

        serve(port=args.port)
        return 0

    if args.browser:
        return _run_in_browser(args)

    if not _single_instance_guard():
        print("MahyarFree is already running.")
        return 0

    _set_app_user_model_id()

    try:
        import webview  # noqa: F401
    except ImportError:
        print("pywebview is not installed - falling back to the browser interface.")
        return _run_in_browser(args)

    api = Api()
    build_window(api, settings)

    import webview

    gui = None
    if os.name == "nt":
        gui = "edgechromium"

    def on_start() -> None:
        if settings.get("update_on_start", True):
            threading.Thread(target=lambda: (time.sleep(1.2), api.refresh(wait=True)),
                             daemon=True, name="mahyarfree-boot-refresh").start()
        if settings.get("auto_best_on_start"):
            threading.Thread(target=lambda: (time.sleep(3.0), api.connect_best()),
                             daemon=True, name="mahyarfree-boot-connect").start()

    try:
        webview.start(on_start, gui=gui, debug=args.debug, private_mode=False,
                      storage_path=str(paths.DATA_DIR / "webview"))
    except TypeError:
        # older pywebview builds do not accept every keyword
        webview.start(on_start, gui=gui, debug=args.debug)
    except Exception as error:  # WebView2 missing, broken runtime, ...
        print(f"native window failed ({error}) - falling back to the browser interface.")
        return _run_in_browser(args)
    finally:
        try:
            api.engine.stop()
        except Exception:
            pass
    return 0


def _run_in_browser(args) -> int:
    """Serve the identical UI over HTTP and open the default browser."""
    from mahyarfree import webbridge

    api = Api()
    settings = get_settings()

    if settings.get("update_on_start", True):
        threading.Thread(target=lambda: (time.sleep(1.0), api.refresh(wait=True)),
                         daemon=True, name="mahyarfree-boot-refresh").start()
    if settings.get("auto_best_on_start"):
        threading.Thread(target=lambda: (time.sleep(6.0), api.connect_best()),
                         daemon=True, name="mahyarfree-boot-connect").start()

    try:
        return webbridge.serve_blocking(api, port=0, open_browser=not args.no_open)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            api.engine.stop()
            api.monitor.stop()
        except Exception:
            pass


def _report_startup_error(error: BaseException) -> None:
    """Leave a useful log and visible message for a double-click launch failure."""
    import traceback

    details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    log_path = Path(os.environ.get("APPDATA", Path.home())) / "MahyarFree" / "logs" / "startup.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n--- MahyarFree startup failure ---\n")
            log.write(details)
    except Exception:
        log_path = Path("startup.log")
        try:
            log_path.write_text(details, encoding="utf-8")
        except Exception:
            pass

    message = f"MahyarFree could not start.\n\n{error}\n\nLog: {log_path}"
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, message, "MahyarFree — خطای اجرا", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)
    print(details, file=sys.stderr)


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except SystemExit:
        raise
    except BaseException as error:
        _report_startup_error(error)
        raise SystemExit(1)
    raise SystemExit(exit_code)
