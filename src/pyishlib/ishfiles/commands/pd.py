# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``pd`` subcommand -- print the dotfiles source directory."""

from __future__ import annotations

import sys

from ...cli_command import CliCommand
from ..applier import make_finder


class PdCommand(CliCommand):
    """Print the dotfiles source directory."""

    NAME = "pd"
    HELP = "Print the dotfiles source directory"
    DESCRIPTION = (
        "Print the resolved ishfiles source directory to stdout.  "
        "Used by the shell wrapper from `ishfiles init` to resolve "
        "the path before cd-ing into it."
    )

    def run(self) -> int:
        finder = make_finder(self.cfg)
        source_dir = finder.source_dir

        print(source_dir)

        if not source_dir.is_dir():
            print(
                f"ishfiles pd: warning: source directory does not exist: {source_dir}",
                file=sys.stderr,
            )
        return 0
