"""Startup focus must never restore hidden helper or unrelated windows."""
import ctypes
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from launcher import launcher_app


@unittest.skipUnless(sys.platform == "win32", "The desktop launcher uses Windows handles")
class LauncherFocusTests(unittest.TestCase):
    def native_window(self, handle):
        return SimpleNamespace(native=SimpleNamespace(
            Handle=SimpleNamespace(ToInt64=lambda: handle)))

    def test_only_the_created_window_is_restored(self):
        handle = 0x123456789
        user32 = Mock()
        user32.IsWindow.return_value = True
        with patch.object(ctypes.windll, "user32", user32), patch("time.sleep"):
            launcher_app._focus_window(self.native_window(handle))
        user32.ShowWindow.assert_called_once_with(handle, 9)
        user32.SetForegroundWindow.assert_called_once_with(handle)
        user32.BringWindowToTop.assert_called_once_with(handle)
        self.assertEqual([c.args[0] for c in user32.SetWindowPos.call_args_list], [handle, handle])
        user32.EnumWindows.assert_not_called()

    def test_focus_waits_for_the_native_handle(self):
        window = SimpleNamespace(native=None)
        user32 = Mock()
        user32.IsWindow.return_value = True
        def delay(seconds):
            if seconds == 1:
                window.native = self.native_window(42).native
        with patch.object(ctypes.windll, "user32", user32), patch("time.sleep", side_effect=delay) as sleep:
            launcher_app._focus_window(window)
        user32.ShowWindow.assert_called_once_with(42, 9)
        self.assertEqual(sleep.call_args_list, [call(2.0), call(1.0)])

    def test_missing_or_invalid_native_handle_never_restores_another_window(self):
        for window in (SimpleNamespace(native=None), self.native_window(0), self.native_window(42)):
            with self.subTest(window=window):
                user32 = Mock()
                user32.IsWindow.return_value = False
                with patch.object(ctypes.windll, "user32", user32), patch("time.sleep"):
                    launcher_app._focus_window(window)
                user32.ShowWindow.assert_not_called()
                user32.SetForegroundWindow.assert_not_called()
                user32.EnumWindows.assert_not_called()
