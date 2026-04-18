# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``init`` subcommand -- print shell integration code."""

from __future__ import annotations

import argparse
import logging

from ... import completions, tools
from ...cli_command import CliCommand
from ...ish_config import IshConfig

log = logging.getLogger(__name__)

_POSIX_SNIPPET = """\
ishfiles() {
    if [ "$1" = "cd" ]; then
        cd "$(command ishfiles pd)" || return
    else
        command ishfiles "$@"
    fi
}
"""


class InitCommand(CliCommand):
    """Print shell integration code (eval in your shell rc)."""

    NAME = "init"
    HELP = "Print shell integration code (eval in your shell rc)"
    DESCRIPTION = (
        "Print shell integration code for ishfiles.  "
        'Add `eval "$(ishfiles init --zsh)"` (or --bash) to your '
        "~/.zshrc / ~/.bashrc to make `ishfiles cd` perform a real "
        "directory change and to enable tab-completion for both "
        "ishfiles and isholate (completion requires the optional "
        "`shtab` package -- see `ishfiles doctor`)."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        shell_group = parser.add_mutually_exclusive_group()
        shell_group.add_argument(
            "--sh",
            action="store_const",
            dest="shell",
            const="sh",
            help="Emit POSIX sh wrapper only (default, safe for dash/ash)",
        )
        shell_group.add_argument(
            "--bash",
            action="store_const",
            dest="shell",
            const="bash",
            help="Emit POSIX wrapper plus bash completions (needs `shtab`)",
        )
        shell_group.add_argument(
            "--zsh",
            action="store_const",
            dest="shell",
            const="zsh",
            help="Emit POSIX wrapper plus zsh completions (needs `shtab`)",
        )
        parser.set_defaults(shell=None)

    def run(self, cfg: IshConfig) -> int:
        shell = cfg.get_opt("shell", None)

        print(_POSIX_SNIPPET, end="")

        if shell not in ("bash", "zsh"):
            return 0

        if not completions.HAS_SHTAB:
            log.warning(
                "%s tab-completion requires the optional `shtab` package "
                "(install with `pip install shtab`; run `ishfiles doctor` "
                "for a full list of optional packages). "
                "Emitting the POSIX wrapper only.",
                shell,
            )
            return 0

        for tool in tools.all_tools():
            print(completions.generate(tool.name, shell), end="")
        return 0
