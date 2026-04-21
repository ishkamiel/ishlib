# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for ishfiles.

Entry point for the ``ishfiles`` tool.  Subcommands are declared as
:class:`~pyishlib.cli_command.CliCommand` subclasses in
:mod:`~pyishlib.ishfiles.commands` and listed on :class:`IshfilesCLI`.
"""

from __future__ import annotations

import argparse
from typing import Any, List, Optional

from ..cli_base import BaseCLI
from .commands.add import AddCommand
from .commands.apply import ApplyCommand
from .commands.cd import CdCommand
from .commands.commit import CommitCommand
from .commands.diff import DiffCommand
from .commands.doctor import DoctorCommand
from .commands.external import ExternalCommand
from .commands.git import GitCommand
from .commands.init import InitCommand
from .commands.install import InstallCommand
from .commands.log import LogCommand
from .commands.pd import PdCommand
from .commands.pull import PullCommand
from .commands.push import PushCommand
from .commands.runscripts import RunscriptsCommand
from .commands.status import StatusCommand
from .config import load_config
from .data import process_data_template


class IshfilesCLI(BaseCLI):
    """ishfiles CLI."""

    PROG = "ishfiles"
    DESCRIPTION = "Manage dotfiles from an ishfiles repository."
    COMMANDS = (
        AddCommand,
        ApplyCommand,
        CdCommand,
        CommitCommand,
        DiffCommand,
        DoctorCommand,
        ExternalCommand,
        GitCommand,
        InitCommand,
        InstallCommand,
        LogCommand,
        PdCommand,
        PullCommand,
        PushCommand,
        RunscriptsCommand,
        StatusCommand,
    )

    def add_global_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--home",
            metavar="DIR",
            default=None,
            help=(
                "Override home directory for all default paths "
                "(source, target, config). Individual -s/-t/-c still override."
            ),
        )
        parser.add_argument(
            "-s",
            "--source",
            metavar="DIR",
            default=None,
            help="Path to the ishfiles source folder (default: ~/.local/share/ishfiles)",
        )
        parser.add_argument(
            "-t",
            "--target",
            metavar="DIR",
            default=None,
            help="Target directory for dotfile installation (default: $HOME)",
        )
        parser.add_argument(
            "-c",
            "--config",
            metavar="FILE",
            default=None,
            help="Path to the config file (default: ~/.config/ishfiles/config.toml)",
        )
        parser.add_argument(
            "--custom-username",
            metavar="NAME",
            default=None,
            help=(
                "Target user for user-scoped operations (e.g. chsh). "
                "Also exposed to scripts as ${__ish_username}. "
                "Defaults to the current user."
            ),
        )

    def resolve_config(self, args: argparse.Namespace) -> Any:
        cfg = load_config(args=args)
        process_data_template(cfg, isholate=bool(getattr(args, "isholate", False)))
        return cfg


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser (exported for tests / passthrough)."""
    return IshfilesCLI().build_parser()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    return IshfilesCLI().main(argv)
