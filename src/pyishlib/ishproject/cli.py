# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for ishproject.

Entry point for the ``ishproject`` tool.  Passthrough subcommands
(``add``, ``apply``, ``diff``) forward arguments to ishfiles via
:mod:`pyishlib.cli_passthrough`; ``init`` is a local implementation.
"""

from __future__ import annotations

import argparse
from typing import List, Optional

from ..cli_base import BaseCLI
from .commands.add import AddCommand
from .commands.apply import ApplyCommand
from .commands.clean_rebase import CleanRebaseCommand
from .commands.diff import DiffCommand
from .commands.init import InitCommand
from .commands.merge import MergeCommand


class IshprojectCLI(BaseCLI):
    """ishproject CLI."""

    PROG = "ishproject"
    DESCRIPTION = "Apply project-scoped ishfiles dotfiles."
    COMMANDS = (
        AddCommand,
        ApplyCommand,
        CleanRebaseCommand,
        DiffCommand,
        InitCommand,
        MergeCommand,
    )
    # The passthrough commands (add/apply/diff) delegate flag handling to
    # ishfiles, so unknown tokens must be forwarded through ``args.rest``
    # rather than rejected by the top-level parser.
    COLLECT_UNKNOWN = True


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    return IshprojectCLI().build_parser()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    return IshprojectCLI().main(argv)
