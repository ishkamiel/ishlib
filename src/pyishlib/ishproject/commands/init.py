# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject init`` -- bootstrap the .ishlib/ishproject worktree."""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ish_logging import setup_logging
from ...ishlib_folder import PROJECT_DIR_NAME, IshlibFolder
from ..config import ISHPROJECT_BRANCH

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``init`` subcommand."""
    parser = subparsers.add_parser(
        "init",
        help="Initialise .ishlib/ishproject from the ish/ishproject branch",
        description=(
            "If cwd is a git-repo root and the branch `ish/ishproject` "
            "exists, adds it as a worktree at .ishlib/ishproject. With "
            "--create, bootstraps an empty orphan branch when none "
            "exists. Always appends .ishlib/ to .git/info/exclude."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v=info, -vv=debug).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress non-essential output.",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        default=False,
        help="Show actions without executing them.",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        default=False,
        help=(
            "If the branch does not exist, create an empty orphan "
            "`ish/ishproject` branch and check it out as the worktree. "
            "Without this flag, a missing branch is an error."
        ),
    )
    parser.set_defaults(func=run)


def _configure_logging(args: argparse.Namespace) -> None:
    if args.quiet:
        level = logging.ERROR
    elif args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    setup_logging(level, log_file=None, quiet=args.quiet)


def run(args: argparse.Namespace) -> int:
    """Bootstrap the worktree and update ``.git/info/exclude``."""
    _configure_logging(args)

    runner = CommandRunner(cfg=IshConfig(dry_run=args.dry_run))
    root = Path.cwd()

    try:
        repo = GitRepo.discover(root, require_root=True)
    except NotAGitRepoError:
        log.error(
            "ishproject init must be run from a git repository root: %s",
            root,
        )
        return 1
    repo.runner = runner

    folder = IshlibFolder(root)
    source = folder.ishproject_dir

    if source.is_dir():
        log.info("Project dotfiles already present at %s", source)
    elif repo.branch_exists(ISHPROJECT_BRANCH, local_only=True):
        folder.path.mkdir(parents=True, exist_ok=True)
        try:
            repo.add_worktree(source, branch=ISHPROJECT_BRANCH)
        except subprocess.CalledProcessError:
            return 1
        log.info("Created worktree: %s -> branch %s", source, ISHPROJECT_BRANCH)
    elif repo.branch_exists(ISHPROJECT_BRANCH):
        # Branch only exists on a remote; ``git worktree add <branch>``
        # requires a local branch. Tell the user how to materialise one.
        log.error(
            "Branch %s only exists on a remote. Create a local tracking "
            "branch first, e.g. `git branch %s origin/%s`, then re-run "
            "`ishproject init`.",
            ISHPROJECT_BRANCH,
            ISHPROJECT_BRANCH,
            ISHPROJECT_BRANCH,
        )
        return 1
    elif args.create:
        folder.path.mkdir(parents=True, exist_ok=True)
        try:
            repo.add_worktree(source, detach=True)
            repo.checkout_orphan(ISHPROJECT_BRANCH, work_dir=source)
            runner.git(
                ["rm", "-rf", "--quiet", "."],
                work_dir=source,
                check=False,
            )
            repo.empty_commit("Initialise ishproject branch", work_dir=source)
        except subprocess.CalledProcessError:
            return 1
        log.info(
            "Created orphan branch %s and worktree at %s",
            ISHPROJECT_BRANCH,
            source,
        )
    else:
        log.error(
            "Branch %s not found. Create it locally or fetch from a "
            "remote, then re-run `ishproject init` (or pass --create "
            "to bootstrap an empty orphan branch now).",
            ISHPROJECT_BRANCH,
        )
        return 1

    repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
    return 0
