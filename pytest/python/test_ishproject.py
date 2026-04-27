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
    DEFAULT_PREFIX,
    DEFAULT_POSTFIX,
    IshprojectConfig,
)

DEFAULT_BRANCH = f"{DEFAULT_PREFIX}/{DEFAULT_POSTFIX}"
# Backward-compat alias: older tests referenced ``ISHPROJECT_BRANCH``.
ISHPROJECT_BRANCH = DEFAULT_BRANCH


def _default_cfg() -> IshprojectConfig:
    """Build an IshprojectConfig with the ishproject default prefix/postfix."""
    return IshprojectConfig(
        defaults={"prefix": DEFAULT_PREFIX, "postfix": DEFAULT_POSTFIX},
    )


_DEFAULT_CFG = _default_cfg()

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
        extras = {"add": ["x"], "clean-rebase": ["HEAD~0"]}
        for cmd in (
            "apply",
            "add",
            "branch",
            "clean-rebase",
            "commit",
            "diff",
            "init",
            "merge",
            "pull",
            "push",
            "status",
        ):
            args = parser.parse_args([cmd, *extras.get(cmd, [])])
            self.assertEqual(args.command, cmd)

    def test_no_command_returns_2(self) -> None:
        with patch("sys.stdout"):
            rc = cli_main([])
        self.assertEqual(rc, 2)

    def test_clean_rebase_requires_base(self) -> None:
        parser = build_parser()
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                parser.parse_args(["clean-rebase"])

    def test_add_files_positional_has_file_completion_hint(self) -> None:
        """`ishproject add <path><tab>` must complete file paths.

        shtab consumes the ``complete`` attribute on the argparse action
        when generating shell completions; without it, bash falls back
        to displaying the help text instead of real filenames.
        """
        import argparse

        from pyishlib.completions import FILE as COMPLETE_FILE

        parser = build_parser()
        subparsers_action = next(
            a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
        )
        add_sub = subparsers_action.choices["add"]
        files_action = next(a for a in add_sub._actions if a.dest == "files")
        self.assertEqual(
            getattr(files_action, "complete", None),
            COMPLETE_FILE,
        )


class TestResolvePaths(_ChdirTestCase):
    def test_source_under_ishlib_ishproject(self) -> None:
        source, target = _DEFAULT_CFG.resolve_project_paths(self.root)
        self.assertEqual(source, self.root / ".ishlib" / "ishproject")
        self.assertEqual(target, self.root)

    def test_branch_specific_path_is_suffixed(self) -> None:
        branch = _DEFAULT_CFG.branch_for("main")
        source, target = _DEFAULT_CFG.resolve_project_paths(self.root, branch=branch)
        self.assertEqual(source.parent, self.root / ".ishlib")
        self.assertTrue(source.name.startswith("ishproject-main-"))
        # 8-hex-char hash suffix.
        suffix = source.name[len("ishproject-main-") :]
        self.assertEqual(len(suffix), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in suffix))
        self.assertEqual(target, self.root)

    def test_branch_with_slashes_is_sanitized(self) -> None:
        from pyishlib.ishlib_folder import IshlibFolder

        folder = IshlibFolder(self.root)
        branch = _DEFAULT_CFG.branch_for("feature/x")
        path = _DEFAULT_CFG.worktree_path(folder, branch)
        self.assertTrue(path.name.startswith("ishproject-feature_x-"))

    def test_sanitize_collision_is_broken_by_hash(self) -> None:
        # feature/x and feature_x sanitize to the same segment; the hash
        # suffix must keep their worktree paths distinct.
        from pyishlib.ishlib_folder import IshlibFolder

        folder = IshlibFolder(self.root)
        a = _DEFAULT_CFG.worktree_path(folder, _DEFAULT_CFG.branch_for("feature/x"))
        b = _DEFAULT_CFG.worktree_path(folder, _DEFAULT_CFG.branch_for("feature_x"))
        self.assertNotEqual(a, b)


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

    def test_passthrough_forwards_skip_launchers(self) -> None:
        # Project worktrees never contain ishlib/src, so ishproject apply
        # should always tell ishfiles to skip Phase 0.
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["apply", "--dry-run"])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        self.assertEqual(argv.count("--skip-launchers"), 1)
        # --skip-launchers is an apply-subparser flag; it must follow the
        # subcommand, not precede it.
        self.assertGreater(argv.index("--skip-launchers"), argv.index("apply"))

    def test_passthrough_skip_launchers_not_duplicated(self) -> None:
        # If the user explicitly passes --skip-launchers via `rest`, the
        # auto-prepend must not add a duplicate.
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["apply", "--dry-run", "--skip-launchers"])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        self.assertEqual(argv.count("--skip-launchers"), 1)


class TestApplyExcludes(_ChdirTestCase):
    """Verify ``ishproject apply`` registers applied targets in info/exclude."""

    def setUp(self) -> None:
        super().setUp()
        _init_repo(self.root)
        self.project = self.root / ".ishlib" / "ishproject"
        self.project.mkdir(parents=True)

    def _exclude_text(self) -> str:
        p = self.root / ".git" / "info" / "exclude"
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def test_apply_adds_ishlib_exclude(self) -> None:
        (self.project / "dot_bashrc").write_text("export FOO=bar\n")
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ):
            rc = cli_main(["apply", "-y"])
        self.assertEqual(rc, 0)
        self.assertIn("/.ishlib/", self._exclude_text())

    def test_apply_excludes_each_target_file(self) -> None:
        (self.project / "dot_foo").write_text("foo\n")
        (self.project / "subdir").mkdir()
        (self.project / "subdir" / "dot_bar").write_text("bar\n")
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ):
            rc = cli_main(["apply", "-y"])
        self.assertEqual(rc, 0)
        text = self._exclude_text()
        self.assertIn("/.foo", text)
        self.assertIn("/subdir/.bar", text)

    def test_apply_idempotent(self) -> None:
        (self.project / "dot_foo").write_text("foo\n")
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ):
            self.assertEqual(cli_main(["apply", "-y"]), 0)
            self.assertEqual(cli_main(["apply", "-y"]), 0)
        text = self._exclude_text()
        self.assertEqual(text.count("/.foo"), 1)
        self.assertEqual(text.count("/.ishlib/"), 1)

    def test_apply_not_a_repo_continues_to_passthrough(self) -> None:
        # Run `apply` inside a plain directory that is not a git repo.
        # The exclude helper must skip silently and still forward to
        # ishfiles -- this is what isholate containers rely on.
        with _make_tempdir() as plain:
            plain_path = Path(plain).resolve()
            (plain_path / ".ishlib" / "ishproject").mkdir(parents=True)
            (plain_path / ".ishlib" / "ishproject" / "dot_foo").write_text("x")
            os.chdir(plain_path)
            try:
                with patch(
                    "pyishlib.ishproject.commands.apply.ishfiles_main",
                    return_value=0,
                ) as mock_main:
                    rc = cli_main(["apply", "-y"])
            finally:
                os.chdir(self.root)
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()

    def test_apply_passthrough_argv_unchanged(self) -> None:
        # Regression guard on top of TestApplyPassthrough: after adding
        # the pre-exclude step, the forwarded argv shape must still
        # carry --source/--target and the user's own flags.
        (self.project / "dot_foo").write_text("x")
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["apply", "-y", "--verbose"])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        self.assertIn("--source", argv)
        self.assertIn("--target", argv)
        self.assertIn("apply", argv)
        self.assertIn("--verbose", argv)
        self.assertLess(argv.index("--source"), argv.index("apply"))

    def test_apply_dry_run_does_not_modify_exclude(self) -> None:
        # `--dry-run` is forwarded via argv passthrough (ADD_COMMON_FLAGS
        # = False on apply), so the helper must parse the composed
        # ishfiles argv rather than read args.dry_run to honour it.
        (self.project / "dot_foo").write_text("foo\n")
        before = self._exclude_text()
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["apply", "-y", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(self._exclude_text(), before)
        argv = mock_main.call_args.args[0]
        self.assertIn("--dry-run", argv)

    def test_apply_restricted_to_positional_files(self) -> None:
        # `ishproject apply <file>` restricts the apply to that file;
        # the pre-scan must only exclude the restricted target, not
        # every file discoverable in the source.
        (self.project / "dot_foo").write_text("foo\n")
        (self.project / "dot_bar").write_text("bar\n")
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ):
            rc = cli_main(["apply", "-y", "dot_foo"])
        self.assertEqual(rc, 0)
        text = self._exclude_text()
        self.assertIn("/.foo", text)
        self.assertNotIn("/.bar", text)


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


