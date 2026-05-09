# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject commit`` -- forward to ``ishfiles commit`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...git_repo import GitRepo, NotAGitRepoError
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from .._precommit import allow_missing_precommit_config

log = logging.getLogger(__name__)


class CommitCommand(CliCommand):
    """Commit all changes in the project dotfiles repository."""

    NAME = "commit"
    HELP = "Commit all changes in the active ishproject dotfiles repository"
    DESCRIPTION = (
        "Thin wrapper around `ishfiles commit` with --source and --target "
        "pointed at the current project.  All remaining arguments (e.g. "
        "`-m MSG`) are forwarded to ishfiles.  With --recurse-submodules "
        "the same commit also runs in every initialised submodule that "
        "has the ishproject branch and worktree set up."
    )

    @staticmethod
    def TARGET_MAIN(argv):
        return ishfiles_main(argv)

    @staticmethod
    def TARGET_BUILD_PARSER():
        return ishfiles_build_parser()

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--recurse-submodules",
            action="store_true",
            default=False,
            help=(
                "After committing the parent project, run `ishproject commit` "
                "in every initialised submodule (recursively) that has the "
                "ishproject branch and worktree set up. Submodules without "
                "an ishproject worktree are silently skipped."
            ),
        )
        parser.add_argument(
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles commit`.",
        )

    def run(self) -> int:
        cfg = self.cfg.ishproject_cfg
        root = Path.cwd()

        branch = cfg.resolve_active_branch(root)
        source, target = cfg.resolve_project_paths(root, branch=branch)
        if not source.is_dir():
            log.error(
                "Project dotfiles directory does not exist: %s "
                "(run `ishproject init` first)",
                source,
            )
            return 1

        rcs = [self._commit_one(source, target)]

        if getattr(self.cfg, "recurse_submodules", False):
            try:
                parent_repo = GitRepo.discover(root, require_root=True)
            except NotAGitRepoError:
                parent_repo = None
            if parent_repo is not None:
                for sub_repo, sub_source, sub_target in cfg.iter_initialised_submodules(
                    parent_repo
                ):
                    log.info("ishproject commit in submodule %s", sub_repo.work_tree)
                    rcs.append(self._commit_one(sub_source, sub_target))

        return max(rcs)

    def _commit_one(self, source: Path, target: Path) -> int:
        with allow_missing_precommit_config():
            return self.passthrough(
                "commit",
                self.cfg.rest,
                global_args=["--source", str(source), "--target", str(target)],
            )
