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

from . import tools as _tools

PROJECT_DIR_NAME = ".ishlib"


class IshlibFolder:
    """Wrapper around a project's ``.ishlib/`` umbrella directory.

    Provides path accessors and ``discover_tool`` helpers for each tool
    that stores per-project state under ``.ishlib/``. All paths are
    resolved against the project root passed to the constructor; no
    parent search is performed.
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

    def tool_dir(self, name: str) -> Path:
        """Absolute path of ``.ishlib/<subdir>/`` for the named tool (may not exist).

        Args:
            name: Tool name as registered in :mod:`pyishlib.tools`.

        Raises:
            ValueError: If *name* is not a registered tool.
        """
        return self.path / _tools.get(name).subdir

    def discover_tool(self, name: str) -> Optional[Path]:
        """Return ``.ishlib/<subdir>/`` for *name* if it exists, else ``None``.

        Args:
            name: Tool name as registered in :mod:`pyishlib.tools`.

        Raises:
            ValueError: If *name* is not a registered tool.
        """
        d = self.tool_dir(name)
        return d if d.is_dir() else None
