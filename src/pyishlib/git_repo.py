# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Thin wrapper around a git working tree.

The wrapper exists primarily so that callers do not hard-code
``<root>/.git/info/exclude``: when the working tree is a submodule the
real git directory lives under the parent repo's
``.git/modules/<name>/`` and the exclude file follows. ``git rev-parse
--git-dir`` resolves the right path in both cases, and :class:`GitRepo`
owns that resolution.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from .command_runner import CommandRunner

log = logging.getLogger(__name__)

_GIT_DIR_VARS = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
)


def _clean_git_env() -> dict:
    """Return a copy of environ with git-dir override vars removed."""
    env = os.environ.copy()
    for var in _GIT_DIR_VARS:
        env.pop(var, None)
    return env


class NotAGitRepoError(RuntimeError):
    """Raised when a path is not inside a git working tree."""


class GitRepo:
    """Lightweight git working-tree wrapper.

    Holds the resolved working tree (``git rev-parse --show-toplevel``)
    and git directory (``git rev-parse --git-dir``) for a path, plus a
    :class:`CommandRunner` for subprocess work. Submodule-safe: callers
    should always go through :attr:`exclude_file` rather than building a
    path from :attr:`work_tree`.
    """

    def __init__(
        self,
        work_tree: Path,
        git_dir: Path,
        runner: Optional[CommandRunner] = None,
    ) -> None:
        self.work_tree = work_tree.resolve()
        self.git_dir = git_dir.resolve()
        self.runner = runner if runner is not None else CommandRunner()

    @classmethod
    def discover(cls, path: Path, *, require_root: bool = False) -> "GitRepo":
        """Discover the repo containing *path*.

        Runs ``git -C <path> rev-parse --show-toplevel --git-dir`` via
        ``subprocess.run`` — discovery is a read-only probe that must
        execute regardless of any caller's dry-run intent. The returned
        :class:`GitRepo` has a default :class:`CommandRunner`; callers
        that need a specific runner (e.g. with ``dry_run=True``)
        should assign it afterwards::

            repo = GitRepo.discover(root, require_root=True)
            repo.runner = my_runner

        Args:
            path: Path to probe.
            require_root: When true, also require the resolved working
                tree to equal ``path.resolve()`` (used by ishproject,
                which only operates from the repo root).

        Raises:
            NotAGitRepoError: *path* is not inside a git repo, or
                ``require_root`` is true but *path* is not the root.
        """
        path = Path(path).resolve()
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--show-toplevel", "--git-dir"],
                check=True,
                capture_output=True,
                text=True,
                env=_clean_git_env(),
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise NotAGitRepoError(f"Not a git repository: {path}") from exc

        lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        if len(lines) < 2:
            raise NotAGitRepoError(
                f"git rev-parse returned unexpected output: {result.stdout!r}"
            )
        toplevel = Path(lines[0])
        git_dir = Path(lines[1])
        if not git_dir.is_absolute():
            # ``--git-dir`` is relative to *path* when given via -C.
            git_dir = (path / git_dir).resolve()

        if require_root and toplevel.resolve() != path:
            raise NotAGitRepoError(
                f"{path} is not the root of the git repository ({toplevel})"
            )

        return cls(toplevel, git_dir)

    # ---- ref queries -------------------------------------------------------

    def _run_ref_query(
        self,
        args: list,
        *,
        capture_output: bool = False,
        text: bool = False,
    ) -> "subprocess.CompletedProcess":
        """Execute a read-only git ref query, bypassing dry-run simulation.

        ``CommandRunner`` returns a synthetic success result when
        ``dry_run`` is true, which would make every ``show-ref`` /
        ``for-each-ref`` look like it found its target. Ref queries
        have no side effects, so it's always safe to actually run them.
        """
        return subprocess.run(
            ["git", "-C", str(self.work_tree), *args],
            check=False,
            capture_output=capture_output,
            text=text,
            env=_clean_git_env(),
        )

    def branch_exists(self, branch: str, *, local_only: bool = False) -> bool:
        """True if *branch* exists locally or (when allowed) on any remote.

        Checks ``refs/heads/<branch>`` first. When ``local_only`` is
        false (the default) the method also scans ``refs/remotes/`` and
        returns true if any ``refs/remotes/<remote>/<branch>`` exists.
        Callers that need a commit-ish suitable for ``git worktree add
        <path> <branch>`` should pass ``local_only=True``: a remote
        ref alone is not a local branch name.
        """
        local = self._run_ref_query(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"]
        )
        if local.returncode == 0:
            return True
        if local_only:
            return False
        return len(self.remotes_with_branch(branch)) > 0

    def remotes_with_branch(self, branch: str) -> list:
        """Return names of remotes that carry *branch*.

        Scans ``refs/remotes/<remote>/<branch>`` and returns the
        matching remote names in the order ``git for-each-ref``
        enumerates them. Returns an empty list when no remote carries
        the branch or when there are no remotes at all.
        """
        result = self._run_ref_query(
            ["for-each-ref", "--format=%(refname)", "refs/remotes"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout:
            return []
        carriers = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith("refs/remotes/"):
                continue
            # refs/remotes/<remote>/<branch>; split once to isolate the
            # remote name, compare the rest exactly.
            tail = line[len("refs/remotes/") :]
            parts = tail.split("/", 1)
            if len(parts) == 2 and parts[1] == branch:
                carriers.append(parts[0])
        return carriers

    def current_branch(self) -> Optional[str]:
        """Return the currently checked-out branch name, or ``None`` if detached.

        Runs ``git symbolic-ref --quiet --short HEAD``. A detached HEAD
        has no symbolic branch, so the method returns ``None`` instead
        of raising.
        """
        result = self._run_ref_query(
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        name = result.stdout.strip()
        return name or None

    # ---- remote helpers ----------------------------------------------------

    def list_remotes(self) -> list:
        """Return names of all configured remotes.

        Runs ``git remote`` via the read-only probe path so dry-run
        callers still see the real remote list.
        """
        result = self._run_ref_query(
            ["remote"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout:
            return []
        return [r for r in result.stdout.splitlines() if r.strip()]

    def remote_exists(self, name: str) -> bool:
        """True if *name* is a configured remote in this repo."""
        return name in self.list_remotes()

    def remote_url(self, name: str) -> Optional[str]:
        """Return the fetch URL of *name*, or ``None`` if the remote does not exist."""
        result = self._run_ref_query(
            ["remote", "get-url", name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def add_remote(self, name: str, url: str) -> None:
        """Run ``git remote add <name> <url>``.

        Honours ``self.runner.dry_run``.
        """
        self.runner.git(["remote", "add", name, url], work_dir=self.work_tree)

    def fetch(self, remote: str, *, refspec: Optional[str] = None) -> None:
        """Run ``git fetch --quiet <remote> [<refspec>]``.

        Honours ``self.runner.dry_run``. Failures propagate as
        :exc:`subprocess.CalledProcessError`; callers decide how to
        report them.
        """
        cmd = ["fetch", "--quiet", remote]
        if refspec is not None:
            cmd.append(refspec)
        self.runner.git(cmd, work_dir=self.work_tree)

    def create_tracking_branch(self, branch: str, remote: str) -> None:
        """Create local *branch* tracking ``<remote>/<branch>``.

        Runs ``git branch --track <branch> <remote>/<branch>``.
        Explicit ``--track`` survives ``branch.autoSetupMerge=never``.
        Honours ``self.runner.dry_run``.
        """
        self.runner.git(
            ["branch", "--track", branch, f"{remote}/{branch}"],
            work_dir=self.work_tree,
        )

    def list_tracked_files(self) -> list:
        """Return work-tree-relative paths of tracked files.

        Wraps ``git -C <work_tree> ls-files -z`` and splits on NUL.
        Read-only probe; bypasses ``CommandRunner``'s dry-run simulation
        so callers can enumerate files under ``--dry-run``.
        """
        result = subprocess.run(
            ["git", "-C", str(self.work_tree), "ls-files", "-z"],
            check=True,
            capture_output=True,
            text=True,
            env=_clean_git_env(),
        )
        return [p for p in result.stdout.split("\x00") if p]

    def status_porcelain(self) -> dict:
        """Return the working-tree status as ``{relative_path: XY_code}``.

        Runs ``git status --porcelain=v1 -z`` (NUL-delimited) and parses
        the output. Read-only probe; bypasses ``CommandRunner``'s dry-run
        simulation so callers always see the true working-tree state.

        For renamed/copied entries the *destination* path is used as the
        key; the origin path is discarded.  An empty dict is returned when
        the repository has no uncommitted changes or when git exits
        non-zero (e.g. a bare repo).
        """
        result = self._run_ref_query(
            ["status", "--porcelain=v1", "-z"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout:
            return {}

        entries: dict = {}
        tokens = result.stdout.split("\x00")
        skip_next = False
        for token in tokens:
            if not token:
                continue
            if skip_next:
                skip_next = False
                continue
            if len(token) < 3 or token[2] != " ":
                continue
            xy = token[:2]
            path = token[3:]
            entries[path] = xy
            # Rename/copy: next token is the orig path, not a new entry.
            if xy[0] in ("R", "C"):
                skip_next = True
        return entries

    # ---- mutating git ops --------------------------------------------------

    def commit_all(self, message: str) -> "subprocess.CompletedProcess":
        """Run ``git commit -a -m <message>`` in the working tree.

        Goes through :attr:`runner` so dry-run mode is respected.
        Returns the ``CompletedProcess`` without raising on non-zero exit
        (e.g. "nothing to commit"); callers are responsible for checking
        ``returncode``.
        """
        return self.runner.git(
            ["commit", "-a", "-m", message],
            work_dir=self.work_tree,
            check=False,
        )

    def push(self, *extra_args: str) -> "subprocess.CompletedProcess":
        """Run ``git push [extra_args]`` in the working tree.

        Goes through :attr:`runner` so dry-run mode is respected.
        Returns the ``CompletedProcess`` without raising on non-zero exit;
        callers are responsible for checking ``returncode``.
        """
        return self.runner.git(
            ["push", *extra_args],
            work_dir=self.work_tree,
            check=False,
        )

    def pull_rebase(self) -> "subprocess.CompletedProcess":
        """Run ``git pull --rebase`` in the working tree.

        Goes through :attr:`runner` so dry-run mode is respected.
        Returns the ``CompletedProcess`` without raising on non-zero exit;
        callers are responsible for checking ``returncode``.
        """
        return self.runner.git(
            ["pull", "--rebase"],
            work_dir=self.work_tree,
            check=False,
        )

    # ---- worktree / branch ops --------------------------------------------

    def add_worktree(
        self,
        path: Path,
        *,
        branch: Optional[str] = None,
        detach: bool = False,
    ) -> None:
        """Run ``git worktree add [--detach] <path> [<branch>]``."""
        cmd = ["worktree", "add"]
        if detach:
            cmd.append("--detach")
        cmd.append(str(path))
        if branch is not None:
            cmd.append(branch)
        self.runner.git(cmd, work_dir=self.work_tree)

    def checkout_orphan(self, branch: str, *, work_dir: Path) -> None:
        """Run ``git switch --orphan <branch>`` inside *work_dir*."""
        self.runner.git(
            ["switch", "--orphan", branch],
            work_dir=work_dir,
        )

    def empty_commit(self, message: str, *, work_dir: Path) -> None:
        """Run ``git commit --allow-empty -m <message>`` inside *work_dir*."""
        self.runner.git(
            [
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                "commit",
                "--allow-empty",
                "-m",
                message,
            ],
            work_dir=work_dir,
        )

    def create_orphan_worktree(
        self,
        path: Path,
        branch: str,
        *,
        message: str,
    ) -> None:
        """Create orphan *branch* checked out as a worktree at *path*.

        Composes :meth:`add_worktree` (detached), :meth:`checkout_orphan`,
        a ``git rm -rf .`` to drop the seeded tree, and :meth:`empty_commit`
        so *branch* starts life with a single empty commit. Honours
        ``self.runner.dry_run`` via the underlying runner.
        """
        self.add_worktree(path, detach=True)
        self.checkout_orphan(branch, work_dir=path)
        self.runner.git(
            ["rm", "-rf", "--quiet", "."],
            work_dir=path,
            check=False,
        )
        self.empty_commit(message, work_dir=path)

    # ---- info/exclude ------------------------------------------------------

    @property
    def info_dir(self) -> Path:
        """``<git_dir>/info`` — submodule-correct."""
        return self.git_dir / "info"

    @property
    def exclude_file(self) -> Path:
        """``<git_dir>/info/exclude`` — submodule-correct."""
        return self.info_dir / "exclude"

    def ensure_exclude_pattern(self, pattern: str) -> bool:
        """Idempotently append *pattern* to ``info/exclude``.

        Returns ``True`` if the file was (or would be) modified, ``False``
        if the pattern was already present. Creates ``info/`` if
        missing. Honours ``self.runner.dry_run``: when true the disk
        is not touched and the method logs the would-be append.
        """
        if not pattern:
            raise ValueError("pattern must be non-empty")

        existing = ""
        if self.exclude_file.is_file():
            existing = self.exclude_file.read_text(encoding="utf-8")

        for line in existing.splitlines():
            if line.strip() == pattern:
                log.debug("exclude pattern already present: %s", pattern)
                return False

        if self.runner.dry_run:
            log.info("dry-run: would append %s to %s", pattern, self.exclude_file)
            return True

        self.info_dir.mkdir(parents=True, exist_ok=True)
        prefix = ""
        if existing and not existing.endswith("\n"):
            prefix = "\n"
        with self.exclude_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}{pattern}\n")
        log.debug("appended exclude pattern: %s", pattern)
        return True

    def ensure_path_excluded(self, path: Path) -> bool:
        """Ensure *path* is covered by ``info/exclude``.

        Resolves *path* to a work-tree-relative pattern anchored with a
        leading slash (e.g. ``/src/foo.txt`` for a file, ``/.ishlib/``
        for a directory). Delegates to :meth:`ensure_exclude_pattern`.

        Raises:
            ValueError: *path* resolves outside the working tree.
        """
        pattern = self._path_to_exclude_pattern(path)
        return self.ensure_exclude_pattern(pattern)

    def remove_exclude_pattern(self, pattern: str) -> bool:
        """Idempotently drop *pattern* from ``info/exclude``.

        Returns ``True`` if the file was (or would be) modified, ``False``
        if the pattern was absent. Honours ``self.runner.dry_run``.
        """
        if not pattern:
            raise ValueError("pattern must be non-empty")

        if not self.exclude_file.is_file():
            return False

        existing = self.exclude_file.read_text(encoding="utf-8")
        lines = existing.splitlines()
        kept = [ln for ln in lines if ln.strip() != pattern]
        if len(kept) == len(lines):
            return False

        if self.runner.dry_run:
            log.info("dry-run: would remove %s from %s", pattern, self.exclude_file)
            return True

        trailing_newline = existing.endswith("\n")
        new_text = "\n".join(kept)
        if kept and trailing_newline:
            new_text += "\n"
        elif not kept:
            new_text = ""
        self.exclude_file.write_text(new_text, encoding="utf-8")
        log.debug("removed exclude pattern: %s", pattern)
        return True

    def remove_path_excluded(self, path: Path) -> bool:
        """Drop the exclude entry covering *path* (see :meth:`ensure_path_excluded`)."""
        pattern = self._path_to_exclude_pattern(path)
        return self.remove_exclude_pattern(pattern)

    def _path_to_exclude_pattern(self, path: Path) -> str:
        """Derive the work-tree-relative exclude pattern for *path*.

        Used by both :meth:`ensure_path_excluded` and
        :meth:`remove_path_excluded` so the byte-for-byte pattern stays
        consistent across add and remove.
        """
        resolved = Path(path).resolve()
        try:
            rel = resolved.relative_to(self.work_tree)
        except ValueError as exc:
            raise ValueError(
                f"{path} is outside the work tree {self.work_tree}"
            ) from exc

        rel_str = rel.as_posix()
        if not rel_str or rel_str == ".":
            raise ValueError(f"{path} resolves to the work tree root")

        pattern = f"/{rel_str}"
        if resolved.is_dir():
            pattern = f"{pattern}/"
        return pattern
