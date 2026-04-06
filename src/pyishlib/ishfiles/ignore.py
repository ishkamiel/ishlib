#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Ignore-list construction for ishfiles.

Extends :data:`~pyishlib.dotfile.DEFAULT_IGNORE` with ishfiles-specific
entries and merges three sources of ignore patterns:

1. **Hardcoded** -- directories reserved for future ishfiles features
   (``ishconfig``, ``ishscripts``).
2. **Dotfile-local** -- a ``.ishignore`` file inside the ishfiles folder.
3. **Config file** -- the ``[ignore] patterns`` list in ``config.toml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple

from ..dotfile import DEFAULT_IGNORE, load_ignore_file

ISHIGNORE_FILE = ".ishignore"

# Directories reserved for future ishfiles features.
HARDCODED_IGNORE_DIRS: frozenset = frozenset({"ishconfig", "ishscripts"})

# Combined with the default dotfile ignores.
ISHFILES_IGNORE: frozenset = (
    DEFAULT_IGNORE | HARDCODED_IGNORE_DIRS | frozenset({ISHIGNORE_FILE})
)


def build_ignore(
    source_dir: Path,
    extra_patterns: Sequence[str] = (),
) -> Tuple[frozenset, List[str]]:
    """Build the complete ignore set and extra pattern list for ishfiles.

    The returned *names* frozenset is passed as ``ignore`` to
    :class:`~pyishlib.dotfile_applier.DotfileApplier`, and the *patterns*
    list as ``ignore_patterns``.

    Args:
        source_dir:      Root of the ishfiles folder (for ``.ishignore``).
        extra_patterns:  Additional patterns from the config file.

    Returns:
        A ``(names, patterns)`` tuple.
    """
    patterns: List[str] = []
    patterns.extend(load_ignore_file(source_dir / ISHIGNORE_FILE))
    patterns.extend(extra_patterns)

    return ISHFILES_IGNORE, patterns
