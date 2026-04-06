#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``install`` subcommand -- install packages from the ishfiles config."""

from __future__ import annotations

import argparse

from ...ish_config import IshConfig
from ..installer_helper import run_install


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``install`` subcommand."""
    parser = subparsers.add_parser(
        "install",
        help="Install packages defined in the ishfiles package config",
    )
    parser.add_argument(
        "packages",
        nargs="*",
        default=None,
        help="Restrict to specific package names (default: all)",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the install command.

    Returns:
        0 on success, 1 on error.
    """
    packages = cfg.get_opt("packages") or None
    return run_install(cfg, packages=packages)
