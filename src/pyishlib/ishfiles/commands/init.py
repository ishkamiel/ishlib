#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``init`` subcommand -- print shell integration code.

Add the following line to your shell rc file to enable shell integration::

    eval "$(ishfiles init)"          # POSIX / bash / zsh
    eval "$(ishfiles init --zsh)"    # same output, explicit flag
    eval "$(ishfiles init --bash)"   # same output, explicit flag

After this, ``ishfiles cd`` will change the current working directory of
the interactive shell rather than spawning a subshell.
"""

from __future__ import annotations

import argparse

from ...ish_config import IshConfig

_POSIX_SNIPPET = """\
ishfiles() {
    if [ "$1" = "cd" ]; then
        cd -- "$(command ishfiles pd)" || return
    else
        command ishfiles "$@"
    fi
}
"""


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``init`` subcommand."""
    parser = subparsers.add_parser(
        "init",
        help="Print shell integration code (eval in your shell rc)",
        description=(
            "Print POSIX shell integration code for ishfiles.  "
            'Add `eval "$(ishfiles init)"` to your ~/.bashrc or ~/.zshrc '
            "to make `ishfiles cd` perform a real directory change."
        ),
    )
    shell_group = parser.add_mutually_exclusive_group()
    shell_group.add_argument(
        "--sh",
        action="store_const",
        dest="shell",
        const="sh",
        help="Emit POSIX sh snippet (default)",
    )
    shell_group.add_argument(
        "--bash",
        action="store_const",
        dest="shell",
        const="bash",
        help="Emit bash snippet (same as POSIX for now)",
    )
    shell_group.add_argument(
        "--zsh",
        action="store_const",
        dest="shell",
        const="zsh",
        help="Emit zsh snippet (same as POSIX for now)",
    )
    parser.set_defaults(func=run, shell=None)


def run(cfg: IshConfig) -> int:  # noqa: ARG001
    """Print shell integration code to stdout.

    All supported shell flavours (sh, bash, zsh) emit the same POSIX
    snippet.  The ``--bash`` / ``--zsh`` flags are provided as
    ergonomic hints and for future per-shell specialisation.

    Returns:
        Always 0.
    """
    print(_POSIX_SNIPPET, end="")
    return 0
