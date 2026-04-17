# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for ishproject.

Entry point for the ``ishproject`` tool.  Subcommands are registered by
modules in :mod:`~pyishlib.ishproject.commands`.
"""

from __future__ import annotations

import argparse
from typing import List, Optional

from .commands import add, apply, diff, init


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ishproject",
        description="Apply project-scoped ishfiles dotfiles.",
    )
    subparsers = parser.add_subparsers(dest="command")
    add.register(subparsers)
    apply.register(subparsers)
    diff.register(subparsers)
    init.register(subparsers)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    # Subcommands that forward to ishfiles collect their forwarded
    # arguments via ``args.rest``; argparse.REMAINDER alone trips on
    # leading ``--`` flags after the subcommand name (Python issue
    # 9334), so we backfill unknowns here.
    if hasattr(args, "rest"):
        args.rest = list(args.rest) + unknown
    elif unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    return args.func(args)
