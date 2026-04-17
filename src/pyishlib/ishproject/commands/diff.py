# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject diff`` -- forward to ``ishfiles diff`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_passthrough import passthrough_to_cli
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ..config import resolve_project_paths

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``diff`` subcommand."""
    parser = subparsers.add_parser(
        "diff",
        help="Show pending project-dotfile changes without applying them",
        description=(
            "Thin wrapper around `ishfiles diff` with --source and --target "
            "pointed at the current project. All remaining arguments are "
            "forwarded to ishfiles."
        ),
    )
    parser.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to `ishfiles diff`.",
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    """Execute the passthrough."""
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
        subcommand="diff",
        remainder=args.rest,
        global_args=["--source", str(source), "--target", str(target)],
        target_parser=ishfiles_build_parser(),
    )
