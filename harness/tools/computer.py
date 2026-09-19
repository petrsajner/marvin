"""Computer-use tools for screenshots and graphical application actions.

The model uses pixels in the image it receives, which may be downscaled. Tools convert them to screen coordinates using the most recent screenshot.

The pyautogui failsafe stays enabled: moving the pointer to the upper-left corner interrupts an action."""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

from harness.safety import Risk
from harness.tools.base import AgentContext, Tool

# Shared last-screenshot geometry for coordinate conversion.
_last_shot: dict = {"screen_w": 0, "screen_h": 0, "img_w": 0, "img_h": 0, "origin_x": 0, "origin_y": 0}


def _to_screen(x: float, y: float) -> tuple[int, int]:
    """Convert image coordinates to physical screen coordinates."""
    if _last_shot["img_w"] == 0:
        return round(x), round(y)  # Assume a 1:1 mapping before the first screenshot.
    sx = _last_shot["origin_x"] + x * (_last_shot["screen_w"] / _last_shot["img_w"])
    sy = _last_shot["origin_y"] + y * (_last_shot["screen_h"] / _last_shot["img_h"])
    return round(sx), round(sy)


def _pyautogui():
    import pyautogui
    pyautogui.FAILSAFE = True  # Keep the corner-triggered failsafe enabled.
    pyautogui.FAILSAFE_POINTS = [(0, 0)]
    return pyautogui


# Virtual-key codes for the names the model uses. pyautogui presses keys with
# keybd_event(vk, 0, ...) - the second argument is the scancode and it passes
# zero. SDL and DirectInput identify keys by scancode, so a game receives
# SDL_SCANCODE_UNKNOWN and drops the event: synthetic keys never arrive. The
# scancode is looked up from the virtual key and sent through SendInput instead.
_VK: dict[str, int] = {
    "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
    "right": 0x27, "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
    "win": 0x5B, "capslock": 0x14, "printscreen": 0x2C, "pause": 0x13,
    "numlock": 0x90, "scrolllock": 0x91, "apps": 0x5D,
}
_VK.update({f"f{index}": 0x6F + index for index in range(1, 13)})
_VK.update({letter: ord(letter.upper()) for letter in "abcdefghijklmnopqrstuvwxyz"})
_VK.update({digit: ord(digit) for digit in "0123456789"})
# Keys the keyboard reports with the extended prefix.
_EXTENDED = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27,
             0x5B, 0x5D, 0x2C, 0x90}


def _scancode(vk: int) -> int:
    """The hardware scancode for a virtual key, or 0 when there is none.

    A few keys - Pause among them - have no single scancode, and sending zero is
    the very thing that makes a game ignore the event, so they take the old path."""
    if sys.platform != "win32":
        return 0
    import ctypes
    return int(ctypes.windll.user32.MapVirtualKeyW(vk, 0))


def _failsafe_triggered() -> bool:
    """The upper-left corner aborts, exactly as it does for pyautogui.

    SendInput bypasses pyautogui entirely, so the promise has to be kept here."""
    import ctypes
    from ctypes import wintypes
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x <= 0 and point.y <= 0


def _send_scancodes(parts: list[str], hold: float) -> int:
    """Press a combination with real scancodes; returns the events accepted."""
    import ctypes
    from ctypes import wintypes

    INPUT_KEYBOARD, KEYEVENTF_EXTENDEDKEY = 1, 0x0001
    KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0002, 0x0008
    MAPVK_VK_TO_VSC = 0
    user32 = ctypes.windll.user32

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]

    class INPUT(ctypes.Structure):
        class _VALUE(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("raw", ctypes.c_byte * 32)]
        _anonymous_ = ("value",)
        _fields_ = [("type", wintypes.DWORD), ("value", _VALUE)]

    def event(vk: int, release: bool) -> INPUT:
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if release else 0)
        if vk in _EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        item = INPUT(type=INPUT_KEYBOARD)
        # With KEYEVENTF_SCANCODE the virtual key must be zero and the scancode
        # carries the key, which is the part SDL actually reads.
        item.ki = KEYBDINPUT(wVk=0, wScan=user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC),
                             dwFlags=flags, time=0, dwExtraInfo=None)
        return item

    codes = [_VK[name] for name in parts]
    accepted = 0
    press = (INPUT * len(codes))(*[event(code, False) for code in codes])
    accepted += user32.SendInput(len(codes), ctypes.byref(press), ctypes.sizeof(INPUT))
    # Games poll once a frame, so a key pressed and released in the same batch can
    # pass between two polls and be missed entirely.
    if hold > 0:
        time.sleep(hold)
    release = (INPUT * len(codes))(*[event(code, True) for code in reversed(codes)])
    accepted += user32.SendInput(len(codes), ctypes.byref(release), ctypes.sizeof(INPUT))
    return accepted


