# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject status`` -- forward to ``ishfiles status`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...cli_passthrough import passthrough_to_cli
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
        "pointed at the current project.  All remaining arguments are "
        "forwarded to ishfiles."
    )
    ADD_COMMON_FLAGS = False

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles status`.",
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
        return passthrough_to_cli(
            ishfiles_main,
            subcommand="status",
            remainder=args.rest,
            global_args=["--source", str(source), "--target", str(target)],
            target_parser=ishfiles_build_parser(),
        )
