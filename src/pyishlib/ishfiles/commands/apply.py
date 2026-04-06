#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging

from ...ish_config import IshConfig
from ..applier import make_applier

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``apply`` subcommand."""
    parser = subparsers.add_parser(
        "apply",
        help="Apply dotfiles from the ishfiles folder to the target directory",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the apply command.

    Returns:
        0 on success, 1 on failure.
    """
    applier = make_applier(cfg)
    applied = applier.apply()
    if applied:
        print(f"Applied {applied} file(s).")
    return 0
