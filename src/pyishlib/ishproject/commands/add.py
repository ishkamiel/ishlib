# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject add`` -- forward to ``ishfiles add`` and update info/exclude."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...cli_passthrough import passthrough_to_cli
from ...git_repo import GitRepo, NotAGitRepoError
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ...ishlib_folder import PROJECT_DIR_NAME
from ..config import resolve_project_paths

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
        parser.add_argument(
            "files",
            nargs="+",
            help="File(s) to add to the project dotfiles repository.",
        )
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="Overwrite dirty files in the project dotfiles repository.",
        )
        parser.set_defaults(rest=[])

    def run(self, args: argparse.Namespace) -> int:
        source, target = resolve_project_paths(Path.cwd())
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
        return passthrough_to_cli(
            ishfiles_main,
            subcommand="add",
            remainder=remainder,
            global_args=["--source", str(source), "--target", str(target)],
            target_parser=ishfiles_build_parser(),
        )
