# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject status`` -- forward to ``ishfiles status`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List

from ...cli_command import CliCommand
from ...git_repo import GitRepo, NotAGitRepoError
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ..config import IshprojectConfig

log = logging.getLogger(__name__)


class StatusCommand(CliCommand):
    """Show dotfile and git status for the project."""

    NAME = "status"
    HELP = "Show dotfile target/source status for the active ishproject worktree"
    DESCRIPTION = (
        "Thin wrapper around `ishfiles status` with --source and --target "
        "pointed at the current project. Recurses automatically into any "
        "initialised git submodules that have the ishproject branch (no "
        "fetches are performed). All remaining arguments are forwarded to "
        "ishfiles."
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
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles status`.",
        )

    def run(self) -> int:
        cfg: IshprojectConfig = self.cfg.ishproject_cfg
        root = Path.cwd()

        try:
            repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            repo = None

        submodules: List[Path] = (
            repo.list_submodules(recursive=True) if repo is not None else []
        )

        # Headers go on every section when at least one submodule will
        # produce a status block; otherwise output stays byte-identical
        # to the pre-recursion behaviour.
        emit_headers = any(self._will_report(cfg, sub) for sub in submodules)

        parent_rc = self._status_one(
            cfg, root, is_parent=True, emit_header=emit_headers
        )
        sub_rcs = [
            self._status_one(cfg, sub, is_parent=False, emit_header=emit_headers)
            for sub in submodules
        ]

        return max([parent_rc, *sub_rcs])

    def _status_one(
        self,
        cfg: IshprojectConfig,
        root: Path,
        *,
        is_parent: bool,
        emit_header: bool,
    ) -> int:
        """Run ishfiles status for a single repo (parent or submodule).

        Submodules without an ishproject branch are silently skipped;
        submodules whose branch exists locally / in cached remote refs
        but whose worktree has not been created yet are surfaced via
        ``log.info`` so the user knows where to run ``ishproject init``.
        No fetches are performed.
        """
        branch = cfg.resolve_active_branch(root)
        source, target = cfg.resolve_project_paths(root, branch=branch)

        # Submodules: gate every action (including running status against
        # an existing worktree) on the ishproject branch being present in
        # locally-known refs. A stale `.ishlib/ishproject` directory left
        # over from a deleted branch is silently skipped rather than
        # reported against. branch_exists() default does not fetch.
        if not is_parent:
            try:
                sub_repo = GitRepo.discover(root, require_root=True)
            except NotAGitRepoError:
                return 0
            if not sub_repo.branch_exists(branch):
                return 0
            if not source.is_dir():
                log.info(
                    "ishproject branch %s present in %s but worktree not "
                    "initialized; run `ishproject init` to set it up",
                    branch,
                    root,
                )
                return 0
        elif not source.is_dir():
            log.error(
                "Project dotfiles directory does not exist: %s "
                "(run `ishproject init` first)",
                source,
            )
            return 1

        if emit_header:
            print(f"=== {self._display_path(root)} ===")

        forwarded = ["--include-ignored", *self.cfg.rest]
        return self.passthrough(
            "status",
            forwarded,
            global_args=["--source", str(source), "--target", str(target)],
        )

    @staticmethod
    def _will_report(cfg: IshprojectConfig, root: Path) -> bool:
        """True if a submodule at *root* will produce a status section.

        Mirrors the gate in :meth:`_status_one`: a section is produced only
        when the ishproject branch is present in locally-known refs *and*
        the worktree directory exists.  Headers are decided from this
        predicate so they are not emitted for submodules that will be
        silently skipped.
        """
        branch = cfg.resolve_active_branch(root)
        source, _target = cfg.resolve_project_paths(root, branch=branch)
        if not source.is_dir():
            return False
        try:
            sub_repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            return False
        return sub_repo.branch_exists(branch)

    @staticmethod
    def _display_path(path: Path) -> str:
        """Return *path* relative to cwd when possible, or its absolute form."""
        try:
            rel = path.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            return str(path)
        rel_str = str(rel)
        return rel_str if rel_str else "."
