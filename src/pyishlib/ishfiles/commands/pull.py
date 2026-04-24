# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``pull`` subcommand -- pull (rebase) the dotfiles repository from remote."""

from __future__ import annotations

import argparse
import sys

from ...cli_command import CliCommand
from ...git_repo import GitRepo, NotAGitRepoError
from ..applier import make_finder


class PullCommand(CliCommand):
    """Pull (rebase) the dotfiles repository from its remote."""

    NAME = "pull"
    HELP = "Pull (rebase) the dotfiles repository from its remote"
    DESCRIPTION = (
        "Runs ``git pull --rebase`` on the dotfiles source directory.  "
        "Always rebases; for merge-based pulls use ``ishfiles git pull``."
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

        result = repo.pull_rebase()
        return result.returncode
