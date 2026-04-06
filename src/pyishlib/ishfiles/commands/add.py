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
from pathlib import Path
from typing import Optional

from ...dotfile import reverse_translate_path
from ...ish_config import IshConfig

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

    1. Resolve the file to an absolute target path (under *target_dir*).
    2. Compute the corresponding source path (with ``dot_`` translation).
    3. If the source file already exists and is identical, warn and skip.
    4. If the source file exists and differs (dirty), refuse unless
       ``--force`` is given.
    5. Copy the target file into the source directory.

    Returns:
        0 on success, 1 if any file could not be added.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser()
    target_dir = Path(cfg.get_opt("target")).expanduser()
    force = cfg.get_opt("force", False)
    files = cfg.get_opt("files", [])

    if not source_dir.is_dir():
        print(f"Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    errors = 0
    added = 0

    for file_arg in files:
        target_path = _resolve_target(file_arg, target_dir)

        if target_path is None:
            print(f"Cannot resolve file: {file_arg}", file=sys.stderr)
            errors += 1
            continue

        if not target_path.is_file():
            print(f"File does not exist: {target_path}", file=sys.stderr)
            errors += 1
            continue

        # Compute relative path under target_dir and reverse-translate
        try:
            rel_target = target_path.resolve().relative_to(target_dir.resolve())
        except ValueError:
            print(
                f"File {target_path} is not under target directory {target_dir}",
                file=sys.stderr,
            )
            errors += 1
            continue

        rel_source = reverse_translate_path(rel_target)
        source_path = source_dir / rel_source

        # Check for duplicates
        if source_path.exists():
            if source_path.is_file() and filecmp.cmp(
                str(source_path), str(target_path), shallow=False
            ):
                print(f"Warning: already tracked (identical): {rel_target}")
                continue

            # Source exists and differs -- dirty
            if not force:
                print(
                    f"Refusing to overwrite dirty file in dotfiles repository: "
                    f"{rel_source} (use -f/--force to override)",
                    file=sys.stderr,
                )
                errors += 1
                continue

            print(f"Overwriting (--force): {rel_source}")

        # Copy file into source directory
        source_path.parent.mkdir(parents=True, exist_ok=True)

        if cfg.dry_run:
            print(f"Would add: {target_path} -> {source_path}")
        else:
            shutil.copy2(str(target_path), str(source_path))
            log.info("Added %s -> %s", target_path, source_path)
            if not cfg.quiet:
                print(f"Added: {rel_target} -> {rel_source}")

        added += 1

    if added and not cfg.quiet and not cfg.dry_run:
        print(f"Added {added} file(s).")

    return 1 if errors else 0


def _resolve_target(file_arg: str, target_dir: Path) -> Optional[Path]:
    """Resolve a file argument to an absolute target path.

    The argument may be an absolute path, a path relative to CWD,
    or a path relative to the target directory.
    """
    p = Path(file_arg).expanduser()

    # Absolute path
    if p.is_absolute():
        return p

    # Relative to CWD
    cwd_path = Path.cwd() / p
    if cwd_path.exists():
        return cwd_path

    # Relative to target dir
    target_path = target_dir / p
    if target_path.exists():
        return target_path

    # Default: treat as relative to target dir even if it doesn't exist
    return cwd_path if cwd_path.parent.exists() else None
