# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for isholate.

Entry point for the ``isholate`` tool.  Exposes four subcommands:

* ``run``   — launch a container and exec a command (or interactive shell).
* ``purge`` — delete the user's isholate containers.
* ``list``  — print a table of isholate containers.
* ``stop``  — stop running isholate containers.
"""

from __future__ import annotations

import argparse
import logging
from typing import List, Optional

from ..cli_base import BaseCLI
from ..container.incus import check_incus_available
from ..environment import is_linux
from .commands.list import ListCommand
from .commands.purge import PurgeCommand
from .commands.run import DEFAULT_IMAGE, DEFAULT_SHELL, RunCommand
from .commands.stop import StopCommand

__all__ = [
    "DEFAULT_IMAGE",
    "DEFAULT_SHELL",
    "IsholateCLI",
    "build_parser",
    "main",
]

log = logging.getLogger(__name__)


class IsholateCLI(BaseCLI):
    """isholate CLI."""

    PROG = "isholate"
    DESCRIPTION = (
        "Launch an isolated Incus container with the host user mirrored. "
        "Persistent base containers cache expensive provisioning steps so "
        "subsequent runs start in seconds."
    )
    COMMANDS = (RunCommand, PurgeCommand, ListCommand, StopCommand)
    SUBPARSER_DEST = "subcommand"
    SUBPARSER_METAVAR = "COMMAND"
    SUBPARSER_REQUIRED = True

    def default_argv(self, argv: List[str]) -> List[str]:
        """With no args, default to the ``run`` subcommand."""
        return argv if argv else ["run"]

    def preflight(self, args: argparse.Namespace) -> Optional[int]:
        if not is_linux():
            log.critical("isholate is only supported on Linux")
            return 1
        incus_guidance = check_incus_available()
        if incus_guidance is not None:
            log.error("%s", incus_guidance)
            return 1
        return None


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for isholate."""
    return IsholateCLI().build_parser()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    return IsholateCLI().main(argv)
