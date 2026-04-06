#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Command-line interface for ishfiles.

Entry point for the ``ishfiles`` tool.  Subcommands are registered by
modules in :mod:`~pyishlib.ishfiles.commands`.
"""

from __future__ import annotations

import argparse
import sys

from ..ish_comp import setup_logging
from .commands import apply, diff
from .config import IshfilesConfig


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ishfiles",
        description="Manage dotfiles from an ishfiles repository.",
    )

    # -- global options -------------------------------------------------------
    parser.add_argument(
        "-s",
        "--source",
        metavar="DIR",
        default=None,
        help="Path to the ishfiles source folder " "(default: ~/.local/share/ishfiles)",
    )
    parser.add_argument(
        "-t",
        "--target",
        metavar="DIR",
        default=None,
        help="Target directory for dotfile installation (default: $HOME)",
    )
    parser.add_argument(
        "-c",
        "--config",
        metavar="FILE",
        default=None,
        help="Path to the config file " "(default: ~/.config/ishfiles/config.toml)",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug output",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress non-essential output",
    )

    # -- subcommands ----------------------------------------------------------
    subparsers = parser.add_subparsers(dest="command")
    apply.register(subparsers)
    diff.register(subparsers)

    return parser


def main(argv: list | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    ishfiles_cfg = IshfilesConfig.load(args=args)
    setup_logging(ishfiles_cfg.log_level)

    return args.func(ishfiles_cfg)


if __name__ == "__main__":
    sys.exit(main())
