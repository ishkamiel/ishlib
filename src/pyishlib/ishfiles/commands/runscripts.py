#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``runscripts`` subcommand -- execute scripts from the ishscripts folder."""

from __future__ import annotations

import argparse

from ...ish_config import IshConfig
from ..script_runner import run_scripts


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``runscripts`` subcommand."""
    parser = subparsers.add_parser(
        "runscripts",
        help="Run scripts from the ishscripts folder",
    )
    parser.add_argument(
        "scripts",
        nargs="*",
        default=None,
        help="Restrict to specific script names (default: all)",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the runscripts command.

    Returns:
        0 on success, 1 on error.
    """
    scripts = cfg.get_opt("scripts") or None
    return run_scripts(cfg, scripts=scripts)