def _simulate_add(argv) -> int:
    """Stand-in for ``ishfiles_main`` used by ``ishproject add`` tests.

    Mirrors what ``ishfiles add`` does on the filesystem: for each
    trailing positional arg, copy it from --target into --source
    (applying the ``dot_`` prefix for hidden path components).
    Directory args are walked recursively, matching the real CLI's
    ``git add <dir>``-style semantics. Returns 0.
    """
    i = argv.index("--source")
    source = Path(argv[i + 1])
    i = argv.index("--target")
    target = Path(argv[i + 1])
    # ishfiles add's pass through positional args after the subcommand.
    try:
        add_idx = argv.index("add")
    except ValueError:
        return 1
    args = [a for a in argv[add_idx + 1 :] if not a.startswith("-")]

    def _translate(rel: Path) -> Path:
        # Mirror ``ishfiles add`` reverse-translation semantics: every path
        # component that starts with ``.`` is stored with a ``dot_`` prefix.
        parts = [
            "dot_" + part[1:] if part.startswith(".") else part for part in rel.parts
        ]
        return Path(*parts)

    files: list[tuple[Path, Path]] = []
    for arg in args:
        arg_path = Path(arg)
        src_path = arg_path if arg_path.is_absolute() else target / arg_path
        if src_path.is_dir():
            for f in sorted(src_path.rglob("*")):
                if f.is_file():
                    try:
                        rel = f.resolve().relative_to(target.resolve())
                    except ValueError:
                        # Mirror the real finder, which rejects absolute
                        # paths outside --target rather than crashing.
                        continue
                    files.append((f, _translate(rel)))
        elif src_path.is_file():
            # Determine the relative path against target when possible so we
            # translate components symmetrically.
            try:
                rel = src_path.resolve().relative_to(target.resolve())
            except ValueError:
                rel = Path(arg_path.name)
            files.append((src_path, _translate(rel)))

    for src_file, dst_rel in files:
        dst_file = source / dst_rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_bytes(src_file.read_bytes())
    return 0


