"""Marvin desktop launcher, packaged as Marvin.exe by PyInstaller.

Startup prepares desktop components and checks the environment, then opens the web workspace while the model starts in the background. Closing the window stops its services and releases GPU memory.

Build: installer/build_exe.bat
Lifecycle diagnostic: Marvin.exe --smoke"""
from __future__ import annotations

import atexit
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller exe
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _app_root()
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

from harness.dependencies import dependencies_current
from harness.i18n import detect_language, set_language, t
from harness.version import APP_COPYRIGHT, APP_VERSION
from harness.webview_runtime import ensure_webview2

# UI language for dialogs/splash: user choice > installer file > English
set_language(detect_language(ROOT) or "en")

VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"

# logging for the windowed executable without a console
if sys.stdout is None or sys.stderr is None:
    _logdir = ROOT / "runtime"
    _logdir.mkdir(parents=True, exist_ok=True)
    _lf = open(_logdir / "launcher.log", "a", buffering=1, encoding="utf-8")
    _lf.write(f"\n===== LAUNCHER {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    sys.stdout = _lf
    sys.stderr = _lf


def _log(msg: str) -> None:
    print(f"[APP] {msg}")


def _alert(msg: str, question: bool = False) -> bool:
    """Show a message box; confirmation questions return True for Yes."""
    try:
        import ctypes
        flags = 0x24 if question else 0x10  # YESNO+QUESTION | ICON_ERROR
        return ctypes.windll.user32.MessageBoxW(
            None, msg, f"Marvin v{APP_VERSION}", flags) == 6
    except Exception:
        return False


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _check_workspace_api(base_web: str) -> None:
    """Release diagnostic only: prove the UI can open its actual selected chat."""
    with urllib.request.urlopen(base_web + "/api/state", timeout=15) as response:
        state = json.load(response)
    session_id = state.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Workspace did not select a conversation")
    path = base_web + "/api/sessions/" + urllib.parse.quote(session_id, safe="")
    with urllib.request.urlopen(path, timeout=15) as response:
        chat = json.load(response)
    if chat.get("id") != session_id or not isinstance(chat.get("messages"), list):
        raise ValueError("Workspace did not open the selected conversation")
    with urllib.request.urlopen(path + "/detail", timeout=15) as response:
        json.load(response)


def _is_our_webui(base_url: str) -> bool:
    from harness.web_identity import belongs_to_installation
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/config", timeout=2.0) as r:
            payload = json.load(r)
        return r.status == 200 and belongs_to_installation(payload, ROOT, APP_VERSION)
    except Exception:
        return False


def _port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _free_web_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        if not _port_busy(port):
            return port
    raise RuntimeError(t("No free Web UI port in range {start}-{end}",
                         start=preferred, end=preferred + 19))


def _existing_web_port(preferred: int) -> int | None:
    for port in range(preferred, preferred + 20):
        if _port_busy(port) and _is_our_webui(f"http://127.0.0.1:{port}"):
            return port
    return None


def _cfg_ports() -> tuple[int, int]:
    """Read inference and web ports from config.yaml with fallback defaults."""
    srv, web = 8080, 7860
    try:
        text = (ROOT / "config.yaml").read_text(encoding="utf-8")
        m = re.search(r"^server:.*?^\s+port:\s*(\d+)", text, re.S | re.M)
        if m:
            srv = int(m.group(1))
        m = re.search(r"^web:.*?^\s+port:\s*(\d+)", text, re.S | re.M)
        if m:
            web = int(m.group(1))
    except Exception:
        pass
    return srv, web


def _check_model_files() -> tuple[bool, str]:
    """Accept any complete configured model, including models stored in nested shards."""
    from harness.config import Config, load_config
    cfg = Config(load_config(ROOT / "config.yaml").data, ROOT)
    models_dir = cfg.path("paths.models_dir")
    has_model = any(cfg.model_ready(key) for key in cfg.data["models"])
    detail = t("looking in: {path}", path=models_dir)
    return has_model, detail


def _port_pid(port: int) -> int | None:
    """Find the process listening on a port using netstat without psutil."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             text=True, creationflags=0x08000000).stdout
        for line in out.splitlines():
            if "LISTENING" in line and f"127.0.0.1:{port} " in line + " ":
                parts = line.split()
                if len(parts) >= 5:
                    return int(parts[-1])
    except Exception:
        pass
    return None


def _kill_tree(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, creationflags=0x08000000)  # hide the console
    except Exception:
        pass


def _run_setup_console() -> bool:
    """Run environment and model setup in a visible console."""
    bat = ROOT / "run_setup.bat"
    if not bat.exists():
        _alert(t("Missing {name} — run the installation manually as described in README.",
                 name=bat.name))
        return False
    rc = subprocess.call(["cmd", "/c", str(bat)], cwd=str(ROOT))
    return rc == 0


def _focus_window() -> None:
    """Bring the window to the foreground using a brief topmost toggle.

    Retry because WebView2 initialization can delay creation of the native window."""
    import ctypes
    import time as _t
    _t.sleep(2.0)
    try:
        from ctypes import wintypes
        u = ctypes.windll.user32
        SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        for _attempt in range(3):
            found: list[int] = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def cb(h, l):
                buf = ctypes.create_unicode_buffer(128)
                u.GetWindowTextW(h, buf, 128)
                if "Marvin" in buf.value:
                    found.append(h)
                return True

            u.EnumWindows(cb, 0)
            if found:
                for h in found:
                    u.ShowWindow(h, 9)  # SW_RESTORE
                    # Toggle topmost to raise the window even when Windows restricts focus changes.
                    u.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                    u.SetWindowPos(h, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                    u.SetForegroundWindow(h)
                    u.BringWindowToTop(h)
                return
            _t.sleep(1.0)
    except Exception:
        pass


_splash_done: "threading.Event | None" = None


def _show_splash() -> None:
    """Show a small startup splash immediately.

    Use native Tk without a console; skip it gracefully when Tk is unavailable."""
    global _splash_done
    try:
        import tkinter as tk

        def _run():
            global _splash_done
            try:
                root = tk.Tk()
                root.title(f"Marvin v{APP_VERSION}")
                root.overrideredirect(True)
                root.attributes("-topmost", True)
                root.configure(bg="#0b0e14")
                splash_text = (f"Marvin v{APP_VERSION}\n\n{t('starting …')}")
                tk.Label(root, text=splash_text,
                         font=("Segoe UI", 13), padx=36, pady=16,
                         bg="#0b0e14", fg="#e8f0ff").pack(fill="both", expand=True)
                tk.Label(root, text=APP_COPYRIGHT, font=("Segoe UI", 9),
                         bg="#0b0e14", fg="#8b949e").pack(side="bottom", pady=(0, 12))
                root.update_idletasks()
                w, h = 320, 145
                x = (root.winfo_screenwidth() - w) // 2
                y = (root.winfo_screenheight() - h) // 2
                root.geometry(f"{w}x{h}+{x}+{y}")
                while not _splash_done.is_set():
                    root.update()
                    time.sleep(0.05)
                root.destroy()
            except Exception:
                pass

        import threading
        _splash_done = threading.Event()
        threading.Thread(target=_run, daemon=True, name="splash").start()
    except Exception:
        pass


def _close_splash() -> None:
    if _splash_done is not None:
        _splash_done.set()


def _write_loading_page(web_port: int):
    """Create the initial loading page, which redirects when the workspace server is ready."""
    d = ROOT / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    p = d / ".loading.html"
    loading_msg = t("starting the interface… (first run takes a while)")
    slow_msg = t("still starting… (details: runtime/launcher.log)")
    p.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<title>Marvin</title>
<style>
body{{background:#0b0e14;color:#e6edf3;font-family:'Segoe UI',system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;
flex-direction:column;gap:20px}}
.r{{width:56px;height:56px;border:4px solid rgba(45,212,191,.18);
border-top-color:#2dd4bf;border-radius:50%;animation:s 1s linear infinite}}
@keyframes s{{to{{transform:rotate(360deg)}}}}
h1{{font-size:21px;font-weight:600;margin:0}} h1 b{{color:#2dd4bf}}
small{{color:#8b949e}}
.copyright{{position:fixed;bottom:20px;font-size:11px}}
</style></head><body>
<div class="r"></div>
<h1><b>Marvin</b> <small>v{APP_VERSION}</small></h1>
<small id="s">{loading_msg}</small>
<small class="copyright">{APP_COPYRIGHT}</small>
<script>
const APP='http://127.0.0.1:{web_port}/';
const t0=Date.now();
(async function probe(){{
  try{{ await fetch(APP+'config',{{mode:'no-cors'}}); location.replace(APP); return; }}catch(e){{}}
  if(Date.now()-t0>20000)
    document.getElementById('s').textContent={slow_msg!r};
  setTimeout(probe,400);
}})();
</script></body></html>""", encoding="utf-8")
    return p


