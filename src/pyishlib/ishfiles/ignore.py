#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Ishfiles-specific ignore rules.

Extends the generic :class:`~pyishlib.dotfile_ignore.DotfileIgnore` with
ishfiles-specific defaults: the ``.ishignore`` file, reserved directories
(``ishconfig``, ``ishscripts``), and any user-configured patterns from
the TOML config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..dotfile_ignore import DotfileIgnore

#: Ignore-file name used by the ishfiles tool.
ISHIGNORE_FILE: str = ".ishignore"

#: Patterns specific to the ishfiles tool (reserved dirs + ignore file).
ISHFILES_PATTERNS: list = [
    "ishconfig",
    "ishscripts",
    ISHIGNORE_FILE,
]


def build_ignore(
    source_dir: Path,
    extra_patterns: Sequence[str] = (),
) -> DotfileIgnore:
    """Build a :class:`DotfileIgnore` with ishfiles defaults.

    Combines the generic defaults with ishfiles-specific patterns
    (reserved directories, ``.ishignore`` file) and any extra patterns
    from the user's config.

    Args:
        source_dir:     Root of the ishfiles source folder.
        extra_patterns: Additional patterns (e.g. from config file).
    """
    patterns = list(ISHFILES_PATTERNS) + list(extra_patterns)
    return DotfileIgnore(
        source_dir=source_dir,
        ignore_file=ISHIGNORE_FILE,
        extra_patterns=patterns,
    )
