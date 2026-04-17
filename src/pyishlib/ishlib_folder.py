# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``.ishlib/`` umbrella directory used by per-project ishlib state.

Multiple ishlib tools (``ishfiles``, ``isholate``, ``ishproject``) keep
project-local state under a single ``.ishlib/`` directory in the project
root, with a tool-specific subdirectory per tool. :class:`IshlibFolder`
owns the path layout so each tool gets a typed accessor for its own
subdirectory and never reaches into another tool's config module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

PROJECT_DIR_NAME = ".ishlib"

ISHFILES_SUBDIR = "ishfiles"
ISHOLATE_SUBDIR = "isholate"
ISHPROJECT_SUBDIR = "ishproject"


class IshlibFolder:
    """Wrapper around a project's ``.ishlib/`` umbrella directory.

    Provides path accessors and ``discover_*`` helpers for each tool that
    stores per-project state under ``.ishlib/``. All paths are resolved
    against the project root passed to the constructor; no parent search
    is performed.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    @classmethod
    def from_cwd(cls) -> "IshlibFolder":
        """Return an :class:`IshlibFolder` rooted at the current working dir."""
        return cls(Path.cwd())

    @property
    def path(self) -> Path:
        """Absolute path of the ``.ishlib/`` directory itself (may not exist)."""
        return self.root / PROJECT_DIR_NAME

    def exists(self) -> bool:
        """True iff the ``.ishlib/`` directory exists."""
        return self.path.is_dir()

    @property
    def ishfiles_dir(self) -> Path:
        """Absolute path of ``.ishlib/ishfiles/`` (may not exist)."""
        return self.path / ISHFILES_SUBDIR

    @property
    def isholate_dir(self) -> Path:
        """Absolute path of ``.ishlib/isholate/`` (may not exist)."""
        return self.path / ISHOLATE_SUBDIR

    @property
    def ishproject_dir(self) -> Path:
        """Absolute path of ``.ishlib/ishproject/`` (may not exist)."""
        return self.path / ISHPROJECT_SUBDIR

    def discover_ishfiles(self) -> Optional[Path]:
        """Return ``.ishlib/ishfiles/`` if it exists, else ``None``."""
        return self.ishfiles_dir if self.ishfiles_dir.is_dir() else None

    def discover_isholate(self) -> Optional[Path]:
        """Return ``.ishlib/isholate/`` if it exists, else ``None``."""
        return self.isholate_dir if self.isholate_dir.is_dir() else None

    def discover_ishproject(self) -> Optional[Path]:
        """Return ``.ishlib/ishproject/`` if it exists, else ``None``."""
        return self.ishproject_dir if self.ishproject_dir.is_dir() else None
