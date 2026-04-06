#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging

from ...dotfile_applier import DotfileApplier
from ...ish_config import IshConfig
from ..ignore import build_ignore

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
    from pathlib import Path

    source_dir = Path(cfg.get_opt("source")).expanduser()
    target_dir = Path(cfg.get_opt("target")).expanduser()
    ignore_names, ignore_patterns = build_ignore(
        source_dir, cfg.get_opt("ignore_patterns", [])
    )

    applier = DotfileApplier(
        source_dir=source_dir,
        target_dir=target_dir,
        cfg=cfg,
        ignore=ignore_names,
        ignore_patterns=ignore_patterns,
    )

    applied = applier.apply()
    if applied:
        print(f"Applied {applied} file(s).")
    return 0
