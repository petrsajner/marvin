"""Key delivery for game windows.

pyautogui presses keys with keybd_event(vk, 0, ...), where the second argument is
the scancode. SDL and DirectInput identify keys by scancode, so a zero means the
window receives SDL_SCANCODE_UNKNOWN and drops the event - which is why a game
never reacted to anything the model pressed. These tests cover the decision and
the safety rules; whether a particular game reacts can only be seen by running one.
"""
import sys
import unittest
from unittest.mock import patch

from harness.config import load_config
from harness.tools import computer
from harness.tools.base import AgentContext
from harness.tools.computer import PressKeyTool, _VK, _scancode


def context():
    return AgentContext(cfg=load_config(), session=None)


class ScancodeTableTests(unittest.TestCase):
    def test_the_keys_a_game_needs_resolve_to_real_scancodes(self):
        """Set-1 scancodes, checked against the values a keyboard actually sends."""
        if sys.platform != "win32":
            self.skipTest("scancodes are a Windows concern")
        expected = {"esc": 0x01, "enter": 0x1C, "space": 0x39, "a": 0x1E,
                    "w": 0x11, "left": 0x4B, "right": 0x4D, "up": 0x48,
                    "down": 0x50, "f1": 0x3B, "ctrl": 0x1D, "shift": 0x2A}
        for name, code in expected.items():
            self.assertEqual(_scancode(_VK[name]), code, name)

    def test_arrows_and_navigation_are_marked_extended(self):
        for name in ("left", "right", "up", "down", "home", "end",
                     "pageup", "pagedown", "insert", "delete", "win"):
            self.assertIn(_VK[name], computer._EXTENDED, name)
        for name in ("a", "space", "enter", "shift", "f1"):
            self.assertNotIn(_VK[name], computer._EXTENDED, name)

    def test_a_key_without_a_scancode_is_not_sent_as_zero(self):
        """Sending zero is the bug; such a key has to take the other path."""
        if sys.platform != "win32":
            self.skipTest("scancodes are a Windows concern")
        without = [name for name, vk in _VK.items() if not _scancode(vk)]
        self.assertEqual(without, ["pause"], without)


class PressKeyTests(unittest.TestCase):
    def test_a_normal_press_goes_out_as_scancodes_and_is_held(self):
        sent = {}

        def record(parts, hold):
            sent["parts"], sent["hold"] = list(parts), hold
            return 2 * len(parts)

        with patch.object(computer, "_send_scancodes", side_effect=record), \
                patch.object(computer, "_failsafe_triggered", return_value=False):
            result = PressKeyTool().run(context(), keys="ctrl+s", hold=0.2)
        self.assertEqual(sent["parts"], ["ctrl", "s"])
        self.assertEqual(sent["hold"], 0.2)
        self.assertIn("scancode", result)

    def test_the_corner_failsafe_still_stops_it(self):
        """SendInput bypasses pyautogui, so the corner rule is enforced here."""
        with patch.object(computer, "_send_scancodes") as sender, \
                patch.object(computer, "_failsafe_triggered", return_value=True):
            result = PressKeyTool().run(context(), keys="enter")
        sender.assert_not_called()
        self.assertTrue(result.startswith("ERROR"))
        self.assertIn("failsafe", result)

    def test_a_partial_send_falls_back_instead_of_leaving_the_key_unpressed(self):
        with patch.object(computer, "_send_scancodes", return_value=0), \
                patch.object(computer, "_failsafe_triggered", return_value=False), \
                patch.object(computer, "_pyautogui") as pag:
            result = PressKeyTool().run(context(), keys="enter")
        pag.return_value.press.assert_called_once_with("enter")
        self.assertIn("virtual keys", result)

    def test_asking_for_scancodes_explicitly_reports_a_failure(self):
        with patch.object(computer, "_send_scancodes", return_value=0), \
                patch.object(computer, "_failsafe_triggered", return_value=False), \
                patch.object(computer, "_pyautogui") as pag:
            result = PressKeyTool().run(context(), keys="enter", method="scancode")
        pag.assert_not_called()
        self.assertTrue(result.startswith("ERROR"))

    def test_the_old_path_is_still_reachable_on_request(self):
        with patch.object(computer, "_send_scancodes") as sender, \
                patch.object(computer, "_pyautogui") as pag:
            result = PressKeyTool().run(context(), keys="alt+f4", method="virtual")
        sender.assert_not_called()
        pag.return_value.hotkey.assert_called_once_with("alt", "f4")
        self.assertIn("virtual keys", result)

    def test_an_unknown_key_name_is_refused_without_sending(self):
        with patch.object(computer, "_send_scancodes") as sender:
            result = PressKeyTool().run(context(), keys="dvorak", method="scancode")
        sender.assert_not_called()
        self.assertTrue(result.startswith("ERROR"))

    def test_an_empty_combination_is_refused(self):
        self.assertTrue(PressKeyTool().run(context(), keys="  +  ").startswith("ERROR"))


if __name__ == "__main__":
    unittest.main()
