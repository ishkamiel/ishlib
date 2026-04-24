# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``push`` subcommand -- push dotfiles repository to remote."""

from __future__ import annotations

import argparse
import sys

from ...cli_command import CliCommand
from ...git_repo import GitRepo, NotAGitRepoError
from ..applier import make_finder


class PushCommand(CliCommand):
    """Push the dotfiles repository to its remote."""

    NAME = "push"
    HELP = "Push the dotfiles repository to its remote"
    DESCRIPTION = (
        "Runs ``git push`` on the dotfiles source directory.  "
        "For non-default remote or branch, use ``ishfiles git push …``."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self) -> int:
        finder = make_finder(self.cfg)

        if not finder.source_dir.is_dir():
            print(
                f"Source directory does not exist: {finder.source_dir}",
                file=sys.stderr,
            )
            return 1

        try:
            repo = GitRepo.discover(finder.source_dir)
        except NotAGitRepoError:
            print(
                f"Source directory is not a git repository: {finder.source_dir}",
                file=sys.stderr,
            )
            return 1

        result = repo.push()
        return result.returncode
