# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Central registry of all ishlib CLI tools.

Add one entry to ``TOOLS`` to register a new tool. Completions,
launcher generation, ``ishfiles init``, and ``IshlibFolder`` all
consume this registry automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Tool:
    name: str
    module: str
    description: str
    subdir: str


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
