#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from ...ish_config import IshConfig
from ..applier import make_applier
from ..resolve import resolve_file_args


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``apply`` subcommand."""
    parser = subparsers.add_parser(
        "apply",
        help="Apply dotfiles from the ishfiles folder to the target directory",
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=None,
        help="Restrict to specific files (source or target paths)",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the apply command.

    Returns:
        0 always (the applier handles user prompts internally).
    """
    applier = make_applier(cfg)

    files = cfg.get_opt("files") or None
    rel_files = None
    if files:
        source_dir = Path(cfg.get_opt("source")).expanduser()
        target_dir = Path(cfg.get_opt("target")).expanduser()
        rel_files = resolve_file_args(files, source_dir, target_dir)

    applied = applier.apply(files=rel_files)
    if applied and not cfg.quiet:
        print(f"Applied {applied} file(s).")
    return 0