class TestAddEndToEnd(_ChdirTestCase):
    """End-to-end: add stays hidden in main but is staged in the ishproject worktree.

    Exercises the full workflow that motivated the feature: a dotfile
    in the user's working tree must be hidden from `git status` in
    that worktree (via the shared `.git/info/exclude`) yet remain
    visible and staged in the ishproject worktree at
    `.ishlib/ishproject/` so the user can commit it there.
    """

    def setUp(self) -> None:
        super().setUp()
        self.bare = _setup_bare_remote(self)

    def test_add_hides_in_main_and_stages_in_ishproject_worktree(self) -> None:
        _init_repo(self.root)
        rc = cli_main(["init", "--create", "--remote", str(self.bare)])
        self.assertEqual(rc, 0)

        (self.root / ".my_config").write_text("stuff\n")

        with patch(
            "pyishlib.ishproject.commands.add.ishfiles_main",
            side_effect=_simulate_add,
        ):
            rc = cli_main(["add", ".my_config"])
        self.assertEqual(rc, 0)

        # Shared exclude hides the file in the main worktree.
        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.my_config", exclude)
        main_porcelain = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertNotIn(".my_config", main_porcelain)

        # File was copied into the ishproject worktree with the dot_ prefix.
        source = self.root / ".ishlib" / "ishproject"
        self.assertTrue((source / "dot_my_config").is_file())

        # And it is staged (git add --force --all ran in the worktree).
        staged = subprocess.run(
            ["git", "-C", str(source), "diff", "--cached", "--name-only"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("dot_my_config", staged)

    def test_add_directory_recurses_end_to_end(self) -> None:
        """A directory arg adds every file inside it, hidden in main and
        staged in the ishproject worktree."""
        _init_repo(self.root)
        rc = cli_main(["init", "--create", "--remote", str(self.bare)])
        self.assertEqual(rc, 0)

        skills = self.root / ".claude" / "skills"
        (skills / "nested").mkdir(parents=True)
        (skills / "foo.md").write_text("foo\n")
        (skills / "bar.md").write_text("bar\n")
        (skills / "nested" / "baz.md").write_text("baz\n")

        with patch(
            "pyishlib.ishproject.commands.add.ishfiles_main",
            side_effect=_simulate_add,
        ):
            rc = cli_main(["add", ".claude/skills"])
        self.assertEqual(rc, 0)

        # The directory is excluded in the main worktree (trailing slash).
        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.claude/skills/", exclude)

        # Every walked file was copied into the ishproject worktree.
        source = self.root / ".ishlib" / "ishproject"
        self.assertTrue((source / "dot_claude" / "skills" / "foo.md").is_file())
        self.assertTrue((source / "dot_claude" / "skills" / "bar.md").is_file())
        self.assertTrue(
            (source / "dot_claude" / "skills" / "nested" / "baz.md").is_file()
        )

        # All of them are staged in the ishproject worktree.
        staged = subprocess.run(
            ["git", "-C", str(source), "diff", "--cached", "--name-only"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("dot_claude/skills/foo.md", staged)
        self.assertIn("dot_claude/skills/bar.md", staged)
        self.assertIn("dot_claude/skills/nested/baz.md", staged)


def _make_bare(parent: Path) -> Path:
    """Create an initialised bare git repo at ``parent/bare.git``."""
    bare = parent / "bare.git"
    bare.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    return bare


def _setup_bare_remote(test_case: unittest.TestCase) -> Path:
    """Create an isolated bare repo outside the main working tree.

    Returns the bare path and registers cleanup on *test_case*.
    Using a separate tempdir keeps the bare repo out of the main working
    tree so commands like clean-rebase do not see it as untracked files.
    """
    bare_tmp = _make_tempdir()
    test_case.addCleanup(bare_tmp.cleanup)
    return _make_bare(Path(bare_tmp.name).resolve())


def _bare_workspace(test_case: unittest.TestCase) -> Path:
    """Return a fresh tempdir for staging submodule bare repos."""
    tmp = _make_tempdir()
    test_case.addCleanup(tmp.cleanup)
    return Path(tmp.name).resolve()


def _make_submodule_source(workspace: Path, name: str) -> Path:
    """Return a bare repo at ``workspace/<name>-bare.git`` seeded with one commit.

    Needed for ``git submodule add`` (the source must have at least one
    commit on the default branch) and so that ``ishproject init --create``
    inside the submodule can push its orphan branch back.
    """
    bare = workspace / f"{name}-bare.git"
    bare.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    scratch = workspace / f"{name}-scratch"
    scratch.mkdir()
    _init_repo(scratch)
    _git("remote", "add", "origin", str(bare), cwd=scratch)
    _git("push", "origin", "main", cwd=scratch)
    return bare


def _add_submodule(parent: Path, url: Path, sub_path: str) -> None:
    """Run ``git submodule add <url> <sub_path>`` in *parent* and commit."""
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            "submodule",
            "add",
            str(url),
            sub_path,
        ],
        cwd=str(parent),
        check=True,
        capture_output=True,
        text=True,
    )
    _git("commit", "-m", f"add submodule {sub_path}", cwd=parent)


class TestInit(_ChdirTestCase):
    """Tests for ``ishproject init``.

    ``conftest.py`` redirects ``$HOME`` to a per-session temp dir so the
    branch name always resolves to the library default
    (``ishlib/ishproject``) regardless of the developer's real
    ``~/.config/ishlib/ishproject.toml``.
    """

    def setUp(self) -> None:
        super().setUp()
        # Shared bare remote for tests that need one.
        self.bare = _setup_bare_remote(self)

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

    def test_init_missing_branch_without_create_errors(self) -> None:
        # No branch and no --create → rc=1 (no remote origin configured in
        # the fresh tempdir repo, and we're non-interactive).
        _init_repo(self.root)
        rc = cli_main(["init"])
        self.assertEqual(rc, 1)
        self.assertFalse((self.root / ".ishlib" / "ishproject").exists())

    def test_init_create_pushes_to_configured_remote(self) -> None:
        _init_repo(self.root)
        rc = cli_main(["init", "--create", "--remote", str(self.bare)])
        self.assertEqual(rc, 0)
        worktree = self.root / ".ishlib" / "ishproject"
        self.assertTrue(worktree.is_dir())
        branches = _git("branch", "--list", cwd=self.root).stdout
        self.assertIn(ISHPROJECT_BRANCH, branches)
        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.ishlib/", exclude)
        # Branch must have been pushed to the bare remote.
        remote_refs = subprocess.run(
            ["git", "ls-remote", "--heads", str(self.bare)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn(ISHPROJECT_BRANCH, remote_refs)

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

    def test_init_auto_tracks_remote_branch(self) -> None:
        # Set up: bare remote has the branch; clone has no local branch.
        _init_repo(self.root)
        _git("remote", "add", "origin", str(self.bare), cwd=self.root)
        # Seed the bare with the ishproject branch via a scratch repo.
        scratch_tmp = _make_tempdir()
        self.addCleanup(scratch_tmp.cleanup)
        scratch = Path(scratch_tmp.name).resolve()
        scratch.mkdir(exist_ok=True)
        _init_repo(scratch)
        _git("remote", "add", "origin", str(self.bare), cwd=scratch)
        _git("branch", ISHPROJECT_BRANCH, cwd=scratch)
        _git("push", "origin", ISHPROJECT_BRANCH, cwd=scratch)
        # init should auto-track the remote branch.
        rc = cli_main(["init"])
        self.assertEqual(rc, 0)
        worktree = self.root / ".ishlib" / "ishproject"
        self.assertTrue(worktree.is_dir())
        branches = _git("branch", "--list", cwd=self.root).stdout
        self.assertIn(ISHPROJECT_BRANCH, branches)

    def test_init_remote_flag_url_adds_ishproject_remote(self) -> None:
        _init_repo(self.root)
        rc = cli_main(["init", "--create", "--remote", str(self.bare)])
        self.assertEqual(rc, 0)
        remotes = _git("remote", cwd=self.root).stdout
        self.assertIn("ishproject", remotes)
        url = _git("remote", "get-url", "ishproject", cwd=self.root).stdout.strip()
        self.assertEqual(url, str(self.bare))

    def test_init_remote_flag_url_idempotent_when_ishproject_same_url(self) -> None:
        # Running init twice with the same URL must not error on the second run.
        _init_repo(self.root)
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)
        # Second init: source dir already exists → idempotent no-op.
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)

    def test_init_remote_flag_url_conflict_errors(self) -> None:
        # Pre-existing `ishproject` remote with a different URL → error.
        _init_repo(self.root)
        other_bare = _make_bare(self.root / "other")
        _git("remote", "add", "ishproject", str(other_bare), cwd=self.root)
        rc = cli_main(["init", "--create", "--remote", str(self.bare)])
        self.assertEqual(rc, 1)
        # No worktree should have been created.
        self.assertFalse((self.root / ".ishlib" / "ishproject").is_dir())

    def test_init_fetch_failure_aborts(self) -> None:
        # A remote that doesn't resolve → fetch fails → rc=1, no worktree.
        _init_repo(self.root)
        _git("remote", "add", "origin", "/nonexistent/path.git", cwd=self.root)
        rc = cli_main(["init"])
        self.assertEqual(rc, 1)
        self.assertFalse((self.root / ".ishlib" / "ishproject").is_dir())

    def test_init_default_does_not_apply(self) -> None:
        # Without --apply, ishfiles_main must not be invoked.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["init"])
        self.assertEqual(rc, 0)
        mock_main.assert_not_called()

    def test_init_apply_forwards_to_ishfiles(self) -> None:
        # --apply on a seeded local branch forwards to ishfiles apply
        # with --source / --target pointing at the worktree.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["init", "--apply"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertIn("--source", argv)
        self.assertIn("--target", argv)
        self.assertIn("apply", argv)
        worktree = str(self.root / ".ishlib" / "ishproject")
        self.assertIn(worktree, argv)

    def test_init_apply_on_orphan_create(self) -> None:
        # --create + --apply on a fresh repo: worktree is empty, but the
        # apply passthrough still fires (it's a no-op at the ishfiles
        # layer, not ishproject's concern).
        _init_repo(self.root)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["init", "--create", "--remote", str(self.bare), "--apply"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()

    def test_init_apply_dry_run_skips(self) -> None:
        # Dry-run init does not create the worktree, so --apply is skipped.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["init", "--apply", "--dry-run"])
        self.assertEqual(rc, 0)
        mock_main.assert_not_called()

    def test_init_apply_failure_propagates(self) -> None:
        # Non-zero exit from ishfiles apply must bubble out of init.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=2,
        ):
            rc = cli_main(["init", "--apply"])
        self.assertEqual(rc, 2)

    def test_init_apply_idempotent_reruns(self) -> None:
        # Second init --apply hits the "already initialised" path and
        # must still dispatch to apply.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            self.assertEqual(cli_main(["init", "--apply"]), 0)
            self.assertEqual(cli_main(["init", "--apply"]), 0)
        self.assertEqual(mock_main.call_count, 2)

    def test_init_apply_forwards_debug_and_log_file(self) -> None:
        # --debug / --log-file on init must also flow into the nested
        # ishfiles apply invocation so its setup_logging() keeps the
        # same verbosity and file sink.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        log_path = self.root / "init-apply.log"
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["init", "--apply", "--debug", "--log-file", str(log_path)])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        self.assertIn("--debug", argv)
        self.assertIn("--log-file", argv)
        self.assertIn(str(log_path), argv)

    # ---- --recurse-submodules ---------------------------------------------

    def test_init_no_recurse_skips_submodule(self) -> None:
        _init_repo(self.root)
        workspace = _bare_workspace(self)
        child_bare = _make_submodule_source(workspace, "child")
        _add_submodule(self.root, child_bare, "child")

        rc = cli_main(["init", "--create", "--remote", str(self.bare)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".ishlib" / "ishproject").is_dir())
        self.assertFalse((self.root / "child" / ".ishlib" / "ishproject").exists())

    def test_init_recurse_submodules_inits_child(self) -> None:
        _init_repo(self.root)
        workspace = _bare_workspace(self)
        child_bare = _make_submodule_source(workspace, "child")
        _add_submodule(self.root, child_bare, "child")

        rc = cli_main(
            [
                "init",
                "--create",
                "--remote",
                str(self.bare),
                "--recurse-submodules",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".ishlib" / "ishproject").is_dir())
        self.assertTrue((self.root / "child" / ".ishlib" / "ishproject").is_dir())
        # Submodule's real git dir lives under the parent's .git/modules/.
        sub_exclude = self.root / ".git" / "modules" / "child" / "info" / "exclude"
        self.assertTrue(sub_exclude.is_file())
        self.assertIn("/.ishlib/", sub_exclude.read_text(encoding="utf-8"))

    def test_init_recurse_remote_not_propagated(self) -> None:
        # Parent pushes to self.bare; submodule must push to ITS OWN bare,
        # not the parent's bare.
        _init_repo(self.root)
        workspace = _bare_workspace(self)
        child_bare = _make_submodule_source(workspace, "child")
        _add_submodule(self.root, child_bare, "child")

        rc = cli_main(
            [
                "init",
                "--create",
                "--remote",
                str(self.bare),
                "--recurse-submodules",
            ]
        )
        self.assertEqual(rc, 0)

        parent_refs = subprocess.run(
            ["git", "ls-remote", "--heads", str(self.bare)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        child_refs = subprocess.run(
            ["git", "ls-remote", "--heads", str(child_bare)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        # The ishproject branch landed on the child's own bare …
        self.assertIn(ISHPROJECT_BRANCH, child_refs)
        # … not the parent's. ls-remote on self.bare should have the
        # branch (parent's), so assert it did NOT leak to child from
        # parent's bare: the child's bare is a separate file, so we
        # check the *child* bare has the branch AND the child has no
        # "ishproject" remote pointing at self.bare (--remote was not
        # forwarded).
        self.assertIn(ISHPROJECT_BRANCH, parent_refs)
        child_wt = self.root / "child"
        child_remotes = _git("remote", cwd=child_wt).stdout.split()
        self.assertNotIn("ishproject", child_remotes)

    def test_init_recurse_nested_submodules(self) -> None:
        _init_repo(self.root)
        workspace = _bare_workspace(self)
        grandchild_bare = _make_submodule_source(workspace, "grandchild")
        child_bare = _make_submodule_source(workspace, "child")

        # Register grandchild as a submodule inside child-bare by working
        # through a scratch clone and pushing back.
        child_scratch = workspace / "child-nest-scratch"
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "clone",
                str(child_bare),
                str(child_scratch),
            ],
            check=True,
            capture_output=True,
        )
        _add_submodule(child_scratch, grandchild_bare, "grandchild")
        _git("push", "origin", "main", cwd=child_scratch)

        _add_submodule(self.root, child_bare, "child")
        # `submodule add` initialises the first level only; recurse into
        # nested submodules explicitly.
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "update",
                "--init",
                "--recursive",
            ],
            cwd=str(self.root),
            check=True,
            capture_output=True,
        )

        rc = cli_main(
            [
                "init",
                "--create",
                "--remote",
                str(self.bare),
                "--recurse-submodules",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".ishlib" / "ishproject").is_dir())
        self.assertTrue((self.root / "child" / ".ishlib" / "ishproject").is_dir())
        self.assertTrue(
            (self.root / "child" / "grandchild" / ".ishlib" / "ishproject").is_dir()
        )

    def test_init_missing_branch_standalone_still_errors(self) -> None:
        # Remote exists, fetch succeeds, branch doesn't exist on remote, no
        # --create.  Standalone (non-recurse) callers should still see a
        # non-zero exit so they can script around it.
        _init_repo(self.root)
        _git("remote", "add", "origin", str(self.bare), cwd=self.root)
        rc = cli_main(["init"])
        self.assertEqual(rc, 1)
        self.assertFalse((self.root / ".ishlib" / "ishproject").exists())

    def test_init_recurse_missing_branch_skips_submodule(self) -> None:
        # Parent already has the branch locally (no --create needed).  The
        # submodule has a working remote but no ishproject branch on it.
        # Recursion should classify the submodule as "not configured" and
        # exit 0 without flagging it as a failure.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        workspace = _bare_workspace(self)
        child_bare = _make_submodule_source(workspace, "child")
        _add_submodule(self.root, child_bare, "child")

        with self.assertLogs("pyishlib.ishproject.commands.init", level="INFO") as cm:
            rc = cli_main(["init", "--recurse-submodules"])

        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".ishlib" / "ishproject").is_dir())
        # Submodule was NOT initialised (no branch, no --create).
        self.assertFalse((self.root / "child" / ".ishlib" / "ishproject").exists())
        joined = "\n".join(cm.output)
        # No "failed in" message — the submodule was skipped, not failed.
        self.assertNotIn("ishproject init failed in", joined)
        # The summary message names the skipped repo.
        self.assertIn("ishproject not configured", joined)
        self.assertIn("child", joined)

    def test_init_recurse_mixed_skip_and_fail(self) -> None:
        # Two submodules: one missing the branch (soft skip), one with a
        # broken origin (hard fail).  Expect rc=1 with only the broken one
        # reported as a failure.
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        workspace = _bare_workspace(self)
        skip_bare = _make_submodule_source(workspace, "skip")
        broken_bare = _make_submodule_source(workspace, "broken")
        _add_submodule(self.root, skip_bare, "skip")
        _add_submodule(self.root, broken_bare, "broken")
        _git(
            "remote",
            "set-url",
            "origin",
            "/nonexistent/path.git",
            cwd=self.root / "broken",
        )

        with self.assertLogs("pyishlib.ishproject.commands.init", level="INFO") as cm:
            rc = cli_main(["init", "--recurse-submodules"])

        self.assertEqual(rc, 1)
        joined = "\n".join(cm.output)
        # The broken submodule appears in the failure summary.
        self.assertIn("ishproject init failed in", joined)
        self.assertIn("broken", joined)
        # The skip submodule appears in the skip summary, not the failure summary.
        self.assertIn("ishproject not configured", joined)
        self.assertIn("skip", joined)

    def test_init_error_messages_include_repo_path(self) -> None:
        # Fetch failure path: the message must include a tag identifying
        # which repo it concerns.
        _init_repo(self.root)
        _git("remote", "add", "origin", "/nonexistent/path.git", cwd=self.root)
        with self.assertLogs("pyishlib.ishproject.commands.init", level="ERROR") as cm:
            rc = cli_main(["init"])
        self.assertEqual(rc, 1)
        joined = "\n".join(cm.output)
        self.assertIn("Failed to fetch", joined)
        # The bracketed tag is either "[.]" (relative-to-cwd) or "[<abspath>]".
        self.assertTrue(
            "[.]" in joined or f"[{self.root}]" in joined,
            f"expected repo tag in: {joined!r}",
        )

    def test_init_recurse_continues_past_submodule_failure(self) -> None:
        # Two submodules. The first has its origin URL pointed at a
        # nonexistent path so its fetch fails; the second is healthy.
        # The failure must not prevent the second from being initialised.
        _init_repo(self.root)
        workspace = _bare_workspace(self)
        broken_bare = _make_submodule_source(workspace, "broken")
        healthy_bare = _make_submodule_source(workspace, "healthy")
        _add_submodule(self.root, broken_bare, "broken")
        _add_submodule(self.root, healthy_bare, "healthy")

        # Break the first submodule's origin by repointing it at a dead
        # path. `ishproject init --create` on it will still try to fetch
        # (because --create falls through to the remote path) and abort.
        _git(
            "remote",
            "set-url",
            "origin",
            "/nonexistent/path.git",
            cwd=self.root / "broken",
        )

        rc = cli_main(
            [
                "init",
                "--create",
                "--remote",
                str(self.bare),
                "--recurse-submodules",
            ]
        )
        self.assertEqual(rc, 1)
        # Parent and the healthy submodule still got inited.
        self.assertTrue((self.root / ".ishlib" / "ishproject").is_dir())
        self.assertTrue((self.root / "healthy" / ".ishlib" / "ishproject").is_dir())
        # The broken submodule did not.
        self.assertFalse((self.root / "broken" / ".ishlib" / "ishproject").exists())


