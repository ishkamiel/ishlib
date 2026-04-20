# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject branch`` -- create a per-dev-branch ishproject variant."""

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
from ..config import IshprojectConfig

log = logging.getLogger(__name__)


class BranchCommand(CliCommand):
    """Create a ``<prefix>/<current>/<postfix>`` ishproject branch + worktree."""

    NAME = "branch"
    HELP = "Create a per-dev-branch ishproject variant for the current branch"
    DESCRIPTION = (
        "Creates an orphan ishproject branch named "
        "`<prefix>/<current>/<postfix>` where <current> is the checked-"
        "out branch in the project repo, plus a worktree for it under "
        ".ishlib/. Subsequent ishproject commands run on <current> "
        "will automatically use this branch instead of the default "
        "`<prefix>/<postfix>` branch."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, args: argparse.Namespace) -> int:
        cfg: IshprojectConfig = args.ishproject_cfg
        runner = CommandRunner(cfg=IshConfig(dry_run=args.dry_run))
        root = Path.cwd()

        try:
            repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            log.error(
                "ishproject branch must be run from a git repository root: %s",
                root,
            )
            return 1
        repo.runner = runner

        current = repo.current_branch()
        if not current:
            log.error(
                "HEAD is detached; check out a branch before running "
                "`ishproject branch`."
            )
            return 1

        branch = cfg.branch_for(current)
        if branch == cfg.default_branch:
            log.error(
                "Resolved branch %s matches the default; refusing to "
                "create a per-branch variant that would collide with "
                "the default worktree.",
                branch,
            )
            return 1

        folder = IshlibFolder(root)
        source = cfg.worktree_path(folder, branch)

        if source.is_dir():
            log.info("Per-branch worktree already present at %s", source)
        elif repo.branch_exists(branch, local_only=True):
            folder.path.mkdir(parents=True, exist_ok=True)
            try:
                repo.add_worktree(source, branch=branch)
            except subprocess.CalledProcessError:
                return 1
            log.info("Created worktree: %s -> branch %s", source, branch)
        else:
            folder.path.mkdir(parents=True, exist_ok=True)
            try:
                repo.create_orphan_worktree(
                    source,
                    branch,
                    message=f"Initialise ishproject branch {branch}",
                )
            except subprocess.CalledProcessError:
                return 1
            log.info(
                "Created orphan branch %s and worktree at %s",
                branch,
                source,
            )

        repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
        return 0
