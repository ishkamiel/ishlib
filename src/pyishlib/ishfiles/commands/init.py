#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``init`` subcommand -- print shell integration code.

Add the following line to your shell rc file to enable shell integration::

    eval "$(ishfiles init)"          # POSIX wrapper only (safe for dash/ash)
    eval "$(ishfiles init --bash)"   # wrapper + bash completions (needs shtab)
    eval "$(ishfiles init --zsh)"    # wrapper + zsh completions (needs shtab)

After this, ``ishfiles cd`` will change the current working directory of
the interactive shell rather than spawning a subshell.  With ``--bash``
or ``--zsh``, tab-completion for both ``ishfiles`` and ``isholate`` is
also registered -- provided the optional `shtab`_ package is installed.
Run ``ishfiles doctor`` to see which optional packages are available.

.. note::
    For zsh, ``autoload -U compinit && compinit`` must have been run
    before the ``eval`` line so that ``compdef`` is available.

.. _shtab: https://pypi.org/project/shtab/
"""

from __future__ import annotations

import argparse
import logging

from ... import completions
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


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``init`` subcommand."""
    parser = subparsers.add_parser(
        "init",
        help="Print shell integration code (eval in your shell rc)",
        description=(
            "Print shell integration code for ishfiles.  "
            'Add `eval "$(ishfiles init --zsh)"` (or --bash) to your '
            "~/.zshrc / ~/.bashrc to make `ishfiles cd` perform a real "
            "directory change and to enable tab-completion for both "
            "ishfiles and isholate (completion requires the optional "
            "`shtab` package -- see `ishfiles doctor`)."
        ),
    )
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
    parser.set_defaults(func=run, shell=None)


def run(cfg: IshConfig) -> int:
    """Print shell integration code to stdout.

    The POSIX ``ishfiles()`` wrapper is always emitted.  When ``--bash``
    or ``--zsh`` is passed, shell-specific completion scripts for both
    ``ishfiles`` and ``isholate`` are appended -- provided the optional
    ``shtab`` package is installed.  When it is missing, only the POSIX
    wrapper is emitted and a warning is logged pointing at
    ``ishfiles doctor``.

    Returns:
        Always 0.
    """
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

    print(completions.generate("ishfiles", shell), end="")
    print(completions.generate("isholate", shell), end="")
    return 0