# ---------------------------------------------------------------------------
# Helpers for merge / clean-rebase tests
# ---------------------------------------------------------------------------


def _seed_managed_file(root: Path, rel: str, content: str) -> None:
    """Commit ``rel`` onto ish/ishproject, apply it, and exclude it.

    Mirrors the end state of ``ishproject add`` + ``ishproject apply``
    without depending on ``ishfiles`` being wired up in the test.
    """
    source = root / ".ishlib" / "ishproject"
    src_file = source / rel
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text(content)
    _git("add", rel, cwd=source)
    _git("commit", "-m", f"add {rel}", cwd=source)
    tgt = root / rel
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text(content)
    # Mirror what `ishproject add` would do: append the per-file
    # pattern to `.git/info/exclude` so the managed copy is hidden
    # from `git status` in the main worktree.
    excl = root / ".git" / "info" / "exclude"
    excl.parent.mkdir(parents=True, exist_ok=True)
    with excl.open("a", encoding="utf-8") as fh:
        fh.write(f"/{rel}\n")


def _simulate_apply(argv) -> int:
    """Stand-in for ishfiles_main used by clean-rebase tests.

    Copies every file tracked in the source worktree into the target
    tree, which is all that ``ishfiles apply`` needs to do for these
    tests (no preprocessing, no packages, no scripts).
    """
    i = argv.index("--source")
    source = Path(argv[i + 1])
    i = argv.index("--target")
    target = Path(argv[i + 1])
    result = subprocess.run(
        ["git", "-C", str(source), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    for rel in result.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        src_file = source / rel
        if not src_file.is_file():
            continue
        dst_file = target / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_bytes(src_file.read_bytes())
    return 0


class TestMerge(_ChdirTestCase):
    def setUp(self) -> None:
        super().setUp()
        p = patch(
            "pyishlib.ishproject.cli.load_config",
            return_value=_DEFAULT_CFG,
        )
        p.start()
        self.addCleanup(p.stop)
        _init_repo(self.root)
        self.bare = _setup_bare_remote(self)
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)

    def test_merge_removes_exclude_and_commits(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        rc = cli_main(["merge"])
        self.assertEqual(rc, 0)

        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/.ishlib/", exclude)
        self.assertNotIn("/foo.txt", exclude)

        show = _git("show", "--name-only", "--pretty=", "HEAD", cwd=self.root).stdout
        self.assertIn("foo.txt", show)
        head_msg = _git("log", "-1", "--pretty=%s", cwd=self.root).stdout.strip()
        self.assertEqual(head_msg, "ishproject: merge managed files")

    def test_merge_custom_message(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        rc = cli_main(["merge", "-m", "custom subject"])
        self.assertEqual(rc, 0)
        head_msg = _git("log", "-1", "--pretty=%s", cwd=self.root).stdout.strip()
        self.assertEqual(head_msg, "custom subject")

    def test_merge_no_managed_files_noop(self) -> None:
        # init --create left the source with only the "Initialise" empty
        # commit; ls-files is empty.
        pre = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        rc = cli_main(["merge"])
        self.assertEqual(rc, 0)
        post = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.assertEqual(pre, post)

    def test_merge_must_run_at_repo_root(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        sub = self.root / "sub"
        sub.mkdir()
        os.chdir(sub)
        rc = cli_main(["merge"])
        self.assertEqual(rc, 1)

    def test_merge_restores_excludes_when_commit_fails(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        excl_path = self.root / ".git" / "info" / "exclude"
        excl_before = excl_path.read_text(encoding="utf-8")
        self.assertIn("/foo.txt", excl_before)

        # Force `git commit` to fail by making the commit author invalid.
        import pyishlib.command_runner as command_runner_mod

        real_git = command_runner_mod.CommandRunner.git

        def fake_git(self, command, work_dir=None, **kwargs):
            cmd = list(command)
            if "commit" in cmd and "-m" in cmd:
                raise subprocess.CalledProcessError(1, ["git", *cmd])
            return real_git(self, command, work_dir=work_dir, **kwargs)

        with patch.object(command_runner_mod.CommandRunner, "git", fake_git):
            rc = cli_main(["merge"])

        self.assertEqual(rc, 1)
        excl_after = excl_path.read_text(encoding="utf-8")
        self.assertIn("/foo.txt", excl_after)
        self.assertIn("/.ishlib/", excl_after)


class TestCleanRebase(_ChdirTestCase):
    def setUp(self) -> None:
        super().setUp()
        _init_repo(self.root)
        self.bare = _setup_bare_remote(self)
        self.base_sha = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)

    def _run_clean_rebase(self, *extra: str) -> int:
        with patch(
            "pyishlib.ishproject.commands.clean_rebase.ishfiles_main",
            side_effect=_simulate_apply,
        ):
            return cli_main(["clean-rebase", self.base_sha, *extra])

    def test_clean_rebase_strips_files_from_history(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)
        (self.root / "bar.txt").write_text("bar\n")
        _git("add", "bar.txt", cwd=self.root)
        _git("commit", "-m", "add bar", cwd=self.root)

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 0)

        log_out = _git("log", "--name-only", "--pretty=format:", cwd=self.root).stdout
        self.assertNotIn("foo.txt", log_out)
        self.assertIn("bar.txt", log_out)

    def test_clean_rebase_restores_working_tree(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 0)

        self.assertTrue((self.root / "foo.txt").is_file())
        exclude = (self.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/foo.txt", exclude)
        self.assertIn("/.ishlib/", exclude)

    def test_clean_rebase_syncs_edits_to_ishproject(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "A\n")
        self.assertEqual(cli_main(["merge"]), 0)
        (self.root / "foo.txt").write_text("B\n")
        _git("add", "foo.txt", cwd=self.root)
        _git("commit", "-m", "edit foo", cwd=self.root)

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 0)

        source = self.root / ".ishlib" / "ishproject"
        self.assertEqual((source / "foo.txt").read_text(), "B\n")
        tree = _git("ls-tree", "-r", "--name-only", "HEAD", cwd=self.root).stdout
        self.assertNotIn("foo.txt", tree)
        self.assertEqual((self.root / "foo.txt").read_text(), "B\n")
        last_msg = _git("log", "-1", "--pretty=%s", cwd=source).stdout.strip()
        self.assertTrue(last_msg.startswith("ishproject: sync edits from "))

    def test_clean_rebase_no_sync_flag_skips_phase2(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "A\n")
        self.assertEqual(cli_main(["merge"]), 0)
        (self.root / "foo.txt").write_text("B\n")
        _git("add", "foo.txt", cwd=self.root)
        _git("commit", "-m", "edit foo", cwd=self.root)

        source = self.root / ".ishlib" / "ishproject"
        source_head_before = _git("rev-parse", "HEAD", cwd=source).stdout.strip()

        rc = self._run_clean_rebase("--no-sync-ishproject")
        self.assertEqual(rc, 0)

        # ish/ishproject untouched; edits to "B" are lost.
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=source).stdout.strip(),
            source_head_before,
        )
        # _simulate_apply restores from source → "A".
        self.assertEqual((self.root / "foo.txt").read_text(), "A\n")

    def test_clean_rebase_no_upstream_is_local_only(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "A\n")
        self.assertEqual(cli_main(["merge"]), 0)
        (self.root / "foo.txt").write_text("B\n")
        _git("add", "foo.txt", cwd=self.root)
        _git("commit", "-m", "edit foo", cwd=self.root)

        source = self.root / ".ishlib" / "ishproject"
        pre_count = len(_git("rev-list", "HEAD", cwd=source).stdout.splitlines())

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 0)

        post_count = len(_git("rev-list", "HEAD", cwd=source).stdout.splitlines())
        self.assertEqual(post_count, pre_count + 1)

    def test_clean_rebase_upstream_conflict_rolls_back(self) -> None:
        # The ishproject worktree already has an `ishproject` remote pointing
        # at self.bare (set up by init --create in setUp).  Clone from
        # self.bare to create a divergent commit on the remote.
        source = self.root / ".ishlib" / "ishproject"

        _seed_managed_file(self.root, "foo.txt", "A\n")
        # Push the "A" commit to self.bare.
        _git("push", "ishproject", ISHPROJECT_BRANCH, cwd=source)
        self.assertEqual(cli_main(["merge"]), 0)

        (self.root / "foo.txt").write_text("B\n")
        _git("add", "foo.txt", cwd=self.root)
        _git("commit", "-m", "edit foo", cwd=self.root)

        # Create a divergent commit on self.bare via a clone.
        with _make_tempdir() as clone_dir:
            clone = Path(clone_dir).resolve()
            subprocess.run(
                ["git", "clone", str(self.bare), str(clone)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "-C",
                    str(clone),
                    "checkout",
                    ISHPROJECT_BRANCH,
                ],
                check=True,
                capture_output=True,
            )
            (clone / "foo.txt").write_text("C\n")
            subprocess.run(
                ["git", "-C", str(clone), "add", "foo.txt"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "tag.gpgsign=false",
                    "-C",
                    str(clone),
                    "commit",
                    "-m",
                    "remote edit",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(clone), "push"],
                check=True,
                capture_output=True,
            )

        main_head_before = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        source_head_before = _git("rev-parse", "HEAD", cwd=source).stdout.strip()

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 1)
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=self.root).stdout.strip(),
            main_head_before,
        )
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=source).stdout.strip(),
            source_head_before,
        )

    def test_clean_rebase_creates_backup_ref(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)
        head_before = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 0)

        refs = _git(
            "for-each-ref",
            "--format=%(refname)",
            "refs/ishproject/",
            cwd=self.root,
        ).stdout
        self.assertTrue(any("clean-rebase-backup-" in ln for ln in refs.splitlines()))
        # Backup ref points at pre-rewrite HEAD.
        backup_line = next(
            ln for ln in refs.splitlines() if "clean-rebase-backup-" in ln
        )
        backup_sha = _git("rev-parse", backup_line, cwd=self.root).stdout.strip()
        self.assertEqual(backup_sha, head_before)

    def test_clean_rebase_refuses_merge_commits(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)
        # Create a merge commit in the range.
        _git("checkout", "-b", "side", cwd=self.root)
        (self.root / "side.txt").write_text("side")
        _git("add", "side.txt", cwd=self.root)
        _git("commit", "-m", "side commit", cwd=self.root)
        _git("checkout", "main", cwd=self.root)
        _git(
            "merge",
            "--no-ff",
            "-m",
            "merge side",
            "side",
            cwd=self.root,
        )

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 1)

    def test_clean_rebase_refuses_dirty_worktree(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)
        # Dirty, unrelated file.
        (self.root / "dirty.txt").write_text("dirty")
        _git("add", "dirty.txt", cwd=self.root)

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 1)

    def test_clean_rebase_refuses_uncommitted_managed_edit(self) -> None:
        # Uncommitted edits to managed files would be silently wiped by
        # the reset --hard in phase 3. Refuse up front.
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)
        (self.root / "foo.txt").write_text("modified\n")

        rc = self._run_clean_rebase()
        self.assertEqual(rc, 1)
        self.assertEqual((self.root / "foo.txt").read_text(), "modified\n")

    def test_clean_rebase_invalid_base_returns_1(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)
        with patch(
            "pyishlib.ishproject.commands.clean_rebase.ishfiles_main",
            side_effect=_simulate_apply,
        ):
            rc = cli_main(["clean-rebase", "definitely-not-a-ref"])
        self.assertEqual(rc, 1)

    def test_clean_rebase_forwards_common_flags_to_apply(self) -> None:
        _seed_managed_file(self.root, "foo.txt", "hello\n")
        self.assertEqual(cli_main(["merge"]), 0)

        captured: list = []

        def capture_apply(argv):
            captured.append(list(argv))
            return _simulate_apply(argv)

        with patch(
            "pyishlib.ishproject.commands.clean_rebase.ishfiles_main",
            side_effect=capture_apply,
        ):
            rc = cli_main(["clean-rebase", "--verbose", self.base_sha])
        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        self.assertIn("--verbose", captured[0])


