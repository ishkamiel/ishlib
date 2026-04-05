#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Single dotfile representation and path-translation helpers.

Provides the :class:`DotFile` value object that tracks a managed dotfile
through the discover / prepare / apply pipeline, along with chezmoi-style
``dot_`` name translation and ignore-file loading utilities.
"""

from __future__ import annotations

import filecmp
import fnmatch
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence

DOT_PREFIX = "dot_"

DEFAULT_IGNORE = frozenset({".git", ".github", ".gitignore", "__pycache__"})

DOTFILEIGNORE = ".dotfileignore"


# ---------------------------------------------------------------------------
# Name translation
# ---------------------------------------------------------------------------


class ChangeType(Enum):
    """Type of change to apply."""

    NEW = "new"
    MODIFIED = "modified"


def translate_name(name: str) -> str:
    """Translate a single path component from dotfile repo naming.

    Converts the ``dot_`` prefix to a literal ``.`` prefix.
    """
    if name.startswith(DOT_PREFIX):
        return "." + name[len(DOT_PREFIX) :]
    return name


def translate_path(rel_path: Path) -> Path:
    """Translate all components of a relative path.

    Each component is passed through :func:`translate_name`.
    """
    parts = [translate_name(part) for part in rel_path.parts]
    return Path(*parts) if parts else rel_path


# ---------------------------------------------------------------------------
# Ignore handling
# ---------------------------------------------------------------------------


def load_ignore_file(path: Path) -> List[str]:
    """Load gitignore-style patterns from *path*, skipping blanks/comments."""
    patterns: List[str] = []
    if not path.is_file():
        return patterns
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def is_ignored(
    name: str,
    ignore_set: frozenset,
    ignore_patterns: Sequence[str],
) -> bool:
    """Return True if *name* should be ignored."""
    if name in ignore_set:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in ignore_patterns)


# ---------------------------------------------------------------------------
# DotFile
# ---------------------------------------------------------------------------


class DotFile:
    """Represents a single dotfile managed by the applier.

    A *DotFile* knows its source path inside the repository, the
    translated relative path (with ``dot_`` resolved), and the
    absolute target path where it should be installed.  It also
    tracks an optional *staged* path used during the prepare step.

    Args:
        source: Absolute path to the file in the source repo.
        rel_path: Path of the file relative to the source root
                  (before translation).
        target_dir: The root target directory (e.g. ``$HOME``).
    """

    def __init__(self, source: Path, rel_path: Path, target_dir: Path) -> None:
        self._source: Path = source
        self._rel_path: Path = rel_path
        self._target_dir: Path = target_dir
        self._translated: Path = translate_path(rel_path)
        self._staged: Optional[Path] = None

    @property
    def source(self) -> Path:
        """Absolute path to the file in the source repository."""
        return self._source

    @property
    def rel_path(self) -> Path:
        """Relative path inside the source repository (untranslated)."""
        return self._rel_path

    @property
    def translated(self) -> Path:
        """Relative path after ``dot_`` translation."""
        return self._translated

    @property
    def target(self) -> Path:
        """Absolute path where the file should be installed."""
        return self._target_dir / self._translated

    @property
    def staged(self) -> Optional[Path]:
        """Absolute path to the staged (preprocessed) copy, if any."""
        return self._staged

    @staged.setter
    def staged(self, path: Optional[Path]) -> None:
        self._staged = path

    @property
    def effective_source(self) -> Path:
        """The file to compare / copy: staged copy if available, else source."""
        return self._staged if self._staged is not None else self._source

    def get_change_type(self) -> Optional[ChangeType]:
        """Compare the effective source against the target.

        Returns:
            :attr:`ChangeType.NEW` if the target does not exist,
            :attr:`ChangeType.MODIFIED` if it differs, or *None* if
            the files are identical.
        """
        if not self.target.exists():
            return ChangeType.NEW
        if not self.target.is_file():
            return ChangeType.MODIFIED
        if not filecmp.cmp(self.effective_source, self.target, shallow=False):
            return ChangeType.MODIFIED
        return None

    def __repr__(self) -> str:
        return (
            f"DotFile(source={self._source}, "
            f"translated={self._translated}, "
            f"target={self.target})"
        )