def main() -> int:
    if "--prepare-webview2" in sys.argv:
        # Called by Setup after files are copied; no venv, backend or model needed.
        try:
            ensure_webview2(ROOT, _log)
            return 0
        except Exception as exc:
            _log(f"Desktop preparation failed: {exc}")
            return 1
    smoke = "--smoke" in sys.argv
    srv_port, web_port = _cfg_ports()
    base_srv = f"http://127.0.0.1:{srv_port}"
    base_web = f"http://127.0.0.1:{web_port}"

    if not smoke:
        _show_splash()
        try:
            ensure_webview2(ROOT, _log)
        except Exception as exc:
            _log(f"Desktop preparation failed: {exc}")
            _close_splash()
            _alert(t("Desktop components could not be prepared. Connect to the internet and "
                     "start Marvin again, or run the Full installer for offline setup."))
            return 1

    for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP"):
        os.environ.pop(key, None)
    os.environ["PYTHONNOUSERSITE"] = "1"
    private_python = ROOT / "runtime" / "python" / "python.exe"
    if private_python.is_file():
        rc = subprocess.call([str(private_python), "-I", "scripts/bootstrap_full.py"],
                             cwd=ROOT, creationflags=0x08000000)
        if rc:
            _close_splash()
            _alert("Bundled Python environment could not be prepared. See runtime/launcher.log.")
            return 1

    # 1) Check environment, inference runtime and model files.
    problems = []
    if not VENV_PY.exists():
        problems.append(t("Python environment (.venv)"))
    elif not dependencies_current(ROOT / "requirements.txt", ROOT / ".venv"):
        problems.append(t("Python dependencies (new requirements.txt version)"))
    if not (ROOT / "runtime" / "llama").exists() or not any(
            (ROOT / "runtime" / "llama").rglob("llama-server.exe")):
        problems.append("llama.cpp (runtime\\llama)")
    models_ok, models_detail = _check_model_files()
    if not models_ok:
        problems.append(t("Qwen3.8-27B models ({detail})", detail=models_detail))
    if problems:
        _close_splash()
        _log("Missing: " + "; ".join(problems))
        question = t("The app is not fully installed — missing:\n\n  • {items}\n\n"
                     "Run the setup now? (downloads ~37 GB to the right place)",
                     items="\n  • ".join(problems))
        if _alert(question, question=True):
            if not _run_setup_console():
                return 1
            models_ok, _ = _check_model_files()
            deps_ok = dependencies_current(ROOT / "requirements.txt", ROOT / ".venv")
            if not VENV_PY.exists() or not deps_ok or not models_ok:
                _alert(t("Setup failed — try again, or run “Set up environment and models” "
                         "from the Start Menu."))
                return 1
        else:
            return 1

    # 2) Open the web workspace first; load the model in the background.
    # The window opens immediately and displays model startup progress.
    webapp_proc = None
    existing_port = _existing_web_port(web_port)
    webui_running = existing_port is not None
    if existing_port is not None:
        web_port = existing_port
        base_web = f"http://127.0.0.1:{web_port}"
    if not webui_running:
        web_port = _free_web_port(web_port)
        base_web = f"http://127.0.0.1:{web_port}"
    env = {**os.environ, "QWEN_NO_BROWSER": "1", "QWEN_AUTOSTART_SERVER": "1",
           "QWEN_WEB_PORT": str(web_port)}
    if not webui_running:
        _log("Starting Web UI (model loads in the background) ...")
        webapp_proc = subprocess.Popen(
            [str(VENV_PYW), "webapp.py"], cwd=str(ROOT), env=env,
            creationflags=0x08000000)
        if not smoke:
            # Open the loading page immediately; it redirects when the UI is ready.
            # This avoids leaving the user on the splash during backend initialization.
            loading = _write_loading_page(web_port)
            url = loading.as_uri()
            _log(f"Window opened immediately (loading page) → {base_web}")
        else:
            for _ in range(120):
                if _http_ok(f"{base_web}/config"):
                    break
                time.sleep(0.5)
            url = base_web
    else:
        url = base_web
        def start_existing_model():
            try:
                request = urllib.request.Request(base_web + "/api/runtime/autostart", data=b"{}",
                                                 headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=5):
                    pass
            except Exception as exc:
                _log(f"Model autostart request failed: {exc}")
        import threading
        threading.Thread(target=start_existing_model, daemon=True, name="model-autostart").start()
    if not (webapp_proc is not None and not smoke):
        _log(f"Web UI ready: {url}")

    # 3) Closing the window stops its services and releases GPU memory.
    cleaned = {"done": False}

    def cleanup() -> None:
        if cleaned["done"]:
            return
        cleaned["done"] = True
        _log("Shutting down: Web UI ...")
        if webapp_proc is not None:
            _kill_tree(webapp_proc.pid)
        _log("Stopping llama-server (freeing VRAM) ...")
        subprocess.call([str(VENV_PY), "scripts/server.py", "stop"],
                        cwd=str(ROOT), creationflags=0x08000000)
        _log("Done - VRAM freed.")

    atexit.register(cleanup)

    if smoke:
        try:
            _check_workspace_api(base_web)
            _log("SMOKE: workspace and selected conversation opened.")
        except Exception as exc:
            _log(f"SMOKE: workspace check failed: {exc}")
            cleanup()
            return 1
        # Wait for model startup, then clean up to test the entire lifecycle.
        _log("SMOKE: waiting for the model (autostart) ...")
        for _ in range(90):
            if _http_ok(f"{base_srv}/health"):
                break
            time.sleep(1)
        ok = _http_ok(f"{base_srv}/health")
        _log(f"SMOKE: model {'RUNNING' if ok else 'NOT RUNNING (timeout)'} - exiting.")
        cleanup()
        return 0 if ok else 1

    # 4) Native desktop window.
    _close_splash()
    try:
        import webview
        webview.create_window(f"Marvin v{APP_VERSION}", url,
                               width=1440, height=920, min_size=(960, 640),
                               background_color="#0b0e14")
        _log(f"Window opened: {url} (model may still be loading in the background)")
        webview.start(_focus_window)
    except ImportError:
        import webbrowser
        _log(f"pywebview missing - opening browser: {url}")
        webbrowser.open(url)
        try:
            input("[APP] Press Enter to quit (the server will stop)...\n")
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
        _alert(t("The app crashed – details in runtime\\launcher.log"))
        raise SystemExit(1)
