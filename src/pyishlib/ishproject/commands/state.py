# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject state`` -- compact dirty-count token for shell prompts.

Prints a single line like ``±3`` when the active ishproject worktree
has uncommitted changes, and nothing when it is clean or absent. With
``-R`` the count aggregates initialised submodules' ishproject worktrees
into the same total so prompts stay one line. No network is touched and
stdin is never read, so the command is safe to invoke on every prompt
render.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...git_repo import GitRepo, NotAGitRepoError
from ..config import IshprojectConfig

log = logging.getLogger(__name__)

DIRTY_SYMBOL = "±"


class StateCommand(CliCommand):
    """Print a compact ishproject worktree dirty-count for shell prompts."""

    NAME = "state"
    HELP = "Print a compact ishproject state token (for shell prompts)"
    DESCRIPTION = (
        "Prints `±N` when the active ishproject worktree has N "
        "uncommitted changes, and nothing when it is clean, absent, or "
        "cwd is not a git repo. With -R the dirty counts of every "
        "initialised submodule with an ishproject worktree are folded "
        "into the same total. Designed to run on every prompt render: "
        "no network, no stdin, exits 0 on every well-formed invocation."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-R",
            "--recurse-submodules",
            action="store_true",
            default=False,
            help=(
                "Fold the dirty count of every initialised submodule "
                "with an ishproject worktree into the parent total."
            ),
        )

    def run(self) -> int:
        cfg: IshprojectConfig = self.cfg.ishproject_cfg
        root = Path.cwd()

        try:
            parent_repo = GitRepo.discover(root)
        except NotAGitRepoError:
            return 0

        total = self._count_for_repo(cfg, parent_repo.work_tree)

        if getattr(self.cfg, "recurse_submodules", False):
            for _sub_repo, sub_source, _sub_target in cfg.iter_initialised_submodules(
                parent_repo
            ):
                total += self._count_at(sub_source)

        if total > 0:
            print(f"{DIRTY_SYMBOL}{total}")
        return 0

    @staticmethod
    def _count_for_repo(cfg: IshprojectConfig, root: Path) -> int:
        """Resolve the active ishproject worktree for *root* and count dirty entries."""
        branch = cfg.resolve_active_branch(root)
        source, _target = cfg.resolve_project_paths(root, branch=branch)
        return StateCommand._count_at(source)

    @staticmethod
    def _count_at(source: Path) -> int:
        """Return the porcelain entry count for the worktree at *source*, 0 if absent."""
        if not source.is_dir():
            return 0
        try:
            worktree = GitRepo.discover(source, require_root=True)
        except NotAGitRepoError:
            return 0
        return len(worktree.status_porcelain())
