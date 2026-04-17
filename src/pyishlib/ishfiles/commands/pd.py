# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``pd`` subcommand -- print the dotfiles source directory.

Intended for scripting and as the backend used by the shell wrapper
installed via ``ishfiles init``::

    eval "$(ishfiles init)"   # adds ishfiles() shell function
    ishfiles cd               # now does a real cd via `ishfiles pd`
"""

from __future__ import annotations

import argparse
import sys

from ...ish_config import IshConfig
from ..applier import make_finder


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``pd`` subcommand."""
    parser = subparsers.add_parser(
        "pd",
        help="Print the dotfiles source directory",
        description=(
            "Print the resolved ishfiles source directory to stdout.  "
            "Used by the shell wrapper from `ishfiles init` to resolve "
            "the path before cd-ing into it."
        ),
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Print the resolved source directory to stdout.

    Always exits 0 so ``cd "$(ishfiles pd)"`` works under ``set -e`` --
    a non-zero exit inside a command substitution would abort the caller
    before ``cd`` runs.  If the directory is missing a warning is printed
    to stderr; ``cd`` itself will then surface the error.

    Returns:
        Always 0.
    """
    finder = make_finder(cfg)
    source_dir = finder.source_dir

    print(source_dir)

    if not source_dir.is_dir():
        print(
            f"ishfiles pd: warning: source directory does not exist: {source_dir}",
            file=sys.stderr,
        )
    return 0