class TestConfigLoad(unittest.TestCase):
    """Cover load / prompt / save of ~/.config/ishlib/ishproject.toml."""

    def setUp(self) -> None:
        self._tmp = _make_tempdir()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "ishproject.toml"

    def test_missing_file_noninteractive_returns_defaults(self) -> None:
        from pyishlib.ishproject.config import load_config

        cfg = load_config(self.config_path, interactive=False)
        self.assertEqual(cfg.get_opt("prefix"), DEFAULT_PREFIX)
        self.assertEqual(cfg.get_opt("postfix"), DEFAULT_POSTFIX)
        self.assertEqual(cfg.get_opt("config_file"), self.config_path)
        self.assertFalse(self.config_path.is_file())

    def test_existing_file_is_parsed(self) -> None:
        from pyishlib.ishproject.config import load_config

        self.config_path.write_text(
            '[ishproject]\nprefix = "myish"\npostfix = "proj"\n',
            encoding="utf-8",
        )
        cfg = load_config(self.config_path, interactive=False)
        self.assertEqual(cfg.get_opt("prefix"), "myish")
        self.assertEqual(cfg.get_opt("postfix"), "proj")

    def test_prompt_writes_file(self) -> None:
        from pyishlib import ish_config as ish_config_mod
        from pyishlib.ishproject import config as cfg_mod

        with patch.object(
            ish_config_mod, "prompt_string", side_effect=["my", "dotfiles"]
        ):
            cfg = cfg_mod.load_config(self.config_path, interactive=True)
        self.assertEqual(cfg.get_opt("prefix"), "my")
        self.assertEqual(cfg.get_opt("postfix"), "dotfiles")
        self.assertTrue(self.config_path.is_file())
        text = self.config_path.read_text(encoding="utf-8")
        self.assertIn('prefix = "my"', text)
        self.assertIn('postfix = "dotfiles"', text)

    def test_prompt_escapes_toml_unsafe_values(self) -> None:
        # TOML string-literal hazards: quote, backslash, newline. The
        # write must escape them so the next load succeeds.
        from pyishlib import ish_config as ish_config_mod
        from pyishlib.ishproject import config as cfg_mod

        hazardous_prefix = 'weird"\\name'
        hazardous_postfix = "has\nnewline"
        with patch.object(
            ish_config_mod,
            "prompt_string",
            side_effect=[hazardous_prefix, hazardous_postfix],
        ):
            cfg_mod.load_config(self.config_path, interactive=True)

        # Round-trip: the value read back matches what the user typed.
        cfg = cfg_mod.load_config(self.config_path, interactive=False)
        self.assertEqual(cfg.get_opt("prefix"), hazardous_prefix)
        self.assertEqual(cfg.get_opt("postfix"), hazardous_postfix)

    def test_write_is_atomic(self) -> None:
        # After a successful write, no sibling .tmp file should remain.
        from pyishlib import ish_config as ish_config_mod
        from pyishlib.ishproject import config as cfg_mod

        with patch.object(ish_config_mod, "prompt_string", side_effect=["a", "b"]):
            cfg_mod.load_config(self.config_path, interactive=True)
        tmp = self.config_path.with_name(f".{self.config_path.name}.tmp")
        self.assertFalse(tmp.exists())


