#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Ignore-list handling for dotfile management.

Provides the :class:`DotfileIgnore` class that encapsulates the full
set of patterns to skip during dotfile discovery.  Used by
:class:`~pyishlib.dotfile_applier.DotfileApplier` and the ``ishfiles``
CLI tool.

Ignore sources (merged by the constructor):

1. **Default patterns** -- VCS directories, build artifacts, etc.
2. **Ignore file** -- a gitignore-style file in the source directory
   (default ``.dotfileignore``, overridable).
3. **Extra patterns** -- caller-supplied globs (e.g. from a config file
   or CLI ``--ignore`` flags).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import List, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Patterns always ignored (VCS dirs, build artifacts, internal files).
DEFAULT_PATTERNS: List[str] = [
    ".git",
    ".github",
    ".gitignore",
    "__pycache__",
    "*.ish",
]

#: Default ignore-file name read from the source directory.
DOTFILEIGNORE: str = ".dotfileignore"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_ignore_file(path: Path) -> List[str]:
    """Load gitignore-style patterns from *path*, skipping blanks and comments."""
    patterns: List[str] = []
    if not path.is_file():
        return patterns
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


# ---------------------------------------------------------------------------
# DotfileIgnore
# ---------------------------------------------------------------------------


class DotfileIgnore:
    """Encapsulates the complete set of ignore rules for dotfile discovery.

    All rules are stored as fnmatch-style patterns.  Exact names (e.g.
    ``.git``) are simply patterns without wildcards — :func:`fnmatch.fnmatch`
    matches them as literal strings.

    Args:
        source_dir:      Root of the dotfile/ishfiles folder.
        ignore_file:     Name of the ignore file to load from *source_dir*
                         (default ``.dotfileignore``).
        extra_patterns:  Additional fnmatch-style patterns (merged with
                         :data:`DEFAULT_PATTERNS` and the ignore file).
    """

    def __init__(
        self,
        source_dir: Path,
        ignore_file: str = DOTFILEIGNORE,
        extra_patterns: Sequence[str] = (),
    ) -> None:
        self._patterns: List[str] = list(DEFAULT_PATTERNS)
        self._patterns.extend(load_ignore_file(source_dir / ignore_file))
        self._patterns.extend(extra_patterns)

    @property
    def patterns(self) -> List[str]:
        """A copy of the full list of ignore patterns."""
        return list(self._patterns)

    def is_ignored(self, name: str) -> bool:
        """Return *True* if *name* should be skipped during discovery."""
        return any(fnmatch.fnmatch(name, pat) for pat in self._patterns)
