# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``git`` subcommand -- run git in the dotfiles repository."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from ...ish_config import IshConfig
from ..applier import make_finder


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

    File-path arguments that resolve to known dotfiles are translated
    to their source-relative equivalents so that, for example,
    ``ishfiles git diff ~/.bashrc`` becomes ``git diff dot_bashrc``
    inside the source repository.

    Returns:
        The exit code from the git process.
    """
    finder = make_finder(cfg)

    if not finder.source_dir.is_dir():
        print(f"Source directory does not exist: {finder.source_dir}", file=sys.stderr)
        return 1

    git_args = cfg.get_opt("git_args", [])
    # translate_arg is safe for non-file arguments (flags, refs, etc.)
    # -- it returns them unchanged when they don't resolve to a dotfile.
    translated = [finder.translate_arg(a) for a in git_args]
    cmd = ["git"] + translated

    # Strip GIT_* environment variables so the subprocess discovers its own
    # git repository from cwd rather than inheriting GIT_DIR (or similar)
    # set by a parent git process (e.g. when running inside a git hook).
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    try:
        result = subprocess.run(cmd, cwd=finder.source_dir, check=False, env=env)
    except FileNotFoundError:
        print(
            "git executable not found. Please install git or ensure it is in PATH.",
            file=sys.stderr,
        )
        return 1
    return result.returncode
