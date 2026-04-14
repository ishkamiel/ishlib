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
import logging
from typing import List, Optional

from ..ish_logging import setup_logging
from .commands import (
    add,
    apply,
    cd,
    diff,
    external,
    git,
    init,
    install,
    log,
    pd,
    runscripts,
)
from .config import load_config
from .data import process_data_template


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="ishfiles",
        description="Manage dotfiles from an ishfiles repository.",
    )

    # -- global options -------------------------------------------------------
    parser.add_argument(
        "--home",
        metavar="DIR",
        default=None,
        help="Override home directory for all default paths "
        "(source, target, config). Individual -s/-t/-c still override.",
    )
    parser.add_argument(
        "-s",
        "--source",
        metavar="DIR",
        default=None,
        help="Path to the ishfiles source folder (default: ~/.local/share/ishfiles)",
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
        help="Path to the config file (default: ~/.config/ishfiles/config.toml)",
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
    parser.add_argument(
        "--log-file",
        metavar="FILE",
        default=None,
        help="Append all log output (DEBUG and above) to this file, "
        "regardless of terminal verbosity. Used by isholate to retrieve "
        "in-container diagnostics.",
    )
    parser.add_argument(
        "--custom-username",
        metavar="NAME",
        default=None,
        help="Target user for user-scoped operations (e.g. chsh). "
        "Also exposed to scripts as ${__ish_username}. "
        "Defaults to the current user.",
    )

    # -- subcommands ----------------------------------------------------------
    subparsers = parser.add_subparsers(dest="command")
    add.register(subparsers)
    apply.register(subparsers)
    cd.register(subparsers)
    diff.register(subparsers)
    external.register(subparsers)
    git.register(subparsers)
    init.register(subparsers)
    install.register(subparsers)
    log.register(subparsers)
    pd.register(subparsers)
    runscripts.register(subparsers)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
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

    # Set up logging early from CLI flags so TOML loading warnings
    # respect --verbose/--debug/--quiet.
    log_file = getattr(args, "log_file", None)
    quiet = getattr(args, "quiet", False)
    if args.debug:
        setup_logging(logging.DEBUG, log_file=log_file, quiet=quiet)
    elif args.verbose:
        setup_logging(logging.INFO, log_file=log_file, quiet=quiet)
    elif quiet:
        setup_logging(logging.ERROR, log_file=log_file, quiet=quiet)
    else:
        setup_logging(logging.WARNING, log_file=log_file, quiet=quiet)

    cfg = load_config(args=args)
    setup_logging(cfg.log_level, log_file=log_file, quiet=quiet)

    process_data_template(cfg, isholate=bool(getattr(args, "isholate", False)))

    return args.func(cfg)
