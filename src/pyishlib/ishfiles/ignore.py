# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Ishfiles-specific ignore rules.

Extends the generic :class:`~pyishlib.dotfile_ignore.DotfileIgnore` with
ishfiles-specific defaults: the ``.ishignore`` file, reserved directories
(``ishconfig``, ``ishscripts``, ``ishinstallers``), and any user-configured
patterns from the TOML config.

Reserved directory names and the ignore file name are read from the
:class:`~pyishlib.ish_config.IshConfig` constants set up by
:func:`~pyishlib.ishfiles.config.load_config`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..dotfile_ignore import DotfileIgnore
from ..ish_config import IshConfig


def build_ignore(
    cfg: IshConfig,
    source_dir: Path,
    extra_patterns: Sequence[str] = (),
) -> DotfileIgnore:
    """Build a :class:`DotfileIgnore` with ishfiles defaults.

    Combines the generic defaults with ishfiles-specific patterns
    (reserved directories, ignore file) and any extra patterns
    from the user's config.

    Reserved directory names and the ignore file name are read from
    *cfg* constants (``config_dir``, ``scripts_dir``,
    ``installers_dir``, ``ignore_file``).

    Args:
        cfg:            Resolved ishfiles configuration.
        source_dir:     Root of the ishfiles source folder.
        extra_patterns: Additional patterns (e.g. from config file).
    """
    ignore_file = cfg.get_opt("ignore_file")
    reserved_dirs = [
        cfg.get_opt("config_dir"),
        cfg.get_opt("scripts_dir"),
        cfg.get_opt("installers_dir"),
    ]
    patterns = reserved_dirs + [ignore_file] + list(extra_patterns)
    return DotfileIgnore(
        source_dir=source_dir,
        ignore_file=ignore_file,
        extra_patterns=patterns,
    )
