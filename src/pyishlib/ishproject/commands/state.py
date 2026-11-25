# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject state`` -- compact dirty-count token for shell prompts.

Prints a single line like ``±3`` when the active ishproject worktree
has uncommitted changes, and nothing when it is clean or absent. With
``-R`` the count aggregates initialised submodules' ishproject worktrees
into the same total so prompts stay one line. No network is touched and
stdin is never read, so the command is safe to invoke on every prompt
render.

The work is done by :mod:`pyishlib.ishproject.state_fast`, which is also
what the launcher runs directly (without importing ``pyishlib``) for the
fastest possible prompt path.
"""

from __future__ import annotations

import argparse
import logging
import os

from ...cli_command import CliCommand
from ..config import IshprojectConfig
from ..state_fast import count_dirty, format_token

log = logging.getLogger(__name__)


class StateCommand(CliCommand):
    """Print a compact ishproject worktree dirty-count for shell prompts."""

    NAME = "state"
    HELP = "Print a compact ishproject state token (for shell prompts)"
    DESCRIPTION = (
        "Prints `±N` when the active ishproject worktree has N "
        "uncommitted changes, and nothing when it is clean, absent, or "
        "cwd is not a git repo. With -R the dirty counts of every "
        "initialised submodule with an ishproject worktree are folded "
        "into the same total. Designed to run on every prompt render: "
        "no network, no stdin, exits 0 on every well-formed invocation."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-R",
            "--recurse-submodules",
            action="store_true",
            default=False,
            help=(
                "Fold the dirty count of every initialised submodule "
                "with an ishproject worktree into the parent total."
            ),
        )

    def run(self) -> int:
        cfg: IshprojectConfig = self.cfg.ishproject_cfg
        total = count_dirty(
            os.getcwd(),
            recurse=bool(getattr(self.cfg, "recurse_submodules", False)),
            prefix=cfg.prefix,
            postfix=cfg.postfix,
        )
        token = format_token(total)
        if token:
            print(token)
        return 0
