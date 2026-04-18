# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject init`` -- bootstrap the .ishlib/ishproject worktree."""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ishlib_folder import PROJECT_DIR_NAME, IshlibFolder
from ..config import ISHPROJECT_BRANCH

log = logging.getLogger(__name__)


class InitCommand(CliCommand):
    """Initialise .ishlib/ishproject from the ish/ishproject branch."""

    NAME = "init"
    HELP = "Initialise .ishlib/ishproject from the ish/ishproject branch"
    DESCRIPTION = (
        "If cwd is a git-repo root and the branch `ish/ishproject` "
        "exists, adds it as a worktree at .ishlib/ishproject. With "
        "--create, bootstraps an empty orphan branch when none "
        "exists. Always appends .ishlib/ to .git/info/exclude."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
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

    def run(self, args: argparse.Namespace) -> int:
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
        source = folder.tool_dir("ishproject")

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
