# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :mod:`pyishlib.cli_command` — base class + passthrough machinery."""

import argparse
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.cli_command import (  # noqa: E402
    CliCommand,
    _compose_argv,
)

# Skipped on Windows for parity with the rest of the ishproject test
# suite; Linux matrix covers the behaviour.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="ishproject stack is Linux/macOS-targeted; Windows skipped.",
)


# ---------------------------------------------------------------------------
# argv composition (legacy tests, unchanged semantics)
# ---------------------------------------------------------------------------


class TestComposeArgv(unittest.TestCase):
    def test_composes_argv(self) -> None:
        argv = _compose_argv(
            "apply",
            ["--foo", "bar"],
            global_args=["--source", "/x", "--target", "/y"],
        )
        self.assertEqual(
            argv, ["--source", "/x", "--target", "/y", "apply", "--foo", "bar"]
        )

    def test_no_global_args(self) -> None:
        self.assertEqual(_compose_argv("add", ("a", "b")), ["add", "a", "b"])

    def test_target_parser_splits_top_level_flags(self) -> None:
        target_parser = argparse.ArgumentParser()
        target_parser.add_argument("-n", "--dry-run", action="store_true")
        target_parser.add_argument("-v", "--verbose", action="count")
        sub = target_parser.add_subparsers(dest="cmd")
        p = sub.add_parser("apply")
        p.add_argument("files", nargs="*")

        argv = _compose_argv(
            "apply",
            ["--dry-run", "foo.txt"],
            global_args=["--source", "/x"],
            target_parser=target_parser,
        )
        # `--dry-run` is top-level on the target parser, so it sits
        # before the subcommand; the positional `foo.txt` stays after.
        self.assertEqual(
            argv, ["--source", "/x", "--dry-run", "apply", "foo.txt"]
        )

    def test_target_parser_abbrev_matches_target(self) -> None:
        target_parser = argparse.ArgumentParser()  # default allow_abbrev=True
        target_parser.add_argument("--verbose", action="store_true")
        sub = target_parser.add_subparsers(dest="cmd")
        sub.add_parser("apply")

        argv = _compose_argv(
            "apply", ["--ver"], target_parser=target_parser
        )
        self.assertEqual(argv, ["--ver", "apply"])


# ---------------------------------------------------------------------------
# CliCommand — self.cfg population & run() signature
# ---------------------------------------------------------------------------


class _DummyCommand(CliCommand):
    NAME = "dummy"
    HELP = "dummy command"

    last_cfg = None
    ran = 0

    def run(self) -> int:
        type(self).last_cfg = self.cfg
        type(self).ran += 1
        return 42


class TestEntryPopulatesCfg(unittest.TestCase):
    def setUp(self) -> None:
        _DummyCommand.last_cfg = None
        _DummyCommand.ran = 0

    def test_entry_sets_cfg_before_run(self) -> None:
        ctx = SimpleNamespace(answer=42)
        rc = _DummyCommand._entry(ctx)
        self.assertEqual(rc, 42)
        self.assertEqual(_DummyCommand.ran, 1)
        self.assertIs(_DummyCommand.last_cfg, ctx)

    def test_self_cfg_defaults_to_none(self) -> None:
        cmd = _DummyCommand()
        self.assertIsNone(cmd.cfg)


# ---------------------------------------------------------------------------
# passthrough() — target gate + forwarding
# ---------------------------------------------------------------------------


def _build_target_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("apply")
    p.add_argument("files", nargs="*")
    p.add_argument("--force-scripts")
    return parser


class _PassThroughCommand(CliCommand):
    NAME = "pt"
    HELP = "passthrough test"
    TARGET_MAIN = staticmethod(MagicMock(return_value=0))
    TARGET_BUILD_PARSER = staticmethod(_build_target_parser)

    def run(self) -> int:
        return 0


class _NoTargetCommand(CliCommand):
    NAME = "no-target"
    HELP = "command without passthrough target"

    def run(self) -> int:
        return 0


