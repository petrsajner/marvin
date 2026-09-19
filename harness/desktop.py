"""Find, focus and capture one window on the desktop.

Computer mode could only see the whole primary monitor and could only send keys
to whatever happened to be in front. That is how a test of a running game ended
up photographing a browser: the screenshot was of the screen, not of the game.

Everything here is plain Win32 through ctypes, so it adds no dependency.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

SW_RESTORE = 9
PW_RENDERFULLCONTENT = 0x00000002     # Include layers a plain PrintWindow leaves out.
DWMWA_CLOAKED = 14                    # Windows keeps invisible shells around; skip them.
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def supported() -> bool:
    return sys.platform == "win32"


def _cloaked(hwnd: int) -> bool:
    value = wintypes.DWORD()
    try:
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        return False
    return result == 0 and bool(value.value)


def _process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    try:
        import psutil
        return psutil.Process(pid.value).name()
    except Exception:
        return ""


def windows() -> list[dict]:
    """Every visible titled top-level window, with where it is and how big."""
    if not supported():
        return []
    user32 = ctypes.windll.user32
    found: list[dict] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _param):
        if not user32.IsWindowVisible(hwnd) or _cloaked(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        minimized = bool(user32.IsIconic(hwnd))
        if not minimized and (width <= 1 or height <= 1):
            return True
        found.append({
            "handle": int(hwnd), "title": buffer.value, "process": _process_name(hwnd),
            "x": rect.left, "y": rect.top, "width": width, "height": height,
            "minimized": minimized,
            "foreground": int(hwnd) == int(user32.GetForegroundWindow()),
        })
        return True

    user32.EnumWindows(proto(visit), 0)
    return found


def find(query: str) -> dict | None:
    """Match a window the way a person names one: by what the title says."""
    wanted = (query or "").strip().lower()
    if not wanted:
        return None
    candidates = windows()
    for test in (lambda title: title == wanted,
                 lambda title: title.startswith(wanted),
                 lambda title: wanted in title):
        for window in candidates:
            if test(window["title"].lower()):
                return window
    for window in candidates:
        if wanted in (window["process"] or "").lower():
            return window
    return None


def focus(handle: int) -> tuple[bool, str]:
    """Bring a window forward, and say honestly whether it worked.

    Windows refuses SetForegroundWindow to a process that does not already own the
    foreground, so the documented escapes are tried in turn and the result is
    verified rather than assumed."""
    if not supported():
        return False, "not supported on this platform"
    user32 = ctypes.windll.user32
    hwnd = wintypes.HWND(handle)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    if int(user32.GetForegroundWindow()) == handle:
        return True, "SetForegroundWindow"
    try:
        user32.SwitchToThisWindow(hwnd, True)
        if int(user32.GetForegroundWindow()) == handle:
            return True, "SwitchToThisWindow"
    except (AttributeError, OSError):
        pass
    # Attaching to the thread that owns the foreground lifts the restriction.
    foreground = user32.GetForegroundWindow()
    current = ctypes.windll.kernel32.GetCurrentThreadId()
    owner = user32.GetWindowThreadProcessId(foreground, None)
    attached = bool(user32.AttachThreadInput(current, owner, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current, owner, False)
    if int(user32.GetForegroundWindow()) == handle:
        return True, "AttachThreadInput"
    return False, "the system kept the current window in front"


def capture(handle: int):
    """Photograph one window where it stands, covered or not.

    Returns a PIL image, or None when the window renders through the GPU in a way
    that gives back nothing - a plain colour is treated as nothing, because that
    is what a failed PrintWindow looks like."""
    if not supported():
        return None
    from PIL import Image
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = wintypes.HWND(handle)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT):
            return None
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height          # Top-down, so no vertical flip.
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer,
                               ctypes.byref(info), DIB_RGB_COLORS):
            return None
        image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
        image = image.convert("RGB")
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
    low, high = image.convert("L").getextrema()
    if low == high:
        return None                                 # One flat colour is a failure.
    return image
