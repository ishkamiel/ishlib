# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject add`` -- forward to ``ishfiles add`` and update info/exclude."""

from __future__ import annotations

import argparse
import logging
import subprocess
from pathlib import Path

from ...cli_command import CliCommand
from ...cli_passthrough import passthrough_to_cli
from ...command_runner import CommandRunner
from ...completions import FILE as _COMPLETE_FILE
from ...dotfile_finder import DotfileFinder
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ...ishlib_folder import PROJECT_DIR_NAME
from ..config import IshprojectConfig

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
    # Common flags (-v/--debug/-q/-n/--log-file) are forwarded to ishfiles
    # via parse_known_args; they are not declared on this subparser.
    ADD_COMMON_FLAGS = False

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        files_arg = parser.add_argument(
            "files",
            nargs="+",
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
        parser.set_defaults(rest=[])

    def run(self, args: argparse.Namespace) -> int:
        cfg: IshprojectConfig = args.ishproject_cfg
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

        try:
            repo = GitRepo.discover(target)
        except NotAGitRepoError:
            log.error("Project root is not a git repository: %s", target)
            return 1

        repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
        for f in args.files:
            try:
                repo.ensure_path_excluded(Path(f))
            except ValueError as exc:
                log.error("%s", exc)
                return 1

        remainder = list(args.rest)
        if args.force:
            remainder.append("--force")
        remainder.extend(args.files)
        rc = passthrough_to_cli(
            ishfiles_main,
            subcommand="add",
            remainder=remainder,
            global_args=["--source", str(source), "--target", str(target)],
            target_parser=ishfiles_build_parser(),
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
        rel_paths = [str(p) for p in finder.get_rel_paths(args.files)]
        if not rel_paths:
            return 0

        source_repo.runner = CommandRunner(
            cfg=IshConfig(dry_run=getattr(args, "dry_run", False))
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
