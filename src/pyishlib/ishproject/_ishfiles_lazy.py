# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Lazy bridges into the ``ishfiles`` CLI.

Importing ``pyishlib.ishfiles.cli`` pulls in the whole installer and
dotfile stack, which is by far the most expensive part of starting
``ishproject``.  The passthrough subcommands only need it when they
actually run, so each command module imports these thin wrappers
instead.  They stay module-level callables (not function-local
imports) so tests can keep patching e.g.
``pyishlib.ishproject.commands.apply.ishfiles_main``.
"""

from __future__ import annotations

import argparse
from typing import List


def ishfiles_main(argv: List[str]) -> int:
    """Run ``ishfiles`` with *argv*; imports the ishfiles CLI on first use."""
    from ..ishfiles.cli import main

    return main(argv)


def ishfiles_build_parser() -> argparse.ArgumentParser:
    """Return the ishfiles top-level parser; imports the CLI on first use."""
    from ..ishfiles.cli import build_parser

    return build_parser()
