#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``add`` subcommand -- add files to the dotfiles repository."""

from __future__ import annotations

import argparse
import filecmp
import logging
import shutil
import sys

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
        print(f"Source directory does not exist: {finder.source_dir}", file=sys.stderr)
        return 1

    errors = 0
    added = 0

    for file_arg in files:
        dotfile = finder.get(file_arg)

        if dotfile is None:
            print(f"Cannot resolve file: {file_arg}", file=sys.stderr)
            errors += 1
            continue

        if not dotfile.target.is_file():
            print(f"File does not exist: {dotfile.target}", file=sys.stderr)
            errors += 1
            continue

        # Check for duplicates
        if dotfile.source.exists():
            if dotfile.source.is_file() and filecmp.cmp(
                str(dotfile.source), str(dotfile.target), shallow=False
            ):
                print(f"Warning: already tracked (identical): {dotfile.translated}")
                continue

            # Source exists and differs -- dirty
            if not force:
                print(
                    f"Refusing to overwrite dirty file in dotfiles repository: "
                    f"{dotfile.rel_path} (use -f/--force to override)",
                    file=sys.stderr,
                )
                errors += 1
                continue

            print(f"Overwriting (--force): {dotfile.rel_path}")

        # Copy file into source directory
        dotfile.source.parent.mkdir(parents=True, exist_ok=True)

        if cfg.dry_run:
            print(f"Would add: {dotfile.target} -> {dotfile.source}")
        else:
            shutil.copy2(str(dotfile.target), str(dotfile.source))
            log.info("Added %s -> %s", dotfile.target, dotfile.source)
            if not cfg.quiet:
                print(f"Added: {dotfile.translated} -> {dotfile.rel_path}")

        added += 1

    if added and not cfg.quiet and not cfg.dry_run:
        print(f"Added {added} file(s).")

    return 1 if errors else 0
