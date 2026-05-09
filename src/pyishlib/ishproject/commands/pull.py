# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject pull`` -- forward to ``ishfiles pull`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...git_repo import GitRepo, NotAGitRepoError
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main

log = logging.getLogger(__name__)


class PullCommand(CliCommand):
    """Pull (rebase) the project dotfiles repository from its remote."""

    NAME = "pull"
    HELP = "Pull (rebase) the active ishproject dotfiles repository from remote"
    DESCRIPTION = (
        "Thin wrapper around `ishfiles pull` with --source and --target "
        "pointed at the current project.  All remaining arguments are "
        "forwarded to ishfiles.  With --recurse-submodules the same pull "
        "also runs in every initialised submodule that has the ishproject "
        "branch and worktree set up."
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
                "After pulling the parent project, run `ishproject pull` "
                "in every initialised submodule (recursively) that has the "
                "ishproject branch and worktree set up. Submodules without "
                "an ishproject worktree are silently skipped."
            ),
        )
        parser.add_argument(
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles pull`.",
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

        rcs = [self._pull_one(source, target)]

        if getattr(self.cfg, "recurse_submodules", False):
            try:
                parent_repo = GitRepo.discover(root, require_root=True)
            except NotAGitRepoError:
                parent_repo = None
            if parent_repo is not None:
                for sub_repo, sub_source, sub_target in cfg.iter_initialised_submodules(
                    parent_repo
                ):
                    log.info("ishproject pull in submodule %s", sub_repo.work_tree)
                    rcs.append(self._pull_one(sub_source, sub_target))

        return max(rcs)

    def _pull_one(self, source: Path, target: Path) -> int:
        return self.passthrough(
            "pull",
            self.cfg.rest,
            global_args=["--source", str(source), "--target", str(target)],
        )
