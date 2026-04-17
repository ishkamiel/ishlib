# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``add`` subcommand -- add files to the dotfiles repository."""

from __future__ import annotations

import argparse
import filecmp
import logging
import shutil

from ...ish_config import IshConfig
from ..applier import make_finder

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``add`` subcommand."""
    parser = subparsers.add_parser(
        "add",
        help="Add files to the dotfiles repository",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="File(s) to add to the dotfiles repository",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        default=False,
        help="Overwrite dirty files in the dotfiles repository",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the add command.

    For each file argument:

    1. Resolve it to a :class:`DotFile` via :class:`DotfileFinder`.
    2. The target must exist on the filesystem.
    3. If the source already exists and is identical, warn and skip.
    4. If the source exists and differs (dirty), refuse unless
       ``--force`` is given.
    5. Copy the target file into the source directory.

    Returns:
        0 on success, 1 if any file could not be added.
    """
    finder = make_finder(cfg)
    force = cfg.get_opt("force", False)
    files = cfg.get_opt("files", [])

    if not finder.source_dir.is_dir():
        log.error("Source directory does not exist: %s", finder.source_dir)
        return 1

    errors = 0
    added = 0

    for file_arg in files:
        dotfile = finder.get(file_arg)

        if dotfile is None:
            log.error("Cannot resolve file: %s", file_arg)
            errors += 1
            continue

        if not dotfile.target.is_file():
            log.error("File does not exist: %s", dotfile.target)
            errors += 1
            continue

        # Refuse if the source path is a directory (not a regular file)
        if dotfile.source.exists() and not dotfile.source.is_file():
            log.error("Source path is not a regular file: %s", dotfile.source)
            errors += 1
            continue

        # Check for duplicates
        if dotfile.source.exists():
            if filecmp.cmp(str(dotfile.source), str(dotfile.target), shallow=False):
                log.warning("Already tracked (identical): %s", dotfile.translated)
                continue

            # Source exists and differs -- dirty
            if not force:
                log.error(
                    "Refusing to overwrite dirty file in dotfiles repository: "
                    "%s (use -f/--force to override)",
                    dotfile.rel_path,
                )
                errors += 1
                continue

            log.info("Overwriting (--force): %s", dotfile.rel_path)

        # Copy file into source directory
        dotfile.source.parent.mkdir(parents=True, exist_ok=True)

        if cfg.dry_run:
            log.info("Would add: %s -> %s", dotfile.target, dotfile.source)
        else:
            shutil.copy2(str(dotfile.target), str(dotfile.source))
            log.info("Added: %s -> %s", dotfile.translated, dotfile.rel_path)

        added += 1

    if added and not cfg.dry_run:
        log.info("Added %d file(s).", added)

    return 1 if errors else 0
