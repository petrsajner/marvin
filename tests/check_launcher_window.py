"""Check startup focus with real WinForms windows, without starting a model."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from launcher.launcher_app import _focus_window
import webview


def main():
    result = {}
    main_window = webview.create_window("Marvin launcher verification",
        html="<h1>Launcher verification</h1><p>Checking that helper windows stay hidden.</p>",
        width=640, height=360)
    helper = webview.create_window("GDI+ Window (Marvin.exe)", html="helper", hidden=True)
    unrelated = webview.create_window("Marvin unrelated window", html="unrelated", hidden=True)

    def verify(window):
        try:
            assert window is main_window, "The startup callback received the wrong window"
            deadline = time.monotonic() + 20
            while not all(window.native is not None for window in (main_window, helper, unrelated)):
                if time.monotonic() > deadline:
                    raise TimeoutError("Native windows did not initialize")
                time.sleep(.1)
            assert not helper.native.Visible and not unrelated.native.Visible
            _focus_window(window)
            assert main_window.native.Visible
            assert not helper.native.Visible, "The hidden graphics helper was exposed"
            assert not unrelated.native.Visible, "An unrelated window was exposed"
            result["ok"] = True
            print("PASS: real main window restored; graphics helper and unrelated window remain hidden")
        except Exception as exc:
            result["error"] = str(exc)
            print(f"FAIL: {type(exc).__name__}: {exc}")
        finally:
            for window in (unrelated, helper, main_window):
                window.destroy()

    webview.start(verify, main_window)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
