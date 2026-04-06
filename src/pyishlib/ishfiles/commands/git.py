#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``git`` subcommand -- run git in the dotfiles repository."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ...ish_config import IshConfig


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``git`` subcommand."""
    parser = subparsers.add_parser(
        "git",
        help="Run a git command inside the dotfiles repository",
    )
    parser.add_argument(
        "git_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed directly to git",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute a git command in the dotfiles source directory.

    Returns:
        The exit code from the git process.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser()

    if not source_dir.is_dir():
        print(f"Source directory does not exist: {source_dir}", file=sys.stderr)
        return 1

    git_args = cfg.get_opt("git_args", [])
    cmd = ["git"] + list(git_args)

    result = subprocess.run(cmd, cwd=source_dir)
    return result.returncode
