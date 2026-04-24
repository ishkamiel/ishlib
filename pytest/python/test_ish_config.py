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


class TestIsExplicit(unittest.TestCase):
    """Cover :meth:`IshConfig.is_explicit`."""

    def test_false_when_args_none(self) -> None:
        cfg = IshConfig()
        self.assertFalse(cfg.is_explicit("verbose"))

    def test_false_when_attr_present_but_not_tracked(self) -> None:
        """Values from TOML / defaults are not 'explicit' even if readable."""
        from types import SimpleNamespace

        # No _ish_explicit attribute — simulates a plain Namespace or a
        # TOML-sourced conf masquerading as args.
        ns = SimpleNamespace(verbose=True)
        cfg = IshConfig(args=ns)
        self.assertFalse(cfg.is_explicit("verbose"))

    def test_true_when_dest_in_explicit_set(self) -> None:
        from types import SimpleNamespace

        ns = SimpleNamespace(verbose=True, _ish_explicit={"verbose"})
        cfg = IshConfig(args=ns)
        self.assertTrue(cfg.is_explicit("verbose"))
        self.assertFalse(cfg.is_explicit("dry_run"))

    def test_parser_with_explicit_actions_populates_set(self) -> None:
        """End-to-end: wrapping actions via _explicit_action records dests."""
        import argparse

        from pyishlib.cli_base import (
            _ExplicitStore,
            _ExplicitStoreTrue,
        )

        parser = argparse.ArgumentParser()
        parser.add_argument("-v", "--verbose", action=_ExplicitStoreTrue, default=False)
        parser.add_argument("-n", "--dry-run", action=_ExplicitStoreTrue, default=False)
        parser.add_argument("--log-file", action=_ExplicitStore, default=None)

        # Nothing typed
        args = parser.parse_args([])
        cfg = IshConfig(args=args)
        self.assertFalse(cfg.is_explicit("verbose"))
        self.assertFalse(cfg.is_explicit("dry_run"))
        self.assertFalse(cfg.is_explicit("log_file"))

        # User typed -v and --log-file
        args = parser.parse_args(["-v", "--log-file", "/tmp/x.log"])
        cfg = IshConfig(args=args)
        self.assertTrue(cfg.is_explicit("verbose"))
        self.assertFalse(cfg.is_explicit("dry_run"))
        self.assertTrue(cfg.is_explicit("log_file"))


if __name__ == "__main__":
    unittest.main()
