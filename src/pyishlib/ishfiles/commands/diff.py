#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``diff`` subcommand -- show what would change without applying."""

from __future__ import annotations

import argparse
import difflib
import logging
from pathlib import Path
from typing import List

from ...dotfile import DotFile, ChangeType
from ...dotfile_preprocessor import DotFilePreprocessor
from ..config import IshfilesConfig
from ..scanner import IshfilesScanner

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``diff`` subcommand."""
    parser = subparsers.add_parser(
        "diff",
        help="Show a unified diff of what would change",
    )
    parser.set_defaults(func=run)


def run(ishfiles_cfg: IshfilesConfig) -> int:
    """Execute the diff command.

    Returns:
        0 when there are no changes, 1 when there are differences.
    """
    scanner = IshfilesScanner(
        source_dir=ishfiles_cfg.source_dir,
        target_dir=ishfiles_cfg.target_dir,
        extra_patterns=ishfiles_cfg.ignore_patterns,
    )
    dotfiles = scanner.scan()

    if not dotfiles:
        print("No dotfiles found.")
        return 0

    dotfiles = _prepare(dotfiles)
    changes = _get_changes(dotfiles)

    if not changes:
        print("Everything is up to date.")
        return 0

    for dotfile in changes:
        _print_diff(dotfile)

    return 1


def _prepare(dotfiles: list) -> list:
    """Run preprocessing on discovered dotfiles."""
    import shutil
    import tempfile

    staging_dir = tempfile.mkdtemp(prefix="ishfiles-")
    preprocessor = DotFilePreprocessor()

    for dotfile in dotfiles:
        staged_path = Path(staging_dir) / dotfile.translated
        staged_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            processed = preprocessor.preprocess(dotfile)
            staged_path.write_text(processed, encoding="utf-8")
        except UnicodeDecodeError:
            log.debug("Binary file, copying verbatim: %s", dotfile.source)
            shutil.copy2(dotfile.source, staged_path)

        dotfile.staged = staged_path

    return dotfiles


def _get_changes(dotfiles: list) -> list:
    """Filter to only dotfiles that would change the target."""
    changed = []
    for dotfile in dotfiles:
        if dotfile.get_change_type() is not None:
            changed.append(dotfile)
    return changed


def _print_diff(dotfile: DotFile) -> None:
    """Print a unified diff for a single dotfile."""
    change = dotfile.get_change_type()

    if change == ChangeType.NEW:
        print(f"--- /dev/null")
        print(f"+++ {dotfile.target}")
        try:
            source_lines = dotfile.effective_source.read_text(
                encoding="utf-8"
            ).splitlines(keepends=True)
            for line in source_lines:
                print(f"+{line}", end="")
            if source_lines and not source_lines[-1].endswith("\n"):
                print()
            print()
        except UnicodeDecodeError:
            print("+<binary file>")
            print()
        return

    # MODIFIED -- show unified diff
    try:
        target_lines = dotfile.target.read_text(encoding="utf-8").splitlines(
            keepends=True
        )
        source_lines = dotfile.effective_source.read_text(encoding="utf-8").splitlines(
            keepends=True
        )
    except UnicodeDecodeError:
        print(f"--- {dotfile.target}")
        print(f"+++ {dotfile.effective_source}")
        print("<binary files differ>")
        print()
        return

    diff = difflib.unified_diff(
        target_lines,
        source_lines,
        fromfile=str(dotfile.target),
        tofile=str(dotfile.effective_source),
    )
    diff_text = "".join(diff)
    if diff_text:
        print(diff_text)