class TestResolveBranch(unittest.TestCase):
    """Unit-test the branch-exists callback dispatch in IshprojectConfig."""

    def setUp(self) -> None:
        self.cfg = IshprojectConfig(
            defaults={"prefix": "pre", "postfix": "post"},
        )

    def test_branch_specific_used_when_present(self) -> None:
        existing = {"pre/main/post"}
        name = self.cfg.resolve_branch(lambda b: b in existing, current_branch="main")
        self.assertEqual(name, "pre/main/post")

    def test_falls_back_when_branch_specific_missing(self) -> None:
        name = self.cfg.resolve_branch(lambda b: False, current_branch="main")
        self.assertEqual(name, "pre/post")

    def test_detached_head_uses_default(self) -> None:
        name = self.cfg.resolve_branch(lambda b: True, current_branch=None)
        self.assertEqual(name, "pre/post")


class TestBranchCommand(_ChdirTestCase):
    """Integration coverage for `ishproject branch`."""

    def setUp(self) -> None:
        super().setUp()
        p = patch(
            "pyishlib.ishproject.cli.load_config",
            return_value=_DEFAULT_CFG,
        )
        p.start()
        self.addCleanup(p.stop)
        _init_repo(self.root)
        self.bare = _setup_bare_remote(self)
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)

    def test_branch_requires_repo(self) -> None:
        with _make_tempdir() as plain:
            os.chdir(plain)
            try:
                rc = cli_main(["branch"])
            finally:
                os.chdir(self.root)
        self.assertEqual(rc, 1)

    def test_branch_creates_orphan_worktree(self) -> None:
        rc = cli_main(["branch"])
        self.assertEqual(rc, 0)
        expected_branch = f"{DEFAULT_PREFIX}/main/{DEFAULT_POSTFIX}"
        branches = _git("branch", "--list", cwd=self.root).stdout
        self.assertIn(expected_branch, branches)
        ishlib_dir = self.root / ".ishlib"
        matches = [
            p for p in ishlib_dir.iterdir() if p.name.startswith("ishproject-main-")
        ]
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].is_dir())

    def test_branch_detached_head_is_rejected(self) -> None:
        head = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        _git("checkout", "--detach", head, cwd=self.root)
        rc = cli_main(["branch"])
        self.assertEqual(rc, 1)

    def test_branch_idempotent_when_worktree_exists(self) -> None:
        self.assertEqual(cli_main(["branch"]), 0)
        # Running twice should not fail.
        self.assertEqual(cli_main(["branch"]), 0)


