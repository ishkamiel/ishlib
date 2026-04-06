#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Common applier setup for ishfiles commands.

Provides :func:`make_applier` which builds a :class:`DotfileApplier`
from an :class:`IshConfig`, wiring up ishfiles-specific ignore rules.
"""

from __future__ import annotations

from pathlib import Path

from ..dotfile_applier import DotfileApplier
from ..ish_config import IshConfig
from .ignore import build_ignore


def make_applier(cfg: IshConfig) -> DotfileApplier:
    """Build a :class:`DotfileApplier` configured for ishfiles.

    Reads ``source``, ``target``, and ``patterns`` from *cfg* and
    constructs the appropriate :class:`DotfileIgnore` with ishfiles
    defaults.

    Args:
        cfg: Resolved ishfiles configuration.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser()
    target_dir = Path(cfg.get_opt("target")).expanduser()

    di = build_ignore(
        source_dir=source_dir,
        extra_patterns=cfg.get_opt("patterns", []),
    )

    return DotfileApplier(
        source_dir=source_dir,
        target_dir=target_dir,
        cfg=cfg,
        dotfile_ignore=di,
    )
