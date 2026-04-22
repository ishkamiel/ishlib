# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject commit`` -- forward to ``ishfiles commit`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...cli_passthrough import passthrough_to_cli
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from .._precommit import allow_missing_precommit_config
from ..config import IshprojectConfig

log = logging.getLogger(__name__)


class CommitCommand(CliCommand):
    """Commit all changes in the project dotfiles repository."""

    NAME = "commit"
    HELP = "Commit all changes in the active ishproject dotfiles repository"
    DESCRIPTION = (
        "Thin wrapper around `ishfiles commit` with --source and --target "
        "pointed at the current project.  All remaining arguments (e.g. "
        "`-m MSG`) are forwarded to ishfiles."
    )
    ADD_COMMON_FLAGS = False

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles commit`.",
        )

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
        with allow_missing_precommit_config():
            return passthrough_to_cli(
                ishfiles_main,
                subcommand="commit",
                remainder=args.rest,
                global_args=["--source", str(source), "--target", str(target)],
                target_parser=ishfiles_build_parser(),
            )
