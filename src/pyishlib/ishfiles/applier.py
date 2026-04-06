#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Common applier setup for ishfiles commands.

Provides :func:`make_applier` which builds a :class:`DotfileApplier`
from an :class:`IshConfig`, wiring up ishfiles-specific ignore rules,
and :func:`make_finder` for a standalone :class:`DotfileFinder`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..dotfile_applier import DotfileApplier
from ..dotfile_finder import DotfileFinder
from ..ish_config import IshConfig
from .ignore import build_ignore


def make_finder(cfg: IshConfig) -> DotfileFinder:
    """Build a :class:`DotfileFinder` configured for ishfiles.

    Args:
        cfg: Resolved ishfiles configuration.
    """
    return DotfileFinder(cfg)


def make_applier(
    cfg: IshConfig,
    finder: Optional[DotfileFinder] = None,
) -> DotfileApplier:
    """Build a :class:`DotfileApplier` configured for ishfiles.

    Reads ``source``, ``target``, and ``patterns`` from *cfg* and
    constructs the appropriate :class:`DotfileIgnore` with ishfiles
    defaults.

    Args:
        cfg: Resolved ishfiles configuration.
        finder: Optional pre-built finder (one is created if *None*).
    """
    if finder is None:
        finder = make_finder(cfg)

    di = build_ignore(
        source_dir=finder.source_dir,
        extra_patterns=cfg.get_opt("patterns", []),
    )

    return DotfileApplier(
        source_dir=finder.source_dir,
        target_dir=finder.target_dir,
        cfg=cfg,
        dotfile_ignore=di,
    )