class ScreenshotTool(Tool):
    name = "screenshot"
    description = ("Capture the screen, or one window by name. The image is attached to the conversation "
                   "so you can see it. Returns real size and image size - use IMAGE pixel "
                   "coordinates for click/move/scroll tools. ALWAYS call this first, before any GUI action. "
                   "Pass 'window' to photograph a program that is open but covered by something else, which "
                   "is the reliable way to watch a game or a program you started: a plain screenshot shows "
                   "whatever happens to be in front, which may not be the program you are testing. "
                   "Use list_windows to learn the names.")
    parameters = {"window": {"type": "string",
                             "description": "Part of a window title, for one window instead of the screen"}}

    def run(self, ctx: AgentContext, window: str = "") -> str:
        import mss
        from PIL import Image

        ccfg = ctx.cfg.computer
        origin = (0, 0)
        note = ""
        if window:
            from harness import desktop
            target = desktop.find(window)
            if target is None:
                open_titles = ", ".join(repr(w["title"]) for w in desktop.windows()[:12])
                return (f"ERROR: no open window matches {window!r}. "
                        f"Currently open: {open_titles or 'nothing with a title'}")
            if target["minimized"]:
                return (f"ERROR: the window {target['title']!r} is minimised and has nothing to show. "
                        f"Use focus_window to restore it first.")
            img = desktop.capture(target["handle"])
            if img is None:
                # Some GPU-drawn windows hand back nothing. Bringing the window
                # forward and grabbing its rectangle always works, at the cost of
                # taking the foreground away from whatever the user was doing.
                ok, how = desktop.focus(target["handle"])
                if not ok:
                    return (f"ERROR: {target['title']!r} could not be photographed where it stands, "
                            f"and it could not be brought forward either ({how}).")
                time.sleep(0.25)
                target = desktop.find(window) or target
                with mss.mss() as sct:
                    shot = sct.grab({"left": target["x"], "top": target["y"],
                                     "width": target["width"], "height": target["height"]})
                    img = Image.frombytes("RGB", shot.size, shot.rgb)
                note = " The window had to be brought to the front to be photographed."
            origin = (target["x"], target["y"])
            label = f"window {target['title']!r}"
        else:
            with mss.mss() as sct:
                mon = sct.monitors[1]  # Primary monitor.
                shot = sct.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.rgb)
            label = "screen"

        screen_w, screen_h = img.size
        max_edge = int(ccfg.get("screenshot_max_edge", 1920))
        if max(img.size) > max_edge:
            scale = max_edge / max(img.size)
            img = img.resize((round(img.size[0] * scale), round(img.size[1] * scale)), Image.LANCZOS)
        if ccfg.get("screenshot_grayscale"):
            img = img.convert("L")

        ctx.session.img_dir.mkdir(parents=True, exist_ok=True)
        path = ctx.session.img_dir / f"shot-{uuid.uuid4().hex[:8]}.png"
        img.save(path, "PNG", optimize=True)

        _last_shot.update(
            screen_w=screen_w, screen_h=screen_h,
            img_w=img.size[0], img_h=img.size[1],
            origin_x=origin[0], origin_y=origin[1],
        )
        ctx.pending_images.append(path)
        return (f"Screenshot captured of the {label}: image {img.size[0]}x{img.size[1]} px "
                f"(real {screen_w}x{screen_h}). Coordinates for GUI tools are in IMAGE pixel space. "
                f"The screenshot is attached to your next message.{note}")


class ListWindowsTool(Tool):
    name = "list_windows"
    description = ("List the open windows with their titles, programs, positions and sizes. "
                   "Use it to find the program you are testing before taking its screenshot or "
                   "sending it keys - the screen shows whatever is in front, which is often "
                   "something else entirely.")
    parameters = {}
    risk = Risk.SAFE

    def run(self, ctx: AgentContext) -> str:
        from harness import desktop
        found = desktop.windows()
        if not found:
            return "No open windows with a title."
        lines = []
        for item in found:
            marks = []
            if item["foreground"]:
                marks.append("in front")
            if item["minimized"]:
                marks.append("minimised")
            lines.append("%-44s %-18s %4d,%-4d %dx%d%s" % (
                item["title"][:44], item["process"][:18], item["x"], item["y"],
                item["width"], item["height"],
                "  (" + ", ".join(marks) + ")" if marks else ""))
        return "Open windows:\n" + "\n".join(lines)


