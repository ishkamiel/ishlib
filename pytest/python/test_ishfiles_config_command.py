# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for ishfiles.commands.config."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.cli import IshfilesCLI
from pyishlib.ishfiles.commands.config import (
    ConfigCommand,
    _format_value,
)
from pyishlib.ishfiles.config import load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**overrides):
    """Argparse-shaped namespace with the attributes ConfigCommand reads."""
    defaults = {
        "home": None,
        "source": None,
        "target": None,
        "config": None,
        "dry_run": False,
        "verbose": False,
        "debug": False,
        "quiet": False,
        "show_origins": False,
        "set_kv": None,
        "custom_username": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _run_view(cfg, *, show_origins: bool = False) -> str:
    cmd = ConfigCommand()
    cmd.cfg = cfg
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cmd._do_view(show_origins)
    assert rc == 0, "view should always succeed"
    return buf.getvalue()


def _run_set(cfg, key: str, value: str) -> int:
    cmd = ConfigCommand()
    cmd.cfg = cfg
    return cmd._do_set(key, value)


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


class TestParser(unittest.TestCase):
    def test_parser_registers_config(self):
        parser = IshfilesCLI().build_parser()
        # The subparsers store choices on the _SubParsersAction.
        sub_action = next(
            a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"
        )
        self.assertIn("config", sub_action.choices)

    def test_parser_accepts_show_origins(self):
        parser = IshfilesCLI().build_parser()
        ns = parser.parse_args(["config", "--show-origins"])
        self.assertTrue(ns.show_origins)
        self.assertIsNone(ns.set_kv)

    def test_parser_accepts_set(self):
        parser = IshfilesCLI().build_parser()
        ns = parser.parse_args(["config", "--set", "ishfiles.source", "/tmp/x"])
        self.assertEqual(ns.set_kv, ["ishfiles.source", "/tmp/x"])
        self.assertFalse(ns.show_origins)

    def test_parser_set_and_origins_mutually_exclusive(self):
        parser = IshfilesCLI().build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["config", "--show-origins", "--set", "ishfiles.source", "/tmp/x"]
            )

    def test_parser_set_requires_two_values(self):
        parser = IshfilesCLI().build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["config", "--set", "ishfiles.source"])


# ---------------------------------------------------------------------------
# Default view
# ---------------------------------------------------------------------------


