#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``cd`` subcommand -- print the dotfiles source directory.

A child process cannot change the parent shell's working directory, so
this command instead prints the resolved source directory path.  Wrap it
in a shell function or alias to ``cd`` into it::

    ishcd() { cd "$(ishfiles cd)" || return; }
"""

from __future__ import annotations

import argparse
import sys

from ...ish_config import IshConfig
from ..applier import make_finder


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``cd`` subcommand."""
    parser = subparsers.add_parser(
        "cd",
        help="Print the dotfiles source directory (for shell `cd` wrappers)",
        description=(
            "Print the resolved ishfiles source directory.  Use with a "
            'shell wrapper, e.g. `ishcd() { cd "$(ishfiles cd)" || return; }`.'
        ),
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Print the resolved source directory to stdout.

    Returns:
        0 if the source directory exists, 1 otherwise.
    """
    finder = make_finder(cfg)
    source_dir = finder.source_dir

    print(source_dir)

    if not source_dir.is_dir():
        print(
            f"Source directory does not exist: {source_dir}",
            file=sys.stderr,
        )
        return 1
    return 0
