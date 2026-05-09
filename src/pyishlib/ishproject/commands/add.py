# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject add`` -- forward to ``ishfiles add`` and update info/exclude."""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...completions import FILE as _COMPLETE_FILE
from ...dotfile_finder import DotfileFinder
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ...ishlib_folder import PROJECT_DIR_NAME

log = logging.getLogger(__name__)


class AddCommand(CliCommand):
    """Add files to the project dotfiles repository (wraps ``ishfiles add``)."""

    NAME = "add"
    HELP = "Add files to the project dotfiles repository"
    DESCRIPTION = (
        "Thin wrapper around `ishfiles add` with --source and --target "
        "pointed at the current project. Before forwarding, each file "
        "is added to the project repo's .git/info/exclude so the "
        "managed copy is not tracked by the project repo."
    )

    @staticmethod
    def TARGET_MAIN(argv):
        return ishfiles_main(argv)

    @staticmethod
    def TARGET_BUILD_PARSER():
        return ishfiles_build_parser()

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        files_arg = parser.add_argument(
            "files",
            nargs="*",
            help="File(s) to add to the project dotfiles repository.",
        )
        files_arg.complete = _COMPLETE_FILE  # type: ignore[attr-defined]
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="Overwrite dirty files in the project dotfiles repository.",
        )
        parser.add_argument(
            "-u",
            "--update",
            action="store_true",
            default=False,
            help=(
                "Re-add every file already tracked in the project "
                "dotfiles repository. Identical files are skipped, so "
                "only changed files are actually copied. Combine with "
                "explicit FILES to include extra paths."
            ),
        )
        parser.set_defaults(rest=[])

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

        update = bool(getattr(self.cfg, "update", False))
        explicit_files = list(self.cfg.files or [])
        if not explicit_files and not update:
            log.error("No files given (specify FILES or use -u/--update).")
            return 1

        try:
            repo = GitRepo.discover(target)
        except NotAGitRepoError:
            log.error("Project root is not a git repository: %s", target)
            return 1

        repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
        for f in explicit_files:
            try:
                repo.ensure_path_excluded(Path(f))
            except ValueError as exc:
                log.error("%s", exc)
                return 1

        remainder = list(self.cfg.rest)
        if self.cfg.force:
            remainder.append("--force")
        if update:
            remainder.append("--update")
        remainder.extend(explicit_files)
        rc = self.passthrough(
            "add",
            remainder,
            global_args=["--source", str(source), "--target", str(target)],
        )
        if rc != 0:
            return rc

        # Stage the just-copied files inside the ishproject worktree.
        # `--force` overrides the shared .git/info/exclude patterns
        # written above. Only the paths we know ishfiles just produced
        # are staged, so unrelated edits in the worktree are left alone.
        # `require_root=True`: only stage when `source` is itself a
        # worktree root. If it is a bare directory inside another
        # repo (e.g. in unit tests that mkdir the path instead of
        # wiring up a real worktree) we skip.
        try:
            source_repo = GitRepo.discover(source, require_root=True)
        except NotAGitRepoError:
            return 0

        finder = DotfileFinder(
            IshConfig(defaults={"source": str(source), "target": str(target)})
        )
        if update:
            # In -u mode ishfiles re-adds every dotfile already in the
            # source. Stage those same paths in the worktree so the
            # project repo sees them as committed work, not untracked.
            rel_paths = [
                str(df.rel_path) for df in finder.discover() if df.target.is_file()
            ]
        else:
            rel_paths = [str(p) for p in finder.get_rel_paths(explicit_files)]
        if not rel_paths:
            return 0

        source_repo.runner = CommandRunner(
            cfg=IshConfig(dry_run=getattr(self.cfg, "dry_run", False))
        )
        try:
            source_repo.runner.git(
                ["add", "--force", "--", *rel_paths],
                work_dir=source,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            log.warning(
                "git add failed in project worktree (%s); files copied but not staged.",
                exc,
            )
            return 0
        return 0
