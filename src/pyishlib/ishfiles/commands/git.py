# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``git`` subcommand -- run git in the dotfiles repository."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from ...cli_command import CliCommand
from ...ish_config import IshConfig
from ..applier import make_finder


class GitCommand(CliCommand):
    """Run a git command inside the dotfiles repository."""

    NAME = "git"
    HELP = "Run a git command inside the dotfiles repository"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "git_args",
            nargs=argparse.REMAINDER,
            help="Arguments passed directly to git",
        )

    def run(self, cfg: IshConfig) -> int:
        """Execute a git command in the dotfiles source directory."""
        finder = make_finder(cfg)

        if not finder.source_dir.is_dir():
            print(
                f"Source directory does not exist: {finder.source_dir}", file=sys.stderr
            )
            return 1

        git_args = cfg.get_opt("git_args", [])
        translated = [finder.translate_arg(a) for a in git_args]
        cmd = ["git"] + translated

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
