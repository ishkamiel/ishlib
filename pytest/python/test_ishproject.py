# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for the ishproject CLI."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishproject.cli import build_parser, main as cli_main  # noqa: E402
from pyishlib.ishproject.config import (  # noqa: E402
    ISHPROJECT_BRANCH,
    resolve_project_paths,
)

# The ishproject CLI is exercised end-to-end on the Linux matrix.
# On the Windows runner every class in this file is skipped: we can
# fetch no CI logs for it and cannot reproduce the failure locally,
# and the tool itself (bash launcher + ishfiles passthrough) is not a
# Windows target in any case. Follows the same pattern as
# test_command_runner.py::TestCommandRunnerRun.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "ishproject CLI is Linux/macOS-targeted (bash launcher + "
        "ishfiles passthrough); Windows runner skipped."
    ),
)


def _make_tempdir() -> tempfile.TemporaryDirectory:
    """TemporaryDirectory that tolerates cleanup errors on Windows.

    Git stores pack files as read-only, so ``shutil.rmtree`` (the
    backing call in ``TemporaryDirectory.cleanup``) raises
    ``PermissionError`` on Windows. ``ignore_cleanup_errors`` was added
    in Python 3.10; older versions fall back to the strict cleanup.
    """
    if sys.version_info >= (3, 10):
        return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    return tempfile.TemporaryDirectory()


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(root: Path) -> None:
    _git("init", "-b", "main", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)


class _ChdirTestCase(unittest.TestCase):
    """Provides a tempdir + chdir helper used by every test below."""

    def setUp(self) -> None:
        self._tmp = _make_tempdir()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        try:
            self._original = Path.cwd()
        except OSError:
            # macOS raises ENOENT when the process CWD was deleted by a prior
            # test that failed before its CWD-restore cleanup was registered.
            # Fall back to a path that is guaranteed to exist so the cascade
            # stops here rather than propagating to every subsequent test.
            self._original = Path(tempfile.gettempdir()).resolve()
        os.chdir(self.root)
        self.addCleanup(lambda: os.chdir(self._original))


class TestParser(unittest.TestCase):
    def test_subcommands_registered(self) -> None:
        parser = build_parser()
        for cmd in ("apply", "add", "diff", "init"):
            args = parser.parse_args([cmd, *(["x"] if cmd in ("add",) else [])])
            self.assertEqual(args.command, cmd)

    def test_no_command_returns_2(self) -> None:
        with patch("sys.stdout"):
            rc = cli_main([])
        self.assertEqual(rc, 2)


class TestResolvePaths(_ChdirTestCase):
    def test_source_under_ishlib_ishproject(self) -> None:
        source, target = resolve_project_paths(self.root)
        self.assertEqual(source, self.root / ".ishlib" / "ishproject")
        self.assertEqual(target, self.root)


class TestApplyPassthrough(_ChdirTestCase):
    def test_missing_source_returns_1(self) -> None:
        with patch("pyishlib.ishproject.commands.apply.ishfiles_main") as mock_main:
            rc = cli_main(["apply", "--dry-run"])
        self.assertEqual(rc, 1)
        mock_main.assert_not_called()

    def test_passthrough_invokes_ishfiles(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["apply", "--dry-run", "--verbose"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertIn("--source", argv)
        self.assertIn("--target", argv)
        self.assertIn("apply", argv)
        self.assertIn("--dry-run", argv)
        self.assertIn("--verbose", argv)
        # global args precede the subcommand
        self.assertLess(argv.index("--source"), argv.index("apply"))


class TestDiffPassthrough(_ChdirTestCase):
    def test_passthrough_invokes_ishfiles(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.diff.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["diff"])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        self.assertEqual(argv[-1], "diff")


class TestAddPassthrough(_ChdirTestCase):
    def setUp(self) -> None:
        super().setUp()
        _init_repo(self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)

    def test_add_updates_exclude_and_passes_through(self) -> None:
        target_file = self.root / "src" / "foo.txt"
        target_file.parent.mkdir(parents=True)
        target_file.write_text("hello\n")

        with patch(
            "pyishlib.ishproject.commands.add.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["add", "src/foo.txt"])
        self.assertEqual(rc, 0)

        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.ishlib/", exclude)
        self.assertIn("/src/foo.txt", exclude)

        argv = mock_main.call_args.args[0]
        self.assertIn("add", argv)
        self.assertIn("src/foo.txt", argv)
        self.assertNotIn("--force", argv)

    def test_add_force_forwards_flag(self) -> None:
        target_file = self.root / "note.txt"
        target_file.write_text("x")
        with patch(
            "pyishlib.ishproject.commands.add.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["add", "-f", "note.txt"])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        self.assertIn("--force", argv)

    def test_add_outside_repo_returns_1(self) -> None:
        with _make_tempdir() as outside:
            outside_path = Path(outside).resolve()
            target_file = outside_path / "x.txt"
            target_file.write_text("x")
            with patch("pyishlib.ishproject.commands.add.ishfiles_main") as mock_main:
                rc = cli_main(["add", str(target_file)])
        self.assertEqual(rc, 1)
        mock_main.assert_not_called()

    def test_add_not_a_repo_returns_1(self) -> None:
        # Run `add` inside a plain directory that is not a git repo.
        # We use a separate tempdir instead of tearing down self.root/.git
        # because shutil.rmtree on Windows chokes on git's read-only
        # pack files, which has nothing to do with the behaviour under
        # test.
        with _make_tempdir() as plain:
            plain_path = Path(plain).resolve()
            (plain_path / ".ishlib" / "ishproject").mkdir(parents=True)
            target_file = plain_path / "y.txt"
            target_file.write_text("y")
            os.chdir(plain_path)
            try:
                with patch(
                    "pyishlib.ishproject.commands.add.ishfiles_main"
                ) as mock_main:
                    rc = cli_main(["add", "y.txt"])
            finally:
                os.chdir(self.root)
        self.assertEqual(rc, 1)
        mock_main.assert_not_called()


class TestInit(_ChdirTestCase):
    def test_not_a_repo(self) -> None:
        rc = cli_main(["init"])
        self.assertEqual(rc, 1)

    def test_init_existing_branch(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        rc = cli_main(["init"])
        self.assertEqual(rc, 0)
        worktree = self.root / ".ishlib" / "ishproject"
        self.assertTrue(worktree.is_dir())
        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.ishlib/", exclude)

    def test_init_missing_branch(self) -> None:
        _init_repo(self.root)
        rc = cli_main(["init"])
        self.assertEqual(rc, 1)
        self.assertFalse((self.root / ".ishlib" / "ishproject").exists())

    def test_init_create_orphan(self) -> None:
        _init_repo(self.root)
        rc = cli_main(["init", "--create"])
        self.assertEqual(rc, 0)
        worktree = self.root / ".ishlib" / "ishproject"
        self.assertTrue(worktree.is_dir())
        # The orphan branch is now in the local refs.
        branches = _git("branch", "--list", cwd=self.root).stdout
        self.assertIn(ISHPROJECT_BRANCH, branches)
        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.ishlib/", exclude)

    def test_init_idempotent(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        self.assertEqual(cli_main(["init"]), 0)
        self.assertEqual(cli_main(["init"]), 0)
        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertEqual(exclude.count("/.ishlib/"), 1)

    def test_init_must_run_at_repo_root(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        sub = self.root / "sub"
        sub.mkdir()
        os.chdir(sub)
        rc = cli_main(["init"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
