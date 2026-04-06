#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Ignore-list handling for dotfile management.

Provides the :class:`DotfileIgnore` class that encapsulates the full
set of names and patterns to skip during dotfile discovery.  Used by
:class:`~pyishlib.dotfile_applier.DotfileApplier` and the ``ishfiles``
CLI tool.

Ignore sources (merged by the constructor):

1. **Hardcoded names** -- VCS directories, build artifacts, and
   (for ishfiles) reserved directories like ``ishconfig`` / ``ishscripts``.
2. **Hardcoded patterns** -- fnmatch globs always skipped (e.g. ``*.ish``).
3. **Ignore file** -- a gitignore-style file in the source directory
   (default ``.dotfileignore``, overridable).
4. **Extra patterns** -- caller-supplied globs (e.g. from a config file
   or CLI ``--ignore`` flags).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import List, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Exact names always ignored (VCS, build artifacts).
DEFAULT_IGNORE: frozenset = frozenset({".git", ".github", ".gitignore", "__pycache__"})

#: Glob patterns always ignored.
DEFAULT_IGNORE_PATTERNS: List[str] = ["*.ish"]

#: Default ignore-file name read from the source directory.
DOTFILEIGNORE: str = ".dotfileignore"

#: Ignore-file name used by the ishfiles tool.
ISHIGNORE_FILE: str = ".ishignore"

#: Directories reserved for future ishfiles features.
ISHFILES_IGNORE_DIRS: frozenset = frozenset({"ishconfig", "ishscripts"})

#: Full ignore set for the ishfiles tool (default + reserved dirs + ignore file).
ISHFILES_IGNORE: frozenset = (
    DEFAULT_IGNORE | ISHFILES_IGNORE_DIRS | frozenset({ISHIGNORE_FILE})
)

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

    Merges hardcoded defaults, an ignore file from the source directory,
    and any caller-supplied extras into a single object whose
    :meth:`is_ignored` method can be called during directory traversal.

    Args:
        source_dir:      Root of the dotfile/ishfiles folder.
        ignore_file:     Name of the ignore file to load from *source_dir*
                         (default ``.dotfileignore``).
        extra_names:     Additional exact names to ignore (merged with
                         :data:`DEFAULT_IGNORE`).
        extra_patterns:  Additional fnmatch-style patterns (merged with
                         :data:`DEFAULT_IGNORE_PATTERNS` and the ignore file).
    """

    def __init__(
        self,
        source_dir: Path,
        ignore_file: str = DOTFILEIGNORE,
        extra_names: frozenset = frozenset(),
        extra_patterns: Sequence[str] = (),
    ) -> None:
        self._names: frozenset = DEFAULT_IGNORE | extra_names

        self._patterns: List[str] = list(DEFAULT_IGNORE_PATTERNS)
        self._patterns.extend(load_ignore_file(source_dir / ignore_file))
        self._patterns.extend(extra_patterns)

    @property
    def names(self) -> frozenset:
        """The set of exact names that are ignored."""
        return self._names

    @property
    def patterns(self) -> List[str]:
        """The list of fnmatch-style patterns that are ignored."""
        return list(self._patterns)

    def is_ignored(self, name: str) -> bool:
        """Return *True* if *name* should be skipped during discovery."""
        if name in self._names:
            return True
        return any(fnmatch.fnmatch(name, pat) for pat in self._patterns)
