#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...dotfile_applier import DotfileApplier
from ...dotfile_ignore import DotfileIgnore, ISHFILES_IGNORE_DIRS, ISHIGNORE_FILE
from ...ish_config import IshConfig

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
    source_dir = Path(cfg.get_opt("source")).expanduser()
    target_dir = Path(cfg.get_opt("target")).expanduser()

    di = DotfileIgnore(
        source_dir=source_dir,
        ignore_file=ISHIGNORE_FILE,
        extra_names=ISHFILES_IGNORE_DIRS | frozenset({ISHIGNORE_FILE}),
        extra_patterns=cfg.get_opt("patterns", []),
    )

    applier = DotfileApplier(
        source_dir=source_dir,
        target_dir=target_dir,
        cfg=cfg,
        dotfile_ignore=di,
    )

    applied = applier.apply()
    if applied:
        print(f"Applied {applied} file(s).")
    return 0
