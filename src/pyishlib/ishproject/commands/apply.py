# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject apply`` -- forward to ``ishfiles apply`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...cli_passthrough import passthrough_to_cli
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ..config import resolve_project_paths

log = logging.getLogger(__name__)


class ApplyCommand(CliCommand):
    """Apply project dotfiles from ``.ishlib/ishproject`` to the project root."""

    NAME = "apply"
    HELP = "Apply project dotfiles from .ishlib/ishproject to the project root"
    DESCRIPTION = (
        "Thin wrapper around `ishfiles apply` with --source and --target "
        "pointed at the current project. All remaining arguments are "
        "forwarded to ishfiles."
    )
    ADD_COMMON_FLAGS = False

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles apply`.",
        )

    def run(self, args: argparse.Namespace) -> int:
        source, target = resolve_project_paths(Path.cwd())
        if not source.is_dir():
            log.error(
                "Project dotfiles directory does not exist: %s "
                "(run `ishproject init` first)",
                source,
            )
            return 1
        return passthrough_to_cli(
            ishfiles_main,
            subcommand="apply",
            remainder=args.rest,
            global_args=["--source", str(source), "--target", str(target)],
            target_parser=ishfiles_build_parser(),
        )
