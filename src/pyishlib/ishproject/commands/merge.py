# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject merge`` -- commit managed files into the main branch."""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path
from typing import List

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError, _clean_git_env
from ...ish_config import IshConfig
from ..config import IshprojectConfig

log = logging.getLogger(__name__)


class MergeCommand(CliCommand):
    """Drop per-file exclude entries and commit managed files into main."""

    NAME = "merge"
    HELP = "Commit the currently-applied ishproject files into the main branch"
    DESCRIPTION = (
        "Removes per-file entries from the project repo's per-worktree "
        "excludes file for every file tracked on the `ish/ishproject` "
        "branch, stages them from the project root, and creates one "
        "commit on the current branch. The `/.ishlib/` worktree "
        "exclude is left in place so the ishproject worktree itself "
        "is never committed. Intended for temporarily adopting "
        "ishproject-managed tool configs into main (e.g. before "
        "handing the repo to an automated session), and paired with "
        "`ishproject clean-rebase` to undo afterwards."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-m",
            "--message",
            default="ishproject: merge managed files",
            help=("Commit message for the merge commit (default: %(default)s)."),
        )

    def run(self, args: argparse.Namespace) -> int:
        cfg: IshprojectConfig = args.ishproject_cfg
        runner = CommandRunner(cfg=IshConfig(dry_run=args.dry_run))
        root = Path.cwd()

        try:
            repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            log.error(
                "ishproject merge must be run from a git repository root: %s",
                root,
            )
            return 1
        repo.runner = runner

        branch = cfg.resolve_active_branch(root)
        source, target = cfg.resolve_project_paths(root, branch=branch)
        if not source.is_dir():
            log.error(
                "Project dotfiles directory does not exist: %s "
                "(run `ishproject init` first)",
                source,
            )
            return 1

        try:
            source_repo = GitRepo.discover(source)
            files = source_repo.list_tracked_files()
        except (NotAGitRepoError, subprocess.CalledProcessError):
            log.error("Failed to list files on %s", source)
            return 1

        if not files:
            log.warning("No files tracked on ish/ishproject; nothing to merge.")
            return 0

        removed: List[str] = []
        try:
            for rel in files:
                if repo.remove_path_excluded(target / rel):
                    removed.append(rel)
        except ValueError as exc:
            log.error("%s", exc)
            _restore_excludes(repo, target, removed)
            return 1

        try:
            runner.git(["add", "--", *files], work_dir=target)
        except subprocess.CalledProcessError:
            log.error("git add failed; aborting merge.")
            _restore_excludes(repo, target, removed)
            return 1

        diff_cached = subprocess.run(
            ["git", "-C", str(target), "diff", "--cached", "--quiet"],
            check=False,
            env=_clean_git_env(),
        )
        if diff_cached.returncode == 0:
            log.warning(
                "No staged changes after removing exclude entries; nothing to commit."
            )
            _restore_excludes(repo, target, removed)
            return 0

        try:
            runner.git(
                [
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "tag.gpgsign=false",
                    "commit",
                    "-m",
                    args.message,
                ],
                work_dir=target,
            )
        except subprocess.CalledProcessError:
            log.error("git commit failed; merge aborted.")
            _restore_excludes(repo, target, removed)
            return 1

        log.info("Committed %d managed file(s) to %s", len(files), target)
        return 0


def _restore_excludes(repo: GitRepo, target: Path, paths: List[str]) -> None:
    """Re-add exclude entries for *paths* so a failed merge doesn't leave
    the per-worktree excludes file half-modified."""
    for rel in paths:
        try:
            repo.ensure_path_excluded(target / rel)
        except ValueError as exc:
            log.warning("could not restore exclude for %s: %s", rel, exc)
