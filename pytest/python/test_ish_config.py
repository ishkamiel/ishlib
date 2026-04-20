# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :class:`pyishlib.ish_config.IshConfig`."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib import ish_config as ish_config_mod  # noqa: E402
from pyishlib.ish_config import IshConfig  # noqa: E402


class TestBootstrap(unittest.TestCase):
    """Cover IshConfig.bootstrap end-to-end."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "cfg.toml"
        self.prompts = [
            ("prefix", "branch prefix", "ishlib"),
            ("postfix", "branch postfix", "ishproject"),
        ]

    def test_existing_file_noop(self) -> None:
        self.config_path.write_text('[sec]\nprefix = "existing"\n', encoding="utf-8")
        before = self.config_path.read_text(encoding="utf-8")
        with patch.object(ish_config_mod, "prompt_string") as mock_prompt:
            IshConfig.bootstrap(self.config_path, section="sec", prompts=self.prompts)
        mock_prompt.assert_not_called()
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), before)

    def test_missing_file_noninteractive_noop(self) -> None:
        with patch.object(ish_config_mod, "prompt_string") as mock_prompt:
            IshConfig.bootstrap(
                self.config_path,
                section="sec",
                prompts=self.prompts,
                interactive=False,
            )
        mock_prompt.assert_not_called()
        self.assertFalse(self.config_path.is_file())

    def test_missing_file_interactive_writes(self) -> None:
        with patch.object(
            ish_config_mod, "prompt_string", side_effect=["a", "b"]
        ) as mock_prompt:
            IshConfig.bootstrap(
                self.config_path,
                section="sec",
                prompts=self.prompts,
                interactive=True,
            )
        self.assertEqual(mock_prompt.call_count, 2)
        self.assertTrue(self.config_path.is_file())
        text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("[sec]", text)
        self.assertIn('prefix = "a"', text)
        self.assertIn('postfix = "b"', text)

    def test_write_is_atomic(self) -> None:
        with patch.object(ish_config_mod, "prompt_string", side_effect=["a", "b"]):
            IshConfig.bootstrap(
                self.config_path,
                section="sec",
                prompts=self.prompts,
                interactive=True,
            )
        tmp = self.config_path.with_name(f".{self.config_path.name}.tmp")
        self.assertFalse(tmp.exists())

    def test_hazardous_input_round_trips(self) -> None:
        # Quote, backslash, newline, and a control char must survive a
        # write -> tomllib-load round trip.
        from pyishlib._compat import load_toml_file

        hazards = ['q"b\\k', "n\nl\tt"]
        with patch.object(ish_config_mod, "prompt_string", side_effect=hazards):
            IshConfig.bootstrap(
                self.config_path,
                section="sec",
                prompts=self.prompts,
                interactive=True,
            )
        data = load_toml_file(self.config_path, default={})
        self.assertEqual(data["sec"]["prefix"], hazards[0])
        self.assertEqual(data["sec"]["postfix"], hazards[1])

    def test_creates_parent_directory(self) -> None:
        nested = self.config_path.parent / "deep" / "nest" / "cfg.toml"
        with patch.object(ish_config_mod, "prompt_string", side_effect=["a", "b"]):
            IshConfig.bootstrap(
                nested,
                section="sec",
                prompts=self.prompts,
                interactive=True,
            )
        self.assertTrue(nested.is_file())


if __name__ == "__main__":
    unittest.main()