class FocusWindowTool(Tool):
    name = "focus_window"
    description = ("Bring a window to the front by part of its title, restoring it if it is "
                   "minimised. Keys always go to the window in front, so call this before "
                   "pressing keys for a program you started. Screenshots do not need it: "
                   "screenshot(window=...) can photograph a covered window where it stands.")
    parameters = {"title": {"type": "string", "description": "Part of the window title"}}
    required = ["title"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, title: str) -> str:
        from harness import desktop
        target = desktop.find(title)
        if target is None:
            open_titles = ", ".join(repr(w["title"]) for w in desktop.windows()[:12])
            return (f"ERROR: no open window matches {title!r}. "
                    f"Currently open: {open_titles or 'nothing with a title'}")
        ok, how = desktop.focus(target["handle"])
        if not ok:
            return (f"ERROR: {target['title']!r} could not be brought to the front ({how}). "
                    f"You can still photograph it with screenshot(window=...).")
        return f"{target['title']!r} is now in front, and will receive keys ({how})."


class ClickTool(Tool):
    name = "click"
    description = "Click the mouse at IMAGE coordinates (from the latest screenshot)."
    parameters = {
        "x": {"type": "integer", "description": "X in image pixels"},
        "y": {"type": "integer", "description": "Y in image pixels"},
        "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button (default left)"},
        "clicks": {"type": "integer", "description": "Number of clicks (2 = double-click, default 1)"},
    }
    required = ["x", "y"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, x: int, y: int, button: str = "left", clicks: int = 1) -> str:
        pag = _pyautogui()
        pag.PAUSE = float(ctx.cfg.computer.get("pause_between_actions", 0.15))
        sx, sy = _to_screen(x, y)
        pag.click(sx, sy, clicks=clicks, button=button, duration=0.2)
        return f"Clicked {button} x{clicks} at image ({x},{y}) -> screen ({sx},{sy})"


class TypeTextTool(Tool):
    name = "type_text"
    description = ("Type text at the current cursor position. Handles unicode (Czech diacritics etc.) "
                   "via clipboard paste automatically. Click the target field first! "
                   "Game windows usually ignore this; use press_key for them.")
    parameters = {"text": {"type": "string", "description": "Text to type"}}
    required = ["text"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, text: str) -> str:
        pag = _pyautogui()
        pag.PAUSE = float(ctx.cfg.computer.get("pause_between_actions", 0.15))
        try:
            text.encode("ascii")
            ascii_ok = True
        except UnicodeEncodeError:
            ascii_ok = False
        if ascii_ok and len(text) < 200:
            pag.write(text, interval=0.02)
            return f"Typed {len(text)} chars (keyboard)"
        # Paste long or non-ASCII text through the clipboard.
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.1)
        pag.hotkey("ctrl", "v")
        return f"Pasted {len(text)} chars via clipboard"


