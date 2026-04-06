#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``diff`` subcommand -- show what would change without applying."""

from __future__ import annotations

import argparse
from pathlib import Path

from ...diff import print_diff, print_new_file, print_binary_diff
from ...dotfile import DotFile, ChangeType
from ...ish_config import IshConfig
from ..applier import make_applier
from ..resolve import resolve_file_args


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``diff`` subcommand."""
    parser = subparsers.add_parser(
        "diff",
        help="Show a unified diff of what would change",
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=None,
        help="Restrict to specific files (source or target paths)",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the diff command.

    Returns:
        0 when there are no changes, 1 when there are differences.
    """
    applier = make_applier(cfg)

    files = cfg.get_opt("files") or None
    rel_files = None
    if files:
        source_dir = Path(cfg.get_opt("source")).expanduser()
        target_dir = Path(cfg.get_opt("target")).expanduser()
        rel_files = resolve_file_args(files, source_dir, target_dir)

    dotfiles = applier.discover(files=rel_files)
    if not dotfiles:
        if not cfg.quiet:
            print("No dotfiles found.")
        return 0

    dotfiles = applier.prepare(dotfiles)
    changes = applier.get_changes(dotfiles)

    if not changes:
        if not cfg.quiet:
            print("Everything is up to date.")
        return 0

    for dotfile in changes:
        _show_diff(dotfile)

    return 1


def _show_diff(dotfile: DotFile) -> None:
    """Print a diff for a single dotfile using :mod:`pyishlib.diff`."""
    change = dotfile.get_change_type()

    if change == ChangeType.NEW:
        try:
            dotfile.effective_source.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            print_binary_diff("/dev/null", str(dotfile.target))
            return
        print_new_file(dotfile.effective_source, str(dotfile.target))
        return

    # MODIFIED
    try:
        dotfile.target.read_bytes().decode("utf-8")
        dotfile.effective_source.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        print_binary_diff(str(dotfile.target), str(dotfile.effective_source))
        return

    print_diff(
        dotfile.target,
        dotfile.effective_source,
        old_label=str(dotfile.target),
        new_label=str(dotfile.effective_source),
    )
