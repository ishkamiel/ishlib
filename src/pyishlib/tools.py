# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Central registry of all ishlib CLI tools.

Add one entry to ``TOOLS`` to register a new tool. Completions,
launcher generation, ``ishfiles init``, and ``IshlibFolder`` all
consume this registry automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class FastPath:
    """A launcher-level shortcut that bypasses the full Python CLI.

    When the launcher's first argument equals *subcommand* and every
    remaining argument is in *flags*, it runs the stdlib-only *script*
    directly (``python3 -S -I``) instead of ``python -m <module>``.  Any
    other argument falls through to the normal CLI, so ``--help`` and
    unknown flags behave as usual.

    Attributes:
        subcommand: First launcher argument that selects the fast path.
        script: Path relative to the ishlib ``src/`` dir.  It must run as a
            bare script: stdlib only, no relative imports.
        flags: Arguments the script understands after the subcommand.
    """

    subcommand: str
    script: str
    flags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Tool:
    name: str
    module: str
    description: str
    subdir: str
    fast_paths: Tuple[FastPath, ...] = ()


TOOLS: List[Tool] = [
    Tool(
        "ishfiles",
        "pyishlib.ishfiles",
        "Manage dotfiles from an ishfiles repository.",
        subdir="ishfiles",
    ),
    Tool(
        "isholate",
        "pyishlib.isholate",
        "Launch isolated Incus containers.",
        subdir="isholate",
    ),
    Tool(
        "ishproject",
        "pyishlib.ishproject",
        "Apply project-scoped ishfiles.",
        subdir="ishproject",
        fast_paths=(
            FastPath(
                "state",
                "pyishlib/ishproject/state_fast.py",
                flags=("-R", "--recurse-submodules"),
            ),
        ),
    ),
]


def all_tools() -> List[Tool]:
    """Return all registered tools."""
    return list(TOOLS)


def get(name: str) -> Tool:
    """Return the tool named *name*, raising ``ValueError`` if unknown."""
    for t in TOOLS:
        if t.name == name:
            return t
    raise ValueError(f"unknown tool {name!r}")


def find(name: str) -> Optional[Tool]:
    """Return the tool named *name*, or ``None`` if unknown."""
    for t in TOOLS:
        if t.name == name:
            return t
    return None
