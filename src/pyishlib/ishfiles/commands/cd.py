#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``cd`` subcommand -- open a shell in the dotfiles source directory."""

from __future__ import annotations

import argparse
import os
import shlex
import sys

from ...ish_config import IshConfig
from ..applier import make_finder


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``cd`` subcommand."""
    parser = subparsers.add_parser(
        "cd",
        help="Open a shell in the dotfiles source directory",
        description="Change into the ishfiles source directory by spawning a new shell there.",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Exec a new interactive shell in the dotfiles source directory.

    Returns:
        1 if the source directory does not exist; otherwise does not return
        (os.execvp replaces the process).
    """
    finder = make_finder(cfg)
    source_dir = finder.source_dir

    if not source_dir.is_dir():
        print(
            f"ishfiles cd: source directory does not exist: {source_dir}",
            file=sys.stderr,
        )
        return 1

    shell_str = os.environ.get("SHELL", "sh")
    shell_argv = shlex.split(shell_str) or ["sh"]

    if cfg.dry_run:
        print(f"cd {source_dir}", file=sys.stderr)
        print(f"exec {shell_str}", file=sys.stderr)
        return 0

    print(
        f"ishfiles cd: spawning a subshell in {source_dir}\n"
        '  (for a real cd, add `eval "$(ishfiles init)"` to your shell rc)',
        file=sys.stderr,
    )
    try:
        os.chdir(source_dir)
        os.execvp(shell_argv[0], shell_argv)  # does not return
    except OSError as exc:
        print(f"ishfiles cd: {exc}", file=sys.stderr)
        return 1
