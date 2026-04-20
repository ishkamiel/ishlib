# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :mod:`pyishlib.git_repo`."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.git_repo import GitRepo, NotAGitRepoError  # noqa: E402

# Every test here exercises real ``git`` subprocesses against a
# ``tempfile.TemporaryDirectory``. On the Windows CI runner that
# combination is flaky (path-casing between GetFinalPathNameByHandle
# and git's output, plus read-only pack files during tempdir teardown).
# The behaviours being tested are platform-agnostic and the Linux
# matrix covers them; same pattern as test_command_runner.py.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "GitRepo tests drive real git subprocesses; Linux matrix covers "
        "the behaviour, Windows tempdir+git interaction is flaky."
    ),
)


def _make_tempdir() -> tempfile.TemporaryDirectory:
    """TemporaryDirectory that tolerates cleanup errors on Windows.

    Git stores pack files as read-only, so ``shutil.rmtree`` (the
    backing call in ``TemporaryDirectory.cleanup``) raises
    ``PermissionError`` on Windows. ``ignore_cleanup_errors`` was added
    in Python 3.10; on older versions we fall back to a plain
    TemporaryDirectory since every shell in the Linux matrix handles
    rmtree on read-only files fine.
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


def _make_repo(root: Path) -> Path:
    _git("init", "-b", "main", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    return root


class GitRepoTestCase(unittest.TestCase):
    """Shared tempdir + git repo setup."""

    def setUp(self) -> None:
        self._tmp = _make_tempdir()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        _make_repo(self.root)


class TestDiscover(GitRepoTestCase):
    def test_discover_at_repo_root(self) -> None:
        repo = GitRepo.discover(self.root)
        self.assertEqual(repo.work_tree, self.root)
        self.assertEqual(repo.git_dir, (self.root / ".git").resolve())

    def test_discover_inside_repo(self) -> None:
        sub = self.root / "sub"
        sub.mkdir()
        repo = GitRepo.discover(sub)
        self.assertEqual(repo.work_tree, self.root)

    def test_discover_require_root_rejects_subdir(self) -> None:
        sub = self.root / "sub"
        sub.mkdir()
        with self.assertRaises(NotAGitRepoError):
            GitRepo.discover(sub, require_root=True)

    def test_discover_outside_repo(self) -> None:
        with _make_tempdir() as plain:
            with self.assertRaises(NotAGitRepoError):
                GitRepo.discover(Path(plain))


class TestSubmoduleDiscovery(unittest.TestCase):
    """Verify ``git_dir`` resolves into the parent repo for a submodule."""

    def test_submodule_git_dir_resolves(self) -> None:
        with _make_tempdir() as tmp:
            tmp_path = Path(tmp).resolve()
            parent = tmp_path / "parent"
            child = tmp_path / "child"
            parent.mkdir()
            child.mkdir()
            _make_repo(parent)
            _make_repo(child)
            # Allow file:// submodule clones in modern git.
            subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.file.allow=always",
                    "-c",
                    "commit.gpgsign=false",
                    "submodule",
                    "add",
                    str(child),
                    "sub",
                ],
                cwd=str(parent),
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "commit", "-m", "add sub"],
                cwd=str(parent),
                check=True,
                capture_output=True,
                text=True,
            )

            repo = GitRepo.discover(parent / "sub")
            # In a submodule, .git is a file pointing to the parent's
            # .git/modules/<name>/. Verify git_dir lands there.
            expected = (parent / ".git" / "modules" / "sub").resolve()
            self.assertEqual(repo.git_dir, expected)
            self.assertEqual(repo.exclude_file, expected / "info" / "exclude")


class TestBranchExists(GitRepoTestCase):
    def test_local_branch_present(self) -> None:
        _git("branch", "feature/x", cwd=self.root)
        repo = GitRepo.discover(self.root)
        self.assertTrue(repo.branch_exists("feature/x"))

    def test_local_branch_absent(self) -> None:
        repo = GitRepo.discover(self.root)
        self.assertFalse(repo.branch_exists("nope/missing"))

    def test_remote_branch_present(self) -> None:
        # Fake a remote-tracking ref by writing into refs/remotes directly.
        remote_dir = self.root / ".git" / "refs" / "remotes" / "origin"
        remote_dir.mkdir(parents=True, exist_ok=True)
        # Use the existing HEAD sha for the fake remote ref.
        head = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        (remote_dir / "feature").write_text(head + "\n")
        repo = GitRepo.discover(self.root)
        self.assertTrue(repo.branch_exists("feature"))

    def test_remote_branch_local_only_false(self) -> None:
        remote_dir = self.root / ".git" / "refs" / "remotes" / "origin"
        remote_dir.mkdir(parents=True, exist_ok=True)
        head = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        (remote_dir / "feature").write_text(head + "\n")
        repo = GitRepo.discover(self.root)
        self.assertFalse(repo.branch_exists("feature", local_only=True))

    def test_remote_branch_no_substring_match(self) -> None:
        # refs/remotes/origin/foo/project must NOT match a query for
        # the bare branch name "project" — it's the ref `foo/project`.
        remote_dir = self.root / ".git" / "refs" / "remotes" / "origin" / "foo"
        remote_dir.mkdir(parents=True, exist_ok=True)
        head = _git("rev-parse", "HEAD", cwd=self.root).stdout.strip()
        (remote_dir / "project").write_text(head + "\n")
        repo = GitRepo.discover(self.root)
        self.assertFalse(repo.branch_exists("project"))
        self.assertTrue(repo.branch_exists("foo/project"))

    def test_branch_exists_honours_dry_run_runner(self) -> None:
        # A dry-run CommandRunner would return synthetic success on
        # every git invocation. Our ref query must bypass that.
        from pyishlib.command_runner import CommandRunner
        from pyishlib.ish_config import IshConfig

        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        repo = GitRepo.discover(self.root)
        repo.runner = runner
        self.assertFalse(repo.branch_exists("never/exists"))


class TestWorktreeOps(GitRepoTestCase):
    def test_add_worktree_with_branch(self) -> None:
        _git("branch", "ish/test", cwd=self.root)
        repo = GitRepo.discover(self.root)
        target = self.root / "wt"
        repo.add_worktree(target, branch="ish/test")
        self.assertTrue(target.is_dir())

    def test_add_worktree_detach_then_checkout_orphan(self) -> None:
        repo = GitRepo.discover(self.root)
        target = self.root / "wt"
        repo.add_worktree(target, detach=True)
        self.assertTrue(target.is_dir())
        repo.checkout_orphan("ish/orphan", work_dir=target)
        # Removing the inherited tree should succeed.
        subprocess.run(
            ["git", "rm", "-rf", "--quiet", "."],
            cwd=str(target),
            check=False,
            capture_output=True,
        )
        repo.empty_commit("init orphan", work_dir=target)
        # Branch now exists locally.
        self.assertTrue(repo.branch_exists("ish/orphan"))

    def test_create_orphan_worktree_composes_the_recipe(self) -> None:
        repo = GitRepo.discover(self.root)
        target = self.root / "wt-orphan"
        repo.create_orphan_worktree(
            target,
            "ish/newborn",
            message="bootstrap",
        )
        self.assertTrue(target.is_dir())
        self.assertTrue(repo.branch_exists("ish/newborn", local_only=True))
        # Orphan should start with an empty tree: no files tracked.
        import subprocess as _sp  # keep imports local to this test

        result = _sp.run(
            ["git", "-C", str(target), "ls-files"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip(), "")
        # And exactly one commit on the new branch.
        rev_list = _sp.run(
            ["git", "-C", str(target), "rev-list", "--count", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(rev_list.stdout.strip(), "1")


class TestExclude(GitRepoTestCase):
    def test_ensure_exclude_pattern_creates_info(self) -> None:
        info = self.root / ".git" / "info"
        # Even though git init creates info/, we tolerate it being missing.
        if info.is_dir():
            for child in info.iterdir():
                child.unlink()
            info.rmdir()
        repo = GitRepo.discover(self.root)
        self.assertTrue(repo.ensure_exclude_pattern("/.ishlib/"))
        self.assertTrue(info.is_dir())
        self.assertIn("/.ishlib/", repo.exclude_file.read_text(encoding="utf-8"))

    def test_ensure_exclude_pattern_idempotent(self) -> None:
        repo = GitRepo.discover(self.root)
        self.assertTrue(repo.ensure_exclude_pattern("/foo/"))
        self.assertFalse(repo.ensure_exclude_pattern("/foo/"))
        contents = repo.exclude_file.read_text(encoding="utf-8")
        self.assertEqual(contents.count("/foo/"), 1)

    def test_ensure_exclude_pattern_appends_newline_when_missing(self) -> None:
        repo = GitRepo.discover(self.root)
        repo.info_dir.mkdir(parents=True, exist_ok=True)
        repo.exclude_file.write_text("# header without trailing newline")
        repo.ensure_exclude_pattern("/.ishlib/")
        body = repo.exclude_file.read_text(encoding="utf-8")
        self.assertIn("\n/.ishlib/\n", body)

    def test_ensure_path_excluded_file(self) -> None:
        repo = GitRepo.discover(self.root)
        target = self.root / "src" / "foo.txt"
        target.parent.mkdir(parents=True)
        target.write_text("content")
        self.assertTrue(repo.ensure_path_excluded(target))
        self.assertIn(
            "/src/foo.txt",
            repo.exclude_file.read_text(encoding="utf-8"),
        )

    def test_ensure_path_excluded_dir_gets_trailing_slash(self) -> None:
        repo = GitRepo.discover(self.root)
        target = self.root / ".ishlib"
        target.mkdir()
        repo.ensure_path_excluded(target)
        self.assertIn(
            "/.ishlib/",
            repo.exclude_file.read_text(encoding="utf-8"),
        )

    def test_ensure_exclude_pattern_dry_run_does_not_write(self) -> None:
        from pyishlib.command_runner import CommandRunner
        from pyishlib.ish_config import IshConfig

        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        repo = GitRepo.discover(self.root)
        repo.runner = runner
        # Start from a clean state: remove the default exclude file.
        if repo.exclude_file.is_file():
            repo.exclude_file.unlink()
        returned = repo.ensure_exclude_pattern("/.ishlib/")
        # Method reports "would modify" but the file is untouched.
        self.assertTrue(returned)
        self.assertFalse(repo.exclude_file.is_file())

    def test_ensure_path_excluded_outside_tree_raises(self) -> None:
        repo = GitRepo.discover(self.root)
        with _make_tempdir() as outside:
            outside_path = Path(outside) / "foo.txt"
            outside_path.write_text("x")
            with self.assertRaises(ValueError):
                repo.ensure_path_excluded(outside_path)


class TestListTrackedFiles(GitRepoTestCase):
    def test_lists_tracked_files_relative_to_worktree(self) -> None:
        (self.root / "a.txt").write_text("a")
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("b")
        _git("add", "a.txt", "sub/b.txt", cwd=self.root)
        _git("commit", "-m", "add files", cwd=self.root)

        repo = GitRepo.discover(self.root)
        files = sorted(repo.list_tracked_files())
        self.assertEqual(files, ["a.txt", "sub/b.txt"])

    def test_handles_paths_with_spaces(self) -> None:
        spaced = self.root / "with space.txt"
        spaced.write_text("x")
        _git("add", "with space.txt", cwd=self.root)
        _git("commit", "-m", "add spaced", cwd=self.root)

        repo = GitRepo.discover(self.root)
        self.assertIn("with space.txt", repo.list_tracked_files())

    def test_returns_empty_when_nothing_tracked(self) -> None:
        repo = GitRepo.discover(self.root)
        self.assertEqual(repo.list_tracked_files(), [])


class TestRemoveExclude(GitRepoTestCase):
    def test_remove_exclude_pattern_drops_line(self) -> None:
        repo = GitRepo.discover(self.root)
        repo.ensure_exclude_pattern("/.ishlib/")
        repo.ensure_exclude_pattern("/foo.txt")
        self.assertTrue(repo.remove_exclude_pattern("/foo.txt"))
        body = repo.exclude_file.read_text(encoding="utf-8")
        self.assertIn("/.ishlib/", body)
        self.assertNotIn("/foo.txt", body)

    def test_remove_exclude_pattern_missing_is_noop(self) -> None:
        repo = GitRepo.discover(self.root)
        repo.ensure_exclude_pattern("/.ishlib/")
        self.assertFalse(repo.remove_exclude_pattern("/foo.txt"))

    def test_remove_exclude_pattern_no_file_returns_false(self) -> None:
        repo = GitRepo.discover(self.root)
        if repo.exclude_file.is_file():
            repo.exclude_file.unlink()
        self.assertFalse(repo.remove_exclude_pattern("/foo.txt"))

    def test_remove_exclude_pattern_dry_run_does_not_write(self) -> None:
        from pyishlib.command_runner import CommandRunner
        from pyishlib.ish_config import IshConfig

        repo = GitRepo.discover(self.root)
        repo.ensure_exclude_pattern("/foo.txt")
        pre = repo.exclude_file.read_text(encoding="utf-8")
        repo.runner = CommandRunner(cfg=IshConfig(dry_run=True))
        self.assertTrue(repo.remove_exclude_pattern("/foo.txt"))
        self.assertEqual(repo.exclude_file.read_text(encoding="utf-8"), pre)

    def test_remove_path_excluded_matches_ensure(self) -> None:
        repo = GitRepo.discover(self.root)
        target = self.root / "src" / "foo.txt"
        target.parent.mkdir(parents=True)
        target.write_text("content")
        repo.ensure_path_excluded(target)
        self.assertTrue(repo.remove_path_excluded(target))
        self.assertNotIn(
            "/src/foo.txt",
            repo.exclude_file.read_text(encoding="utf-8"),
        )

    def test_remove_exclude_pattern_preserves_trailing_newline(self) -> None:
        repo = GitRepo.discover(self.root)
        repo.ensure_exclude_pattern("/a")
        repo.ensure_exclude_pattern("/b")
        repo.remove_exclude_pattern("/a")
        body = repo.exclude_file.read_text(encoding="utf-8")
        self.assertTrue(body.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
