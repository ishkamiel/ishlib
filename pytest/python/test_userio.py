#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import sys
import os
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.userio import (
    getch,
    normalise_str,
    prompt_bool,
    prompt_choice,
    prompt_yes_no_always,
)


class TestNormaliseStr(unittest.TestCase):
    def test_lowercase(self):
        assert normalise_str("MyStuff") == "mystuff"

    def test_keeps_alphanumeric(self):
        assert normalise_str("abc123") == "abc123"

    def test_keeps_dash(self):
        assert normalise_str("hello-world") == "hello-world"

    def test_keeps_underscore(self):
        assert normalise_str("foo_bar") == "foo_bar"

    def test_keeps_plus(self):
        assert normalise_str("a+b") == "a+b"

    def test_strips_spaces(self):
        assert normalise_str("build tools") == "buildtools"

    def test_strips_punctuation(self):
        assert normalise_str("foo!bar?") == "foobar"

    def test_empty(self):
        assert normalise_str("") == ""


class TestPromptChoiceNonInteractive(unittest.TestCase):
    """Tests that run without a tty (non-interactive path)."""

    def test_returns_default_when_set(self):
        with patch("sys.stdin.isatty", return_value=False):
            result = prompt_choice("Pick", ["min", "def", "personal"], default="def")
        assert result == "def"

    def test_returns_first_when_no_default(self):
        with patch("sys.stdin.isatty", return_value=False):
            result = prompt_choice("Pick", ["min", "def", "personal"])
        assert result == "min"

    def test_raises_on_empty_values(self):
        with self.assertRaises(ValueError):
            prompt_choice("Pick", [])


class TestPromptChoiceInteractive(unittest.TestCase):
    """Tests that simulate interactive input."""

    def _run_choice(self, values, input_str, default=None):
        with patch("sys.stdin.isatty", return_value=True):
            with patch("sys.stdin.readline", return_value=input_str + "\n"):
                with patch("sys.stdout.write"), patch("sys.stdout.flush"):
                    return prompt_choice("Pick", values, default=default)

    def test_exact_match(self):
        result = self._run_choice(["min", "def", "personal"], "def")
        assert result == "def"

    def test_case_insensitive_match(self):
        result = self._run_choice(["Min", "Def", "Personal"], "DEF")
        assert result == "Def"

    def test_enter_uses_default(self):
        with patch("sys.stdin.isatty", return_value=True):
            with patch("sys.stdin.readline", return_value="\n"):
                with patch("sys.stdout.write"), patch("sys.stdout.flush"):
                    result = prompt_choice("Pick", ["min", "def", "personal"], default="personal")
        assert result == "personal"

    def test_enter_without_default_uses_first(self):
        with patch("sys.stdin.isatty", return_value=True):
            with patch("sys.stdin.readline", return_value="\n"):
                with patch("sys.stdout.write"), patch("sys.stdout.flush"):
                    result = prompt_choice("Pick", ["min", "def", "personal"])
        assert result == "min"

    def test_invalid_then_valid(self):
        """Simulate bad input followed by a valid choice."""
        responses = iter(["bogus\n", "def\n"])
        with patch("sys.stdin.isatty", return_value=True):
            with patch("sys.stdin.readline", side_effect=responses):
                with patch("sys.stdout.write"), patch("sys.stdout.flush"):
                    result = prompt_choice("Pick", ["min", "def", "personal"])
        assert result == "def"

    def test_preserves_original_casing(self):
        """Return spec's casing, not the user's input casing."""
        result = self._run_choice(["MyStuff", "Other"], "MYSTUFF")
        assert result == "MyStuff"


class TestGetchCtrlC(unittest.TestCase):
    """getch() must raise KeyboardInterrupt on Ctrl-C (\x03)."""

    @unittest.skipIf(sys.platform == "win32", "POSIX-only test")
    def test_posix_ctrl_c_raises(self):
        """When stdin delivers \\x03, getch raises KeyboardInterrupt."""
        with patch("sys.stdin.fileno", return_value=0), \
             patch("termios.tcgetattr", return_value=[]), \
             patch("termios.tcsetattr"), \
             patch("tty.setcbreak"), \
             patch("sys.stdin.read", return_value="\x03"):
            with self.assertRaises(KeyboardInterrupt):
                getch()

    @unittest.skipIf(sys.platform == "win32", "POSIX-only test")
    def test_posix_normal_char_returned(self):
        """Normal characters are returned unchanged."""
        with patch("sys.stdin.fileno", return_value=0), \
             patch("termios.tcgetattr", return_value=[]), \
             patch("termios.tcsetattr"), \
             patch("tty.setcbreak"), \
             patch("sys.stdin.read", return_value="y"):
            assert getch() == "y"


class TestPromptYesNoAlwaysCtrlC(unittest.TestCase):
    """prompt_yes_no_always must propagate KeyboardInterrupt from getch."""

    def test_ctrl_c_propagates(self):
        with patch("sys.stdin.isatty", return_value=True):
            with patch("pyishlib.userio.getch", side_effect=KeyboardInterrupt):
                with patch("sys.stdout.write"), patch("sys.stdout.flush"):
                    with self.assertRaises(KeyboardInterrupt):
                        prompt_yes_no_always("Run sudo?")


class TestPromptBoolCtrlC(unittest.TestCase):
    """prompt_bool must propagate KeyboardInterrupt from getch."""

    def test_ctrl_c_propagates(self):
        with patch("sys.stdin.isatty", return_value=True):
            with patch("pyishlib.userio.getch", side_effect=KeyboardInterrupt):
                with patch("sys.stdout.write"), patch("sys.stdout.flush"):
                    with self.assertRaises(KeyboardInterrupt):
                        prompt_bool("Continue?")


if __name__ == "__main__":
    unittest.main()
