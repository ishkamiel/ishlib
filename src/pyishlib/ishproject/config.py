# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Constants and small helpers specific to ishproject."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from ..ishlib_folder import IshlibFolder

ISHPROJECT_BRANCH = "ish/ishproject"


def resolve_project_paths(root: Path) -> Tuple[Path, Path]:
    """Return ``(source, target)`` for ishproject at *root*.

    ``source`` is ``<root>/.ishlib/ishproject`` (the worktree managed by
    ``ishproject init``); ``target`` is the project root itself.
    """
    folder = IshlibFolder(root)
    return folder.ishproject_dir, folder.root
