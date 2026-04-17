# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :mod:`pyishlib.cli_passthrough`."""

import os
import sys
import unittest
from unittest.mock import MagicMock

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.cli_passthrough import passthrough_to_cli  # noqa: E402

# Skipped on Windows for parity with the rest of the ishproject test
# suite; Linux matrix covers the behaviour.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="ishproject stack is Linux/macOS-targeted; Windows skipped.",
)


class TestPassthrough(unittest.TestCase):
    def test_composes_argv(self) -> None:
        target = MagicMock(return_value=0)
        rc = passthrough_to_cli(
            target,
            subcommand="apply",
            remainder=["--foo", "bar"],
            global_args=["--source", "/x", "--target", "/y"],
        )
        self.assertEqual(rc, 0)
        target.assert_called_once_with(
            ["--source", "/x", "--target", "/y", "apply", "--foo", "bar"]
        )

    def test_returns_target_exit_code(self) -> None:
        target = MagicMock(return_value=7)
        self.assertEqual(
            passthrough_to_cli(target, subcommand="diff", remainder=[]),
            7,
        )
        target.assert_called_once_with(["diff"])

    def test_no_global_args(self) -> None:
        target = MagicMock(return_value=0)
        passthrough_to_cli(target, subcommand="add", remainder=("a", "b"))
        target.assert_called_once_with(["add", "a", "b"])

    def test_target_parser_splits_top_level_flags(self) -> None:
        """When a target parser is given, its top-level flags jump ahead."""
        import argparse

        target_parser = argparse.ArgumentParser()
        target_parser.add_argument("-n", "--dry-run", action="store_true")
        target_parser.add_argument("-v", "--verbose", action="count")
        sub = target_parser.add_subparsers(dest="cmd")
        p = sub.add_parser("apply")
        p.add_argument("files", nargs="*")

        target = MagicMock(return_value=0)
        passthrough_to_cli(
            target,
            subcommand="apply",
            remainder=["--dry-run", "foo.txt"],
            global_args=["--source", "/x"],
            target_parser=target_parser,
        )
        # `--dry-run` is top-level on the target parser, so it sits
        # before the subcommand; the positional `foo.txt` stays after.
        target.assert_called_once_with(
            ["--source", "/x", "--dry-run", "apply", "foo.txt"]
        )

    def test_target_parser_abbrev_matches_target(self) -> None:
        """`--ver` should not be misclassified as leftover."""
        import argparse

        target_parser = argparse.ArgumentParser()  # default allow_abbrev=True
        target_parser.add_argument("--verbose", action="store_true")
        sub = target_parser.add_subparsers(dest="cmd")
        sub.add_parser("apply")

        target = MagicMock(return_value=0)
        passthrough_to_cli(
            target,
            subcommand="apply",
            remainder=["--ver"],
            target_parser=target_parser,
        )
        # `--ver` is an unambiguous abbreviation of `--verbose` on the
        # target parser, so it routes before the subcommand.
        target.assert_called_once_with(["--ver", "apply"])


if __name__ == "__main__":
    unittest.main()