class PressKeyTool(Tool):
    name = "press_key"
    description = (
        "Press a key or key combination. Examples: 'enter', 'esc', 'tab', 'win', 'ctrl+s', "
        "'ctrl+shift+t', 'alt+f4', 'win+d'. Use lowercase key names. "
        "Sends real hardware scancodes, which games and other SDL/DirectInput windows "
        "require - they ignore keys sent without one. If a game still does not react, "
        "raise 'hold' so the key stays down across a frame, and only then try "
        "method='virtual', which some accessibility-aware windows prefer.")
    parameters = {
        "keys": {"type": "string", "description": "Key or combo, joined with '+'"},
        "hold": {"type": "number",
                 "description": "Seconds to hold the key down (default 0.05; raise for games)"},
        "method": {"type": "string", "enum": ["auto", "scancode", "virtual"],
                   "description": "auto and scancode send hardware scancodes; virtual is the old path"},
    }
    required = ["keys"]
    risk = Risk.WRITE

    KEY_ALIASES = {"windows": "win", "super": "win", "return": "enter", "del": "delete", "space": "space"}

    def run(self, ctx: AgentContext, keys: str, hold: float = 0.05,
            method: str = "auto") -> str:
        parts = [self.KEY_ALIASES.get(k.strip().lower(), k.strip().lower())
                 for k in keys.split("+") if k.strip()]
        if not parts:
            return "ERROR: empty key combo"
        combo = "+".join(parts)
        unknown = [name for name in parts
                   if name not in _VK or not _scancode(_VK[name])]
        if method in ("auto", "scancode") and sys.platform == "win32" and not unknown:
            if ctx.cfg.computer.get("failsafe", True) and _failsafe_triggered():
                return "ERROR: failsafe - pointer in the upper-left corner, nothing sent"
            accepted = _send_scancodes(parts, max(0.0, float(hold)))
            if accepted == 2 * len(parts):
                return f"Pressed: {combo} (hardware scancodes, held {hold:g}s)"
            if method == "scancode":
                return (f"ERROR: the system accepted {accepted} of {2 * len(parts)} key "
                        f"events for {combo}")
            # Fall through to the older path rather than leaving the key unpressed.
        elif method == "scancode":
            reason = (f"no hardware scancode for: {unknown}" if unknown
                      else "not supported on this platform")
            return f"ERROR: cannot send scancodes for {combo} ({reason})"
        pag = _pyautogui()
        pag.PAUSE = float(ctx.cfg.computer.get("pause_between_actions", 0.15))
        if len(parts) == 1:
            pag.press(parts[0])
        else:
            pag.hotkey(*parts)
        return f"Pressed: {combo} (virtual keys; a game window may not see these)"


class ScrollTool(Tool):
    name = "scroll"
    description = "Scroll the mouse wheel. Positive amount scrolls UP, negative scrolls DOWN. Optional x,y = image coordinates to scroll at."
    parameters = {
        "amount": {"type": "integer", "description": "Scroll amount in 'clicks' (positive=up, negative=down)"},
        "x": {"type": "integer", "description": "X in image pixels (optional)"},
        "y": {"type": "integer", "description": "Y in image pixels (optional)"},
    }
    required = ["amount"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, amount: int, x: int | None = None, y: int | None = None) -> str:
        pag = _pyautogui()
        pag.PAUSE = float(ctx.cfg.computer.get("pause_between_actions", 0.15))
        if x is not None and y is not None:
            sx, sy = _to_screen(x, y)
            pag.moveTo(sx, sy)
        pag.scroll(amount)
        return f"Scrolled {amount:+d}"


class MoveMouseTool(Tool):
    name = "move_mouse"
    description = "Move the mouse pointer to IMAGE coordinates (useful for hover tooltips)."
    parameters = {
        "x": {"type": "integer", "description": "X in image pixels"},
        "y": {"type": "integer", "description": "Y in image pixels"},
    }
    required = ["x", "y"]
    risk = Risk.WRITE

    def run(self, ctx: AgentContext, x: int, y: int) -> str:
        pag = _pyautogui()
        pag.PAUSE = float(ctx.cfg.computer.get("pause_between_actions", 0.15))
        sx, sy = _to_screen(x, y)
        pag.moveTo(sx, sy, duration=0.2)
        return f"Mouse moved to image ({x},{y}) -> screen ({sx},{sy})"


class GetScreenSizeTool(Tool):
    name = "get_screen_info"
    description = "Get screen resolution and info about the last screenshot (coordinate mapping)."
    parameters = {}

    def run(self, ctx: AgentContext) -> str:
        pag = _pyautogui()
        w, h = pag.size()
        if _last_shot["img_w"]:
            return (f"Screen: {w}x{h}px. Last screenshot image: {_last_shot['img_w']}x{_last_shot['img_h']}px "
                    f"(scale {_last_shot['screen_w'] / _last_shot['img_w']:.2f}x). Use IMAGE pixel coordinates.")
        return f"Screen: {w}x{h}px. No screenshot taken yet - call screenshot() first."


def desktop_supported() -> bool:
    from harness import desktop
    return desktop.supported()


def register_computer_tools(registry) -> None:
    registry.register(ScreenshotTool())
    registry.register(ClickTool())
    registry.register(TypeTextTool())
    registry.register(PressKeyTool())
    registry.register(ScrollTool())
    registry.register(MoveMouseTool())
    registry.register(GetScreenSizeTool())
    if desktop_supported():
        registry.register(ListWindowsTool())
        registry.register(FocusWindowTool())
