"""Seeing and choosing one window instead of whatever happens to be in front.

Computer mode photographed the screen and sent keys to the foreground, so a test
of a running game produced a picture of a browser. These cover the parts that can
be checked without a second program on screen; capturing a real covered window is
measured in docs/design/ and by running the harness against a live one.
"""
import sys
import unittest
from unittest.mock import patch

from harness import desktop
from harness.agent import build_registry
from harness.config import load_config
from harness.prompts import system_prompt
from harness.tools import computer
from harness.tools.base import AgentContext
from harness.tools.computer import FocusWindowTool, ListWindowsTool, ScreenshotTool

OPEN = [
    {"handle": 1, "title": "Space Invaders", "process": "python.exe",
     "x": 200, "y": 150, "width": 400, "height": 300, "minimized": False, "foreground": False},
    {"handle": 2, "title": "Space Invaders - notes.txt - Notepad", "process": "notepad.exe",
     "x": 0, "y": 0, "width": 800, "height": 600, "minimized": False, "foreground": True},
    {"handle": 3, "title": "Inbox - Outlook", "process": "outlook.exe",
     "x": 10, "y": 10, "width": 900, "height": 700, "minimized": True, "foreground": False},
]


def context():
    return AgentContext(cfg=load_config(), session=None)


class FindTests(unittest.TestCase):
    def test_an_exact_title_wins_over_a_longer_one_containing_it(self):
        """'Space Invaders' must find the game, not a text editor mentioning it."""
        with patch.object(desktop, "windows", return_value=OPEN):
            self.assertEqual(desktop.find("Space Invaders")["handle"], 1)
            self.assertEqual(desktop.find("space invaders")["handle"], 1)

    def test_a_fragment_still_matches(self):
        with patch.object(desktop, "windows", return_value=OPEN):
            self.assertEqual(desktop.find("Outlook")["handle"], 3)
            self.assertEqual(desktop.find("notes.txt")["handle"], 2)

    def test_the_program_name_is_a_last_resort(self):
        with patch.object(desktop, "windows", return_value=OPEN):
            self.assertEqual(desktop.find("notepad.exe")["handle"], 2)

    def test_nothing_matches_nothing(self):
        with patch.object(desktop, "windows", return_value=OPEN):
            self.assertIsNone(desktop.find("Arkanoid"))
            self.assertIsNone(desktop.find(""))


class RealDesktopTests(unittest.TestCase):
    def setUp(self):
        if not desktop.supported():
            self.skipTest("windows are a Windows concern")

    def test_the_open_windows_are_described_completely(self):
        found = desktop.windows()
        self.assertTrue(found, "a desktop session always has at least one titled window")
        for window in found:
            self.assertEqual(
                set(window),
                {"handle", "title", "process", "x", "y", "width", "height",
                 "minimized", "foreground"})
            self.assertTrue(window["title"])
        self.assertLessEqual(sum(1 for w in found if w["foreground"]), 1)

    def test_a_handle_that_is_not_a_window_fails_quietly(self):
        self.assertIsNone(desktop.capture(1))
        ok, reason = desktop.focus(1)
        self.assertFalse(ok)
        self.assertTrue(reason)


class ToolTests(unittest.TestCase):
    def test_an_unknown_window_lists_what_is_actually_open(self):
        with patch.object(desktop, "windows", return_value=OPEN):
            answer = ScreenshotTool().run(context(), window="Arkanoid")
        self.assertTrue(answer.startswith("ERROR"))
        self.assertIn("Space Invaders", answer)

    def test_a_minimised_window_says_so_instead_of_returning_a_blank(self):
        with patch.object(desktop, "windows", return_value=OPEN):
            answer = ScreenshotTool().run(context(), window="Outlook")
        self.assertTrue(answer.startswith("ERROR"))
        self.assertIn("focus_window", answer)

    def test_window_coordinates_are_offset_so_clicks_land_in_the_window(self):
        class Image:
            size = (400, 300)
            width, height = 400, 300

            def save(self, *args, **kwargs):
                pass

            def convert(self, mode):
                return self

            def resize(self, size, filter):
                return self

        class Session:
            class img_dir:
                @staticmethod
                def mkdir(**kwargs):
                    pass

                def __truediv__(self, other):
                    return __import__("pathlib").Path(other)
            img_dir = img_dir()

        ctx = AgentContext(cfg=load_config(), session=Session())
        ctx.pending_images = []
        with patch.object(desktop, "windows", return_value=OPEN), \
                patch.object(desktop, "capture", return_value=Image()):
            answer = ScreenshotTool().run(ctx, window="Space Invaders")
        self.assertIn("Space Invaders", answer)
        self.assertEqual(computer._last_shot["origin_x"], 200)
        self.assertEqual(computer._last_shot["origin_y"], 150)
        # A click in the middle of the image lands in the middle of the window.
        self.assertEqual(computer._to_screen(200, 150), (400, 300))

    def test_the_list_names_the_program_and_marks_the_front_window(self):
        with patch.object(desktop, "windows", return_value=OPEN):
            answer = ListWindowsTool().run(context())
        self.assertIn("python.exe", answer)
        self.assertIn("in front", answer)
        self.assertIn("minimised", answer)

    def test_a_refused_focus_is_reported_rather_than_claimed(self):
        with patch.object(desktop, "windows", return_value=OPEN), \
                patch.object(desktop, "focus", return_value=(False, "the system said no")):
            answer = FocusWindowTool().run(context(), title="Space Invaders")
        self.assertTrue(answer.startswith("ERROR"))
        self.assertIn("the system said no", answer)

    def test_a_successful_focus_says_which_way_it_worked(self):
        with patch.object(desktop, "windows", return_value=OPEN), \
                patch.object(desktop, "focus", return_value=(True, "AttachThreadInput")):
            answer = FocusWindowTool().run(context(), title="Space Invaders")
        self.assertFalse(answer.startswith("ERROR"))
        self.assertIn("AttachThreadInput", answer)


class PromptTests(unittest.TestCase):
    """The model used to learn these tools by trying them one after another."""

    def test_computer_mode_is_told_about_every_tool_it_has(self):
        if sys.platform != "win32":
            self.skipTest("the window tools are only registered on Windows")
        prompt = system_prompt("computer", "computer")
        registry = build_registry("computer", "computer")
        gui = {"screenshot", "list_windows", "focus_window", "press_key", "type_text",
               "click", "move_mouse", "scroll", "get_screen_info"}
        self.assertTrue(gui <= set(registry._tools), "a GUI tool disappeared from the registry")
        for name in sorted(gui):
            self.assertIn(name, prompt, f"{name} is registered but not described to the model")

    def test_the_order_that_works_is_stated(self):
        prompt = system_prompt("computer", "computer")
        self.assertIn("list_windows", prompt)
        self.assertIn("keys follow the foreground", prompt)
        self.assertIn("covered", prompt)


if __name__ == "__main__":
    unittest.main()
