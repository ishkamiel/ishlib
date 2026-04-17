# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Single dotfile representation and path-translation helpers.

Provides the :class:`DotFile` value object that tracks a managed dotfile
through the discover / prepare / apply pipeline, along with chezmoi-style
``dot_`` and ``executable_`` name translation.

Ignore-list constants and utilities live in :mod:`dotfile_ignore`.
"""

from __future__ import annotations

import filecmp
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from .environment import is_windows
from .json_merge import semantic_equal

DOT_PREFIX = "dot_"
EXECUTABLE_PREFIX = "executable_"
MERGEJSON_PREFIX = "mergejson_"


# ---------------------------------------------------------------------------
# Name translation
# ---------------------------------------------------------------------------


class ChangeType(Enum):
    """Type of change to apply."""

    NEW = "new"
    MODIFIED = "modified"


def is_executable_name(name: str) -> bool:
    """Return *True* if *name* carries the ``executable_`` prefix."""
    return name.startswith(EXECUTABLE_PREFIX)


def is_mergejson_name(name: str) -> bool:
    """Return *True* if *name* carries the ``mergejson_`` prefix.

    The check tolerates a leading ``executable_`` prefix so that
    ``executable_mergejson_foo.json`` is still detected as a mergejson
    file.
    """
    if name.startswith(EXECUTABLE_PREFIX):
        name = name[len(EXECUTABLE_PREFIX) :]
    return name.startswith(MERGEJSON_PREFIX)


def translate_name(name: str) -> str:
    """Translate a single path component from dotfile repo naming.

    Strips prefixes in the order ``executable_`` → ``mergejson_`` →
    ``dot_``, then converts a remaining ``dot_`` prefix to a literal
    ``.`` prefix.  Examples:

    - ``executable_dot_foo`` → ``.foo``
    - ``mergejson_settings.json`` → ``settings.json``
    - ``mergejson_dot_settings.json`` → ``.settings.json``
    - ``executable_mergejson_dot_foo.json`` → ``.foo.json``
    """
    if name.startswith(EXECUTABLE_PREFIX):
        name = name[len(EXECUTABLE_PREFIX) :]
    if name.startswith(MERGEJSON_PREFIX):
        name = name[len(MERGEJSON_PREFIX) :]
    if name.startswith(DOT_PREFIX):
        return "." + name[len(DOT_PREFIX) :]
    return name


def translate_path(rel_path: Path) -> Path:
    """Translate all components of a relative path.

    Each component is passed through :func:`translate_name`.
    """
    parts = [translate_name(part) for part in rel_path.parts]
    return Path(*parts) if parts else rel_path


def reverse_translate_name(
    name: str, executable: bool = False, mergejson: bool = False
) -> str:
    """Reverse-translate a single path component to dotfile repo naming.

    Converts a leading ``.`` to the ``dot_`` prefix and prepends
    ``mergejson_`` when *mergejson* is ``True`` and ``executable_`` when
    *executable* is ``True`` (outermost).  This is the symmetric
    counterpart of :func:`translate_name`.
    """
    if name.startswith(".") and name not in {".", ".."} and len(name) > 1:
        name = DOT_PREFIX + name[1:]
    if mergejson:
        name = MERGEJSON_PREFIX + name
    if executable:
        name = EXECUTABLE_PREFIX + name
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
    def executable(self) -> bool:
        """True if the source filename carries the ``executable_`` prefix.

        When *True*, the applied file must be made executable (``chmod +x``).
        """
        return is_executable_name(self._rel_path.name)

    @property
    def mergejson(self) -> bool:
        """True if the source filename carries the ``mergejson_`` prefix.

        When *True*, the file is treated as an RFC 7396 JSON Merge Patch
        that combines with any existing target rather than replacing it.
        """
        return is_mergejson_name(self._rel_path.name)

    @property
    def effective_source(self) -> Path:
        """The file to compare / copy: staged copy if available, else source."""
        return self._staged if self._staged is not None else self._source

    def get_change_type(self) -> Optional[ChangeType]:
        """Compare the effective source against the target.

        Returns:
            :attr:`ChangeType.NEW` if the target does not exist,
            :attr:`ChangeType.MODIFIED` if content differs or if the
            target is missing its executable bit when the source carries
            the ``executable_`` prefix, or *None* if everything matches.

        For ``mergejson_`` files the comparison is performed by parsing
        both sides as JSON and comparing semantically, so key ordering
        inside objects does not count as a change.
        """
        if not self.target.exists():
            return ChangeType.NEW
        if not self.target.is_file():
            return ChangeType.MODIFIED
        if self.mergejson:
            if not semantic_equal(self.effective_source, self.target):
                return ChangeType.MODIFIED
        elif not filecmp.cmp(self.effective_source, self.target, shallow=False):
            return ChangeType.MODIFIED
        # exec bits are meaningless on Windows; skip the check there
        if self.executable and not is_windows() and not os.access(self.target, os.X_OK):
            return ChangeType.MODIFIED
        return None

    def __repr__(self) -> str:
        return (
            f"DotFile(source={self._source}, "
            f"translated={self._translated}, "
            f"target={self.target})"
        )
