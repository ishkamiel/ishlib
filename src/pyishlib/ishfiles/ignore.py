#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Ignore-list construction for ishfiles.

Merges three sources of ignore rules:

1. **Hardcoded** -- directories reserved for future ishfiles features
   (``ishconfig``, ``ishscripts``), plus common VCS / build artifacts.
2. **Dotfile-local** -- a ``.ishignore`` file inside the ishfiles folder.
3. **Config file** -- the ``[ignore] patterns`` list in ``config.toml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from ..dotfile import load_ignore_file

ISHIGNORE_FILE = ".ishignore"

# Directories reserved for future ishfiles features.
HARDCODED_IGNORE_DIRS: frozenset = frozenset({"ishconfig", "ishscripts"})

# Exact names that are always ignored (VCS, build artifacts, etc.).
HARDCODED_IGNORE_NAMES: frozenset = frozenset(
    {".git", ".github", ".gitignore", "__pycache__"}
)

# All hardcoded exact-match ignores combined.
HARDCODED_IGNORE: frozenset = HARDCODED_IGNORE_DIRS | HARDCODED_IGNORE_NAMES

# Glob patterns that are always ignored.
HARDCODED_IGNORE_PATTERNS: List[str] = ["*.ish"]


def build_ignore_set(
    source_dir: Path,
    extra_patterns: Sequence[str] = (),
) -> tuple:
    """Build the complete ignore set and pattern list.

    Args:
        source_dir:      Root of the ishfiles folder (for ``.ishignore``).
        extra_patterns:  Additional patterns from the config file.

    Returns:
        A ``(names, patterns)`` tuple where *names* is a :class:`frozenset`
        of exact directory/file names to skip and *patterns* is a list of
        fnmatch-style glob patterns.
    """
    ignore_names = HARDCODED_IGNORE

    patterns: List[str] = list(HARDCODED_IGNORE_PATTERNS)
    patterns.extend(load_ignore_file(source_dir / ISHIGNORE_FILE))
    patterns.extend(extra_patterns)

    return ignore_names, patterns