class TestView(unittest.TestCase):
    def test_view_default_lists_user_facing_keys(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text(
                "[ishfiles]\n"
                'source = "/tmp/dot"\n'
                'target = "/tmp/home"\n'
                'default_shell = "zsh"\n'
                "\n[ignore]\n"
                'patterns = ["*.bak"]\n'
                "\n[data]\n"
                'email = "me@example.com"\n'
            )
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            out = _run_view(cfg)

        self.assertIn("ishfiles.source = /tmp/dot", out)
        self.assertIn("ishfiles.target = /tmp/home", out)
        self.assertIn("ishfiles.default_shell = zsh", out)
        self.assertIn('ignore.patterns = ["*.bak"]', out)
        self.assertIn("data.email = me@example.com", out)
        # Constants must not leak into the user-facing view.
        self.assertNotIn("config_dir", out)
        self.assertNotIn("scripts_dir", out)
        self.assertNotIn("ignore_file", out)

    def test_view_skips_unset_default_shell(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"  # absent
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            out = _run_view(cfg)
        # default_shell has no built-in default and no user/repo source here.
        self.assertNotIn("default_shell", out)
        # source and target ARE in defaults so they show up.
        self.assertIn("ishfiles.source", out)
        self.assertIn("ishfiles.target", out)

    def test_view_output_lines_are_set_compatible(self):
        """Every printed scalar line must round-trip through the --set parser."""
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text(
                '[ishfiles]\nsource = "/tmp/dot"\ndefault_shell = "zsh"\n'
                '\n[data]\nemail = "me@example.com"\nmachineType = "personal"\n'
            )
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            out = _run_view(cfg)

        parser = IshfilesCLI().build_parser()
        seen_scalar = False
        for line in out.splitlines():
            if not line.strip():
                continue
            # ignore.patterns is list-valued; skip per the v1 deferral.
            if line.startswith("ignore.patterns"):
                continue
            key, _, value = line.partition(" = ")
            ns = parser.parse_args(["config", "--set", key, value])
            self.assertEqual(ns.set_kv, [key, value])
            seen_scalar = True
        self.assertTrue(seen_scalar, "test produced no scalar lines to check")

    def test_view_show_origins_tags_layers(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            home.mkdir()
            cfg_path = home / ".config" / "ishfiles" / "config.toml"
            cfg_path.parent.mkdir(parents=True)
            cfg_path.write_text(
                '[ishfiles]\ntarget = "/tmp/from-user"\n'
                '\n[data]\nemail = "me@example.com"\n'
            )

            # The CLI-supplied source must actually exist where
            # load_config will look for the repo-level config.toml.
            source_dir = home / "src"
            (source_dir / "ishconfig").mkdir(parents=True)
            (source_dir / "ishconfig" / "config.toml").write_text(
                '[ishfiles]\ndefault_shell = "fish"\n'
            )

            cfg = load_config(
                args=_make_args(home=str(home), source=str(source_dir)),
                config_file=cfg_path,
            )
            out = _run_view(cfg, show_origins=True)

        self.assertIn(f"ishfiles.source = {source_dir}  # cli", out)
        self.assertIn(
            f"ishfiles.target = /tmp/from-user  # user-config: {cfg_path}", out
        )
        self.assertIn(
            "ishfiles.default_shell = fish  # repo-config: "
            + str(source_dir / "ishconfig" / "config.toml"),
            out,
        )
        self.assertIn("ignore.patterns = []  # default", out)
        self.assertIn(
            f"data.email = me@example.com  # user-config: {cfg_path}",
            out,
        )


# ---------------------------------------------------------------------------
# IshConfig.get_origin
# ---------------------------------------------------------------------------


class TestGetOrigin(unittest.TestCase):
    def test_origin_walks_constants_then_args_then_conf_then_repo_then_default(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            home.mkdir()
            cfg_path = home / ".config" / "ishfiles" / "config.toml"
            cfg_path.parent.mkdir(parents=True)
            cfg_path.write_text('[ishfiles]\ntarget = "/tmp/from-user"\n')

            source_dir = home / "src"
            (source_dir / "ishconfig").mkdir(parents=True)
            (source_dir / "ishconfig" / "config.toml").write_text(
                '[ishfiles]\ndefault_shell = "fish"\n'
            )

            cfg = load_config(
                args=_make_args(home=str(home), source=str(source_dir)),
                config_file=cfg_path,
            )

            self.assertEqual(cfg.get_origin("config_dir"), ("constant", None))
            self.assertEqual(cfg.get_origin("source"), ("cli", None))

            layer, src = cfg.get_origin("target")
            self.assertEqual(layer, "user-config")
            self.assertEqual(src, str(cfg_path))

            layer, src = cfg.get_origin("default_shell")
            self.assertEqual(layer, "repo-config")
            self.assertEqual(src, str(source_dir / "ishconfig" / "config.toml"))

            self.assertEqual(cfg.get_origin("patterns"), ("default", None))
            self.assertEqual(cfg.get_origin("never_set"), ("unset", None))


# ---------------------------------------------------------------------------
# --set
# ---------------------------------------------------------------------------


class TestSet(unittest.TestCase):
    def test_set_writes_to_user_config_and_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)

            rc = _run_set(cfg, "ishfiles.source", "/tmp/foo")
            self.assertEqual(rc, 0)
            self.assertTrue(cfg_path.is_file())

            # Reload and check the value made the chain.
            cfg2 = load_config(args=_make_args(), config_file=cfg_path)
            self.assertEqual(cfg2.get_opt("source"), "/tmp/foo")
            layer, src = cfg2.get_origin("source")
            self.assertEqual(layer, "user-config")
            self.assertEqual(src, str(cfg_path))

    def test_set_creates_config_file_when_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "deep" / "nested" / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)

            rc = _run_set(cfg, "data.email", "me@example.com")
            self.assertEqual(rc, 0)
            self.assertTrue(cfg_path.is_file())

            cfg2 = load_config(args=_make_args(), config_file=cfg_path)
            self.assertEqual(cfg2.context.get("email"), "me@example.com")

    def test_set_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(dry_run=True), config_file=cfg_path)

            rc = _run_set(cfg, "ishfiles.source", "/tmp/foo")
            self.assertEqual(rc, 0)
            self.assertFalse(cfg_path.exists())

    def test_set_unknown_section_errors(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            rc = _run_set(cfg, "foo.bar", "baz")
            self.assertNotEqual(rc, 0)
            self.assertFalse(cfg_path.exists())

    def test_set_requires_dotted_key(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            rc = _run_set(cfg, "source", "/tmp/foo")
            self.assertNotEqual(rc, 0)
            self.assertFalse(cfg_path.exists())

    def test_set_unknown_leaf_in_ishfiles_errors(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            rc = _run_set(cfg, "ishfiles.bogus", "x")
            self.assertNotEqual(rc, 0)
            self.assertFalse(cfg_path.exists())

    def test_set_ignore_patterns_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            rc = _run_set(cfg, "ignore.patterns", '["*.bak"]')
            self.assertNotEqual(rc, 0)
            self.assertFalse(cfg_path.exists())

    def test_set_constant_leaf_in_data_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            # config_dir is a registered constant on cfg.
            rc = _run_set(cfg, "data.config_dir", "x")
            self.assertNotEqual(rc, 0)
            self.assertFalse(cfg_path.exists())

    def test_set_with_custom_config_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "alt.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            rc = _run_set(cfg, "ishfiles.target", "/tmp/elsewhere")
            self.assertEqual(rc, 0)
            self.assertTrue(cfg_path.is_file())
            self.assertIn("/tmp/elsewhere", cfg_path.read_text())

    def test_set_preserves_other_sections(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text(
                '[ishfiles]\nsource = "/tmp/keep"\n'
                '\n[data]\nemail = "keep@example.com"\n'
            )
            cfg = load_config(args=_make_args(), config_file=cfg_path)

            rc = _run_set(cfg, "data.machineType", "personal")
            self.assertEqual(rc, 0)

            cfg2 = load_config(args=_make_args(), config_file=cfg_path)
            self.assertEqual(cfg2.get_opt("source"), "/tmp/keep")
            self.assertEqual(cfg2.context.get("email"), "keep@example.com")
            self.assertEqual(cfg2.context.get("machineType"), "personal")

    def test_set_overwrites_existing_value(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text('[ishfiles]\nsource = "/old"\n')
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            rc = _run_set(cfg, "ishfiles.source", "/new")
            self.assertEqual(rc, 0)
            cfg2 = load_config(args=_make_args(), config_file=cfg_path)
            self.assertEqual(cfg2.get_opt("source"), "/new")

    def test_set_escapes_special_characters(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            tricky = 'a"b\\c\nd'
            rc = _run_set(cfg, "data.note", tricky)
            self.assertEqual(rc, 0)
            cfg2 = load_config(args=_make_args(), config_file=cfg_path)
            self.assertEqual(cfg2.context.get("note"), tricky)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):
    def test_format_value_string(self):
        self.assertEqual(_format_value("hello"), "hello")

    def test_format_value_list(self):
        self.assertEqual(_format_value([]), "[]")
        self.assertEqual(_format_value(["a", "b"]), '["a", "b"]')

    def test_format_value_none(self):
        self.assertEqual(_format_value(None), "")

    def test_bare_key_with_dash_accepted(self):
        """Integration: --set accepts TOML bare keys containing `-`."""
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg = load_config(args=_make_args(), config_file=cfg_path)
            rc = _run_set(cfg, "data.machine-type", "personal")
            self.assertEqual(rc, 0)
            cfg2 = load_config(args=_make_args(), config_file=cfg_path)
            self.assertEqual(cfg2.context.get("machine-type"), "personal")


if __name__ == "__main__":
    unittest.main()
