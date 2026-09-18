"""Marvin Windows desktop entry point.

Startup checks the environment, starts local services and opens a WebView2 window. Closing the window stops the services and releases GPU memory.

Run with pythonw for a console-free shortcut, python for diagnostics, or --smoke for a windowless lifecycle check. Without pywebview, the system browser is the compatibility fallback."""
from __future__ import annotations

import atexit
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from harness.version import APP_VERSION
from harness.i18n import detect_language, set_language, t

# UI language: user choice > installer file > English (must be set before webapp import)
set_language(detect_language(ROOT) or "en")

# Redirect pythonw output to a log so failures remain diagnosable.
if sys.stdout is None or sys.stderr is None:
    _logdir = ROOT / "runtime"
    _logdir.mkdir(parents=True, exist_ok=True)
    _logfile = open(_logdir / "app.log", "a", buffering=1, encoding="utf-8")
    _logfile.write(f"\n===== APP START {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    sys.stdout = _logfile
    sys.stderr = _logfile


def _alert(msg: str) -> None:
    """Show a native message box using ctypes without external dependencies."""
    print(f"[APP] {msg}", file=sys.stderr)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, msg, f"Marvin v{APP_VERSION}", 0x10)
    except Exception:
        pass


def preflight(cfg) -> list[str]:
    """What is missing to run (llama.cpp, model)."""
    problems = []
    if cfg.llama_server_exe() is None:
        problems.append("llama.cpp binaries (runtime/llama)")
    if not cfg.model_ready():
        problems.append(f"model {cfg.model_key()} (runtime/models)")
    return problems


def _focus_window() -> None:
    """Bring the application window forward when WebView2 opens it in the background."""
    import ctypes
    import time as _t
    _t.sleep(0.8)
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(h, l):
            buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(h, buf, 128)
            if "Marvin" in buf.value:
                found.append(h)
            return True

        user32.EnumWindows(cb, 0)
        for h in found:
            user32.ShowWindow(h, 9)          # SW_RESTORE
            user32.SetForegroundWindow(h)
    except Exception:
        pass


def main() -> int:
    from harness import servermgmt
    from harness.config import load_config

    cfg = load_config()
    smoke = "--smoke" in sys.argv

    # ---- 1) preflight ---------------------------------------------------
    problems = preflight(cfg)
    if problems:
        _alert(t("Missing required components:\n  • {items}\n\nRun the environment setup:\n  "
                 ".venv\\Scripts\\python scripts\\setup_env.py", items="\n  • ".join(problems)))
        return 1

    # 2) Start llama-server if needed.
    we_started_server = not servermgmt.health(cfg)
    if we_started_server:
        print("[APP] Starting llama-server ...")
        if servermgmt.start(cfg) != 0:
            _alert(t("llama-server could not be started.\nDetails: runtime\\llama-server.log"))
            return 1
    else:
        print(f"[APP] llama-server already running ({servermgmt.running_model(cfg)}) - reusing it.")

    # ---- 3) Web UI (in-process) ------------------------------------------
    import webapp
    webapp.RELOAD_ENABLED = False  # embedded launch has no rebuild loop
    host, port = cfg.web["host"], int(cfg.web["port"])
    ui = None
    if not webapp._is_our_webui(host, port):
        print("[APP] Starting Web UI ...")
        ui = webapp.build_ui()
        ui.launch(server_name=host, server_port=port,
                  show_error=True, inbrowser=False, prevent_thread_lock=True,
                  allowed_paths=[str(cfg.path("paths.sessions_dir"))])
        for _ in range(120):
            if webapp._is_our_webui(host, port):
                break
            time.sleep(0.5)
    url = f"http://{host}:{port}"

    # 4) Always stop services and release GPU memory when the window closes.
    cleaned = {"done": False}

    def cleanup() -> None:
        if cleaned["done"]:
            return
        cleaned["done"] = True
        print("[APP] Shutting down: stopping Web UI ...")
        if ui is not None:
            try:
                ui.close()
            except Exception:
                pass
        print("[APP] Stopping llama-server (freeing VRAM) ...")
        try:
            servermgmt.stop(cfg, quiet=True)
            print("[APP] Done - VRAM freed.")
        except Exception as e:
            print(f"[APP] Warning: server could not be stopped cleanly ({e}); "
                  f"manually: taskkill /F /IM llama-server.exe")

    atexit.register(cleanup)

    # ---- 5) window / smoke test -------------------------------------------
    if smoke:
        print(f"[APP] SMOKE: everything running at {url} - exiting after 3 s (cleanup test).")
        time.sleep(3)
        cleanup()
        return 0

    try:
        import webview  # pywebview (WebView2)
        model = servermgmt.running_model(cfg) or cfg.model_key()
        webview.create_window(
            f"Marvin v{APP_VERSION} - {model}",
            url, width=1440, height=920, min_size=(960, 640),
            background_color="#0b0e14",
            # pywebview disables selection unless asked for.
            text_select=True,
        )
        print(f"[APP] Window opened: {url}")
        webview.start(_focus_window)  # Block until the window closes.
    except ImportError:
        import webbrowser
        print(f"[APP] pywebview missing - opening system browser: {url}")
        webbrowser.open(url)
        try:
            input("[APP] Enter/closing the console quits (the server will stop)...\n")
        except EOFError:
            pass
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        _alert(t("The app crashed – details in runtime\\app.log"))
        raise SystemExit(1)
