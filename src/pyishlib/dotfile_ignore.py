#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Ignore-list handling for dotfile management.

Provides the :class:`DotfileIgnore` class that encapsulates the full
set of patterns to skip during dotfile discovery.  Used by
:class:`~pyishlib.dotfile_applier.DotfileApplier` and the ``ishfiles``
CLI tool.

Ignore sources (merged by the constructor):

1. **Default patterns** -- VCS directories, build artifacts, etc.
2. **Ignore file** -- a gitignore-style file in the source directory
   (default ``.dotfileignore``, overridable).
3. **Extra patterns** -- caller-supplied globs (e.g. from a config file
   or CLI ``--ignore`` flags).

OS-conditional sections
-----------------------

Ignore files support ``[only_on.<os>]`` and ``[ignore_on.<os>]``
sections for platform-conditional ignore rules:

- ``[only_on.linux]`` -- patterns listed here apply *only* on Linux;
  on all other platforms they are ignored (i.e. the files are kept).
- ``[ignore_on.windows]`` -- patterns listed here are ignored *on*
  Windows; on other platforms they have no effect.

Recognised OS names: ``linux``, ``macos``, ``windows`` (plus common
aliases like ``mac``, ``darwin``, ``win``).

Lines before the first section header are unconditional (always active).
"""

from __future__ import annotations

import fnmatch
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .command_runner import RECOGNISED_OS, normalise_os, detect_os

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Patterns always ignored (VCS dirs, build artifacts, internal files).
DEFAULT_PATTERNS: List[str] = [
    ".git",
    ".github",
    ".gitignore",
    "__pycache__",
    "*.ish",
]

#: Default ignore-file name read from the source directory.
DOTFILEIGNORE: str = ".dotfileignore"

#: Regex matching section headers: [only_on.linux], [ignore_on.windows], etc.
_RE_SECTION = re.compile(
    r"^\[\s*(only_on|ignore_on)\.(\w+)\s*\]$"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_ignore_file(
    path: Path,
) -> Tuple[List[str], Dict[str, List[str]], Dict[str, List[str]]]:
    """Load patterns from an ignore file, including OS-conditional sections.

    Returns a tuple of:

    - **global_patterns** -- unconditional patterns (lines before any
      section header).
    - **only_on** -- ``{os: [patterns]}`` dict for ``[only_on.<os>]``
      sections.
    - **ignore_on** -- ``{os: [patterns]}`` dict for ``[ignore_on.<os>]``
      sections.

    Blank lines and comment lines (starting with ``#``) are skipped.
    Unrecognised OS names in section headers produce a warning and the
    section is ignored.
    """
    global_patterns: List[str] = []
    only_on: Dict[str, List[str]] = {}
    ignore_on: Dict[str, List[str]] = {}

    if not path.is_file():
        return global_patterns, only_on, ignore_on

    current_section: Optional[str] = None  # None = global
    current_kind: Optional[str] = None  # "only_on" or "ignore_on"
    current_os: Optional[str] = None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for section header
        m = _RE_SECTION.match(stripped)
        if m:
            kind, os_name = m.group(1), m.group(2)
            try:
                canonical = normalise_os(os_name)
            except ValueError:
                log.warning(
                    "Ignoring unrecognised OS in section header: %s", stripped
                )
                current_section = "invalid"
                current_kind = None
                current_os = None
                continue
            current_section = f"{kind}.{canonical}"
            current_kind = kind
            current_os = canonical
            continue

        if current_section == "invalid":
            continue

        if current_section is None:
            global_patterns.append(stripped)
        elif current_kind == "only_on":
            only_on.setdefault(current_os, []).append(stripped)
        elif current_kind == "ignore_on":
            ignore_on.setdefault(current_os, []).append(stripped)

    return global_patterns, only_on, ignore_on


# ---------------------------------------------------------------------------
# DotfileIgnore
# ---------------------------------------------------------------------------


class DotfileIgnore:
    """Encapsulates the complete set of ignore rules for dotfile discovery.

    All rules are stored as fnmatch-style patterns.  Exact names (e.g.
    ``.git``) are simply patterns without wildcards — :func:`fnmatch.fnmatch`
    matches them as literal strings.

    OS-conditional patterns from ``[only_on.<os>]`` and
    ``[ignore_on.<os>]`` sections are evaluated against the current
    platform (or an explicit *current_os* override).

    Args:
        source_dir:      Root of the dotfile/ishfiles folder.
        ignore_file:     Name of the ignore file to load from *source_dir*
                         (default ``.dotfileignore``).
        extra_patterns:  Additional fnmatch-style patterns (merged with
                         :data:`DEFAULT_PATTERNS` and the ignore file).
        current_os:      Override the auto-detected OS (for testing).
                         One of ``"linux"``, ``"macos"``, ``"windows"``.
    """

    def __init__(
        self,
        source_dir: Path,
        ignore_file: str = DOTFILEIGNORE,
        extra_patterns: Sequence[str] = (),
        current_os: Optional[str] = None,
    ) -> None:
        self._current_os = current_os or detect_os()

        # Unconditional patterns
        self._patterns: List[str] = list(DEFAULT_PATTERNS)
        global_pats, only_on, ignore_on = load_ignore_file(
            source_dir / ignore_file
        )
        self._patterns.extend(global_pats)
        self._patterns.extend(extra_patterns)

        # Build effective OS-conditional patterns for the current platform
        self._os_patterns: List[str] = []

        # [only_on.<os>] -- these patterns are ONLY for <os>; on all
        # OTHER platforms, the listed entries should be ignored.
        for os_name, pats in only_on.items():
            if os_name != self._current_os:
                self._os_patterns.extend(pats)

        # [ignore_on.<os>] -- ignore these entries ON <os>.
        for os_name, pats in ignore_on.items():
            if os_name == self._current_os:
                self._os_patterns.extend(pats)

    @property
    def patterns(self) -> List[str]:
        """A copy of all effective ignore patterns (unconditional + OS)."""
        return list(self._patterns) + list(self._os_patterns)

    @property
    def current_os(self) -> str:
        """The OS identifier used for conditional evaluation."""
        return self._current_os

    def is_ignored(self, name: str) -> bool:
        """Return *True* if *name* should be skipped during discovery."""
        return any(
            fnmatch.fnmatch(name, pat)
            for pat in self._patterns
        ) or any(
            fnmatch.fnmatch(name, pat)
            for pat in self._os_patterns
        )
