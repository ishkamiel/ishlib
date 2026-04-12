#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.dotfile_context import DotfileContext


class TestDotfileContextPromptChoice(unittest.TestCase):
    VALUES = ["min", "def", "personal"]

    def test_returns_stored_valid_value(self):
        ctx = DotfileContext({"machineType": "def"})
        result = ctx.prompt_choice("machineType", "Pick", self.VALUES, "def")
        assert result == "def"

    def test_stored_value_case_insensitive(self):
        """A stored value that normalises to a valid choice is accepted as-is."""
        ctx = DotfileContext({"machineType": "Personal"})
        result = ctx.prompt_choice("machineType", "Pick", self.VALUES, "def")
        assert result == "Personal"

    def test_invalid_stored_value_prompts(self):
        ctx = DotfileContext({"machineType": "bogus"})
        with patch("sys.stdin.isatty", return_value=False):
            result = ctx.prompt_choice("machineType", "Pick", self.VALUES, "def")
        assert result == "def"

    def test_missing_value_prompts(self):
        ctx = DotfileContext()
        with patch("sys.stdin.isatty", return_value=False):
            result = ctx.prompt_choice("machineType", "Pick", self.VALUES, "def")
        assert result == "def"

    def test_result_stored_in_vars(self):
        ctx = DotfileContext()
        with patch("sys.stdin.isatty", return_value=False):
            ctx.prompt_choice("machineType", "Pick", self.VALUES, "min")
        assert ctx.get("machineType") == "min"


if __name__ == "__main__":
    unittest.main()