class TestDynamicBranchResolution(_ChdirTestCase):
    """End-to-end: apply picks branch-specific worktree when one exists."""

    def setUp(self) -> None:
        super().setUp()
        p = patch(
            "pyishlib.ishproject.cli.load_config",
            return_value=_DEFAULT_CFG,
        )
        p.start()
        self.addCleanup(p.stop)
        _init_repo(self.root)
        self.bare = _setup_bare_remote(self)
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)

    def test_apply_uses_branch_specific_worktree(self) -> None:
        self.assertEqual(cli_main(["branch"]), 0)
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["apply"])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        src_idx = argv.index("--source")
        src = argv[src_idx + 1]
        self.assertIn("/.ishlib/ishproject-main-", src)

    def test_apply_uses_default_when_no_branch_variant(self) -> None:
        # no `ishproject branch` run -> apply should hit the default worktree.
        with patch(
            "pyishlib.ishproject.commands.apply.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["apply"])
        self.assertEqual(rc, 0)
        argv = mock_main.call_args.args[0]
        src_idx = argv.index("--source")
        self.assertTrue(argv[src_idx + 1].endswith(".ishlib/ishproject"))


class TestStatusPassthrough(_ChdirTestCase):
    def test_missing_source_returns_1(self) -> None:
        with patch("pyishlib.ishproject.commands.status.ishfiles_main") as mock_main:
            rc = cli_main(["status"])
        self.assertEqual(rc, 1)
        mock_main.assert_not_called()

    def test_passthrough_invokes_ishfiles_status(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertIn("--source", argv)
        self.assertIn("--target", argv)
        self.assertIn("status", argv)
        self.assertLess(argv.index("--source"), argv.index("status"))
        self.assertIn("--include-ignored", argv)
        self.assertGreater(argv.index("--include-ignored"), argv.index("status"))


class TestStatusSubmoduleRecursion(_ChdirTestCase):
    """`ishproject status` recurses automatically into submodules.

    Each submodule is reported only when the underlying git submodule is
    initialised AND its locally-known refs include the ishproject branch.
    No fetches are performed.
    """

    def _add_initialised_submodule(self, name: str) -> Path:
        """Create a submodule wired up under ``self.root`` and return its path."""
        workspace = _bare_workspace(self)
        bare = _make_submodule_source(workspace, name)
        _add_submodule(self.root, bare, name)
        return self.root / name

    def test_recurses_into_submodule_with_branch_and_worktree(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)

        sub = self._add_initialised_submodule("child")
        _git("branch", ISHPROJECT_BRANCH, cwd=sub)
        (sub / ".ishlib" / "ishproject").mkdir(parents=True)

        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        self.assertEqual(mock_main.call_count, 2)

        sources = []
        for call in mock_main.call_args_list:
            argv = call.args[0]
            sources.append(argv[argv.index("--source") + 1])
        self.assertIn(str(self.root / ".ishlib" / "ishproject"), sources)
        self.assertIn(str(sub / ".ishlib" / "ishproject"), sources)

    def test_skips_submodule_without_ishproject_branch(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)

        # Submodule has no ishproject branch and no worktree.
        self._add_initialised_submodule("child")

        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertEqual(
            argv[argv.index("--source") + 1],
            str(self.root / ".ishlib" / "ishproject"),
        )

    def test_includes_uninitialized_submodule_with_branch(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)

        sub = self._add_initialised_submodule("child")
        # Branch exists, but no `.ishlib/ishproject` worktree.
        _git("branch", ISHPROJECT_BRANCH, cwd=sub)

        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ) as mock_main:
            with self.assertLogs(
                "pyishlib.ishproject.commands.status", level="INFO"
            ) as cm:
                rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        # Parent only — submodule has no worktree to status against.
        mock_main.assert_called_once()
        # …but the submodule was surfaced in an info log.
        joined = "\n".join(cm.output)
        self.assertIn(str(sub), joined)
        self.assertIn(ISHPROJECT_BRANCH, joined)
        self.assertIn("worktree not initialized", joined)

    def test_no_header_when_only_parent_reports(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        # Submodule has no ishproject branch — no section, no header.
        self._add_initialised_submodule("child")

        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ):
            from io import StringIO

            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        self.assertNotIn("===", buf.getvalue())

    def test_header_emitted_when_submodule_reports(self) -> None:
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)

        sub = self._add_initialised_submodule("child")
        _git("branch", ISHPROJECT_BRANCH, cwd=sub)
        (sub / ".ishlib" / "ishproject").mkdir(parents=True)

        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ):
            from io import StringIO

            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("=== . ===", out)
        self.assertIn("=== child ===", out)

    def test_skips_submodule_with_stale_worktree_dir_no_branch(self) -> None:
        """A leftover `.ishlib/ishproject` directory must not be reported
        when the ishproject branch has been deleted (or never existed)
        in the submodule.  Otherwise status would silently report
        against a stale worktree, contradicting the "no branch → silent
        skip" contract.
        """
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)

        sub = self._add_initialised_submodule("child")
        # Stale worktree dir present, but no ishproject branch.
        (sub / ".ishlib" / "ishproject").mkdir(parents=True)

        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ) as mock_main:
            from io import StringIO

            buf = StringIO()
            with patch("sys.stdout", buf):
                rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        # Parent only; submodule is silently skipped.
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertEqual(
            argv[argv.index("--source") + 1],
            str(self.root / ".ishlib" / "ishproject"),
        )
        # No header should be emitted (only one section, no submodule report).
        self.assertNotIn("===", buf.getvalue())

    def test_does_not_fetch_when_origin_unreachable(self) -> None:
        """Pointing the submodule's origin at a non-existent path must not break status.

        ``branch_exists`` only consults locally-known refs, so a missing
        remote should be irrelevant. This test guards against a future
        regression that would add an implicit ``git fetch`` to the
        submodule recursion path.
        """
        _init_repo(self.root)
        _git("branch", ISHPROJECT_BRANCH, cwd=self.root)
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)

        sub = self._add_initialised_submodule("child")
        _git("branch", ISHPROJECT_BRANCH, cwd=sub)
        (sub / ".ishlib" / "ishproject").mkdir(parents=True)
        # Break origin so any accidental fetch would explode.
        _git(
            "remote",
            "set-url",
            "origin",
            str(self.root / "definitely-does-not-exist.git"),
            cwd=sub,
        )

        with patch(
            "pyishlib.ishproject.commands.status.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["status"])
        self.assertEqual(rc, 0)
        # Both parent and submodule should still produce status.
        self.assertEqual(mock_main.call_count, 2)


class TestCommitPassthrough(_ChdirTestCase):
    def test_missing_source_returns_1(self) -> None:
        with patch("pyishlib.ishproject.commands.commit.ishfiles_main") as mock_main:
            rc = cli_main(["commit"])
        self.assertEqual(rc, 1)
        mock_main.assert_not_called()

    def test_passthrough_invokes_ishfiles_commit(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.commit.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["commit", "-m", "my message"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertIn("commit", argv)
        self.assertIn("-m", argv)
        self.assertIn("my message", argv)
        self.assertLess(argv.index("--source"), argv.index("commit"))

    def test_sets_pre_commit_allow_no_config(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        seen: dict[str, object] = {}

        def _capture(_argv):
            seen["during"] = os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG")
            return 0

        with patch(
            "pyishlib.ishproject.commands.commit.ishfiles_main",
            side_effect=_capture,
        ):
            rc = cli_main(["commit", "-m", "msg"])
        self.assertEqual(rc, 0)
        self.assertEqual(seen["during"], "1")
        # Restored after the call (unset in the conftest minimal env).
        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)

    def test_restores_pre_existing_pre_commit_allow_no_config(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        os.environ["PRE_COMMIT_ALLOW_NO_CONFIG"] = "0"
        try:
            with patch(
                "pyishlib.ishproject.commands.commit.ishfiles_main",
                return_value=0,
            ):
                rc = cli_main(["commit", "-m", "msg"])
            self.assertEqual(rc, 0)
            self.assertEqual(os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG"), "0")
        finally:
            os.environ.pop("PRE_COMMIT_ALLOW_NO_CONFIG", None)


class TestPushPassthrough(_ChdirTestCase):
    def test_missing_source_returns_1(self) -> None:
        with patch("pyishlib.ishproject.commands.push.ishfiles_main") as mock_main:
            rc = cli_main(["push"])
        self.assertEqual(rc, 1)
        mock_main.assert_not_called()

    def test_passthrough_invokes_ishfiles_push(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.push.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["push"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertIn("push", argv)
        self.assertLess(argv.index("--source"), argv.index("push"))


class TestPullPassthrough(_ChdirTestCase):
    def test_missing_source_returns_1(self) -> None:
        with patch("pyishlib.ishproject.commands.pull.ishfiles_main") as mock_main:
            rc = cli_main(["pull"])
        self.assertEqual(rc, 1)
        mock_main.assert_not_called()

    def test_passthrough_invokes_ishfiles_pull(self) -> None:
        (self.root / ".ishlib" / "ishproject").mkdir(parents=True)
        with patch(
            "pyishlib.ishproject.commands.pull.ishfiles_main",
            return_value=0,
        ) as mock_main:
            rc = cli_main(["pull"])
        self.assertEqual(rc, 0)
        mock_main.assert_called_once()
        argv = mock_main.call_args.args[0]
        self.assertIn("pull", argv)
        self.assertLess(argv.index("--source"), argv.index("pull"))


class TestPrecommitHelper(unittest.TestCase):
    """Direct tests for ``allow_missing_precommit_config``."""

    def setUp(self) -> None:
        # The conftest minimal env guarantees the var is unset at start.
        self.addCleanup(os.environ.pop, "PRE_COMMIT_ALLOW_NO_CONFIG", None)

    def test_sets_and_unsets(self) -> None:
        from pyishlib.ishproject._precommit import allow_missing_precommit_config

        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)
        with allow_missing_precommit_config():
            self.assertEqual(os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG"), "1")
        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)

    def test_restores_preexisting_value(self) -> None:
        from pyishlib.ishproject._precommit import allow_missing_precommit_config

        os.environ["PRE_COMMIT_ALLOW_NO_CONFIG"] = "0"
        with allow_missing_precommit_config():
            self.assertEqual(os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG"), "1")
        self.assertEqual(os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG"), "0")

    def test_restores_on_exception(self) -> None:
        from pyishlib.ishproject._precommit import allow_missing_precommit_config

        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)
        with self.assertRaises(RuntimeError):
            with allow_missing_precommit_config():
                raise RuntimeError("boom")
        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)


class TestPrecommitGuardIntegration(_ChdirTestCase):
    """Every ishproject commit on the ishproject branch is env-guarded."""

    def setUp(self) -> None:
        super().setUp()
        _init_repo(self.root)
        self.bare = _setup_bare_remote(self)

    def test_init_create_sets_env_around_orphan_creation(self) -> None:
        seen: dict[str, object] = {}

        from pyishlib.git_repo import GitRepo

        def _capture(self, path, branch, *, message):
            seen["during"] = os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG")
            # Don't actually create the worktree; the test only observes.
            # Signal failure so the subsequent push step is skipped cleanly.
            raise subprocess.CalledProcessError(1, "git")

        with patch.object(
            GitRepo, "create_orphan_worktree", autospec=True, side_effect=_capture
        ):
            rc = cli_main(["init", "--create", "--remote", str(self.bare)])
        self.assertEqual(rc, 1)
        self.assertEqual(seen["during"], "1")
        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)

    def test_branch_sets_env_around_orphan_creation(self) -> None:
        # First set up a working default worktree so the branch command can run.
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)

        seen: dict[str, object] = {}

        from pyishlib.git_repo import GitRepo

        def _capture(self, path, branch, *, message):
            seen["during"] = os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG")
            raise subprocess.CalledProcessError(1, "git")

        with patch.object(
            GitRepo, "create_orphan_worktree", autospec=True, side_effect=_capture
        ):
            rc = cli_main(["branch"])
        self.assertEqual(rc, 1)
        self.assertEqual(seen["during"], "1")
        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)

    def test_clean_rebase_sync_sets_env_around_commit(self) -> None:
        # Set up a scenario that triggers the phase-2 sync commit.
        self.assertEqual(cli_main(["init", "--create", "--remote", str(self.bare)]), 0)
        base_sha = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        _seed_managed_file(self.root, "foo.txt", "A\n")
        self.assertEqual(cli_main(["merge"]), 0)
        (self.root / "foo.txt").write_text("B\n")
        _git("add", "foo.txt", cwd=self.root)
        _git("commit", "-m", "edit foo", cwd=self.root)

        # Wrap CommandRunner.git so the flow still runs, but record the env
        # at every call that includes "commit" in argv.  Only the sync
        # commit flows through runner.git with "commit"; _rewrite_commit
        # uses the plumbing "commit-tree" form, which we filter out.
        from pyishlib.command_runner import CommandRunner

        original_git = CommandRunner.git
        env_at_commits: list[object] = []

        def _spy(self, command, work_dir=None, **kwargs):
            cmd_list = list(command)
            if "commit" in cmd_list and "commit-tree" not in cmd_list:
                env_at_commits.append(os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG"))
            return original_git(self, command, work_dir=work_dir, **kwargs)

        with (
            patch.object(CommandRunner, "git", _spy),
            patch(
                "pyishlib.ishproject.commands.clean_rebase.ishfiles_main",
                side_effect=_simulate_apply,
            ),
        ):
            rc = cli_main(["clean-rebase", base_sha])
        self.assertEqual(rc, 0)
        self.assertTrue(env_at_commits, "sync commit never reached runner.git")
        self.assertTrue(
            all(v == "1" for v in env_at_commits),
            f"PRE_COMMIT_ALLOW_NO_CONFIG was not set for every commit: {env_at_commits}",
        )
        self.assertNotIn("PRE_COMMIT_ALLOW_NO_CONFIG", os.environ)


if __name__ == "__main__":
    unittest.main()
