# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject add`` -- forward to ``ishfiles add`` and update info/exclude."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_passthrough import passthrough_to_cli
from ...git_repo import GitRepo, NotAGitRepoError
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ...ishlib_folder import PROJECT_DIR_NAME
from ..config import resolve_project_paths

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``add`` subcommand."""
    parser = subparsers.add_parser(
        "add",
        help="Add files to the project dotfiles repository",
        description=(
            "Thin wrapper around `ishfiles add` with --source and --target "
            "pointed at the current project. Before forwarding, each file "
            "is added to the project repo's .git/info/exclude so the "
            "managed copy is not tracked by the project repo."
        ),
    )
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
    # Captures additional flags forwarded to ishfiles (e.g. --dry-run,
    # --verbose). Backfilled by the wrapping CLI with anything its
    # top-level parse_known_args left over.
    parser.set_defaults(func=run, rest=[])


def run(args: argparse.Namespace) -> int:
    """Execute the add: register exclude patterns then forward to ishfiles."""
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
