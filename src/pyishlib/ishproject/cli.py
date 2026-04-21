# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for ishproject.

Entry point for the ``ishproject`` tool.  Passthrough subcommands
(``add``, ``apply``, ``diff``) forward arguments to ishfiles via
:mod:`pyishlib.cli_passthrough`; ``init``, ``branch``, ``merge``, and
``clean-rebase`` are local implementations.

The per-user ishproject config is loaded once at CLI entry via
:func:`~pyishlib.ishproject.config.load_config` and attached to
``args.ishproject_cfg`` so every subcommand sees the same resolved
prefix/postfix without re-prompting.
"""

from __future__ import annotations

import argparse
from typing import List, Optional

from ..cli_base import BaseCLI
from .commands.add import AddCommand
from .commands.apply import ApplyCommand
from .commands.branch import BranchCommand
from .commands.clean_rebase import CleanRebaseCommand
from .commands.commit import CommitCommand
from .commands.diff import DiffCommand
from .commands.init import InitCommand
from .commands.merge import MergeCommand
from .commands.pull import PullCommand
from .commands.push import PushCommand
from .commands.status import StatusCommand
from .config import load_config


class IshprojectCLI(BaseCLI):
    """ishproject CLI."""

    PROG = "ishproject"
    DESCRIPTION = "Apply project-scoped ishfiles dotfiles."
    COMMANDS = (
        AddCommand,
        ApplyCommand,
        BranchCommand,
        CleanRebaseCommand,
        CommitCommand,
        DiffCommand,
        InitCommand,
        MergeCommand,
        PullCommand,
        PushCommand,
        StatusCommand,
    )
    # The passthrough commands (add/apply/diff) delegate flag handling to
    # ishfiles, so unknown tokens must be forwarded through ``args.rest``
    # rather than rejected by the top-level parser.
    COLLECT_UNKNOWN = True

    def resolve_config(self, args: argparse.Namespace) -> argparse.Namespace:
        args.ishproject_cfg = load_config()
        return args


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argument parser."""
    return IshprojectCLI().build_parser()


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    return IshprojectCLI().main(argv)
