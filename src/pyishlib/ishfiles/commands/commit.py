# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``commit`` subcommand -- commit all changes in the dotfiles repository."""

from __future__ import annotations

import argparse
import sys

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError
from ..applier import make_finder

_DEFAULT_MESSAGE = "Update ishfiles"


class CommitCommand(CliCommand):
    """Commit all changes in the dotfiles repository."""

    NAME = "commit"
    HELP = "Commit all changes in the dotfiles repository"
    DESCRIPTION = (
        "Runs ``git commit -a`` on the dotfiles source directory.  "
        "Stages and commits all tracked modifications.  Defaults to the "
        f"message ``{_DEFAULT_MESSAGE}``; override with ``-m``.  "
        "Pass ``--push`` to also push after a successful commit."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-m",
            "--message",
            default=_DEFAULT_MESSAGE,
            metavar="MSG",
            help=f"Commit message (default: {_DEFAULT_MESSAGE!r})",
        )
        parser.add_argument(
            "--push",
            action="store_true",
            help="After committing, run `git push` on the dotfiles repository.",
        )

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

        repo.runner = CommandRunner(self.cfg)
        message = self.cfg.get_opt("message", _DEFAULT_MESSAGE)
        result = repo.commit_all(message)
        if result.returncode != 0:
            return result.returncode
        if self.cfg.get_opt("push", False):
            return repo.push().returncode
        return 0