class _ExplicitAwareCfg:
    """Tiny stand-in for IshConfig: only implements is_explicit + log_file."""

    def __init__(self, explicit: set, log_file=None) -> None:
        self._explicit = explicit
        self.log_file = log_file

    def is_explicit(self, name: str) -> bool:
        return name in self._explicit


class TestPassthroughMethod(unittest.TestCase):
    def setUp(self) -> None:
        _PassThroughCommand.TARGET_MAIN.reset_mock()

    def test_raises_when_target_not_set(self) -> None:
        cmd = _NoTargetCommand()
        cmd.cfg = _ExplicitAwareCfg(set())
        with self.assertRaises(TypeError):
            cmd.passthrough("apply", ())
        with self.assertRaises(TypeError):
            cmd.compose_passthrough_argv("apply", ())

    def test_no_explicit_no_forwarded_globals(self) -> None:
        cmd = _PassThroughCommand()
        cmd.cfg = _ExplicitAwareCfg(set())
        rc = cmd.passthrough(
            "apply",
            ("foo.txt",),
            global_args=["--source", "/x"],
        )
        self.assertEqual(rc, 0)
        _PassThroughCommand.TARGET_MAIN.assert_called_once_with(
            ["--source", "/x", "apply", "foo.txt"]
        )

    def test_explicit_dry_run_is_forwarded(self) -> None:
        cmd = _PassThroughCommand()
        cmd.cfg = _ExplicitAwareCfg({"dry_run"})
        cmd.passthrough("apply", (), global_args=["--source", "/x"])
        # --dry-run is a top-level flag on the target; _split_for_target
        # keeps it before the subcommand.
        _PassThroughCommand.TARGET_MAIN.assert_called_once_with(
            ["--source", "/x", "--dry-run", "apply"]
        )

    def test_explicit_log_file_forwards_value(self) -> None:
        cmd = _PassThroughCommand()
        cmd.cfg = _ExplicitAwareCfg({"log_file"}, log_file="/tmp/ish.log")
        cmd.passthrough("apply", (), global_args=())
        # --log-file is not declared on the mock target parser, so it
        # lands after the subcommand; the value must follow.
        _PassThroughCommand.TARGET_MAIN.assert_called_once_with(
            ["apply", "--log-file", "/tmp/ish.log"]
        )

    def test_remainder_delivered_flag_not_double_forwarded(self) -> None:
        """`-v` inside REMAINDER is not also forwarded via explicit tracking."""
        cmd = _PassThroughCommand()
        # User typed `pt apply --force-scripts myscript -v` — --force-scripts
        # triggered REMAINDER, which then swallowed `-v`. argparse never
        # saw `-v`, so is_explicit("verbose") is False, but the token is
        # still present in the REMAINDER payload.
        cmd.cfg = _ExplicitAwareCfg(set())
        cmd.passthrough(
            "apply",
            ("--force-scripts", "myscript", "-v"),
            global_args=["--source", "/x"],
        )
        # `-v` gets peeled off by _split_for_target and placed before
        # the subcommand; not appended a second time via explicit
        # forwarding (which would produce `--verbose` as well).
        _PassThroughCommand.TARGET_MAIN.assert_called_once_with(
            ["--source", "/x", "-v", "apply", "--force-scripts", "myscript"]
        )

    def test_compose_passthrough_argv_returns_list(self) -> None:
        cmd = _PassThroughCommand()
        cmd.cfg = _ExplicitAwareCfg({"debug"})
        argv = cmd.compose_passthrough_argv(
            "apply", (), global_args=["--source", "/x"]
        )
        # `--debug` is not declared on the mock target parser, so it
        # falls after the subcommand via `_split_for_target`.
        self.assertEqual(argv, ["--source", "/x", "apply", "--debug"])
        _PassThroughCommand.TARGET_MAIN.assert_not_called()


if __name__ == "__main__":
    unittest.main()
