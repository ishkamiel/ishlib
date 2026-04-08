#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Single dotfile representation and path-translation helpers.

Provides the :class:`DotFile` value object that tracks a managed dotfile
through the discover / prepare / apply pipeline, along with chezmoi-style
``dot_`` name translation.

Ignore-list constants and utilities live in :mod:`dotfile_ignore`.
"""

from __future__ import annotations

import filecmp
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

DOT_PREFIX = "dot_"


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


def reverse_translate_name(name: str) -> str:
    """Reverse-translate a single path component to dotfile repo naming.

    Converts a leading ``.`` to the ``dot_`` prefix.
    """
    if name.startswith(".") and name not in {".", ".."} and len(name) > 1:
        return DOT_PREFIX + name[1:]
    return name


def reverse_translate_path(rel_path: Path) -> Path:
    """Reverse-translate all components of a relative path.

    Each component is passed through :func:`reverse_translate_name`.
    """
    parts = [reverse_translate_name(part) for part in rel_path.parts]
    return Path(*parts) if parts else rel_path


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
        self._metadata: Optional[Dict[str, Any]] = None
        self._scanned: bool = False

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
    def metadata(self) -> Optional[Dict[str, Any]]:
        """Extracted __ISH__ metadata, populated during preprocessing."""
        return self._metadata

    @metadata.setter
    def metadata(self, value: Optional[Dict[str, Any]]) -> None:
        self._metadata = value
        self._scanned = True

    @property
    def scanned(self) -> bool:
        """True if metadata has been read (even if no metadata was found)."""
        return self._scanned

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
