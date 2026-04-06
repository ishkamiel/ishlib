#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""File scanner for ishfiles.

Walks the ishfiles source directory and builds a list of
:class:`~pyishlib.dotfile.DotFile` objects, respecting the merged
ignore rules from :mod:`~pyishlib.ishfiles.ignore`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Sequence

from ..dotfile import DotFile, is_ignored
from .ignore import build_ignore_set

log = logging.getLogger(__name__)


class IshfilesScanner:
    """Scan an ishfiles source directory for managed dotfiles.

    Args:
        source_dir:      Root of the ishfiles folder.
        target_dir:      Installation target (typically ``$HOME``).
        extra_patterns:  Additional ignore patterns (e.g. from config).
    """

    def __init__(
        self,
        source_dir: Path,
        target_dir: Path,
        extra_patterns: Sequence[str] = (),
    ) -> None:
        self._source_dir = source_dir
        self._target_dir = target_dir
        self._ignore_names, self._ignore_patterns = build_ignore_set(
            source_dir, extra_patterns
        )

    @property
    def source_dir(self) -> Path:
        """The ishfiles source directory."""
        return self._source_dir

    @property
    def target_dir(self) -> Path:
        """The target directory."""
        return self._target_dir

    def scan(self) -> List[DotFile]:
        """Recursively scan the source directory for dotfiles.

        Returns:
            Sorted list of :class:`DotFile` objects.
        """
        if not self._source_dir.is_dir():
            log.warning("Source directory does not exist: %s", self._source_dir)
            return []

        dotfiles: List[DotFile] = []
        self._scan_dir(self._source_dir, Path(), dotfiles)
        dotfiles.sort(key=lambda df: df.translated)
        return dotfiles

    def _scan_dir(
        self,
        current: Path,
        rel_prefix: Path,
        dotfiles: List[DotFile],
    ) -> None:
        """Recursively collect files, skipping ignored entries."""
        for entry in sorted(current.iterdir()):
            if is_ignored(entry.name, self._ignore_names, self._ignore_patterns):
                log.debug("Ignoring %s", entry)
                continue

            rel = rel_prefix / entry.name if rel_prefix != Path() else Path(entry.name)

            if entry.is_dir():
                self._scan_dir(entry, rel, dotfiles)
            elif entry.is_file():
                dotfiles.append(DotFile(entry, rel, self._target_dir))
