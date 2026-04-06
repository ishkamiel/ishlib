#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""OS detection utilities for platform-conditional logic.

Provides :func:`detect_os` which returns the current operating system
as one of the recognised OS identifiers (``linux``, ``macos``,
``windows``), and :func:`should_skip_for_os` which evaluates
``only_on`` / ``ignore_on`` rules against the current platform.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, Optional, Sequence

log = logging.getLogger(__name__)

#: Recognised OS identifiers used in ``only_on`` / ``ignore_on`` rules.
RECOGNISED_OS = ("linux", "macos", "windows")


def detect_os() -> str:
    """Return the current OS as a recognised identifier.

    Returns:
        One of ``"linux"``, ``"macos"``, or ``"windows"``.

    Raises:
        RuntimeError: If the platform cannot be mapped to a recognised OS.
    """
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise RuntimeError(f"Unrecognised platform: {sys.platform}")


def should_skip_for_os(
    only_on: Optional[Sequence[str]] = None,
    ignore_on: Optional[Sequence[str]] = None,
    current_os: Optional[str] = None,
) -> bool:
    """Determine whether an item should be skipped based on OS rules.

    Args:
        only_on:     If set, the item applies *only* on these OSes.
                     It is skipped on all others.
        ignore_on:   If set, the item is skipped on these OSes.
        current_os:  Override for the detected OS (for testing).

    Returns:
        *True* if the item should be skipped on the current platform.
    """
    if current_os is None:
        current_os = detect_os()

    if only_on is not None:
        normalised = [_normalise_os(o) for o in only_on]
        if current_os not in normalised:
            return True

    if ignore_on is not None:
        normalised = [_normalise_os(o) for o in ignore_on]
        if current_os in normalised:
            return True

    return False


def should_skip_for_os_from_metadata(
    metadata: Optional[Dict[str, Any]],
    current_os: Optional[str] = None,
) -> bool:
    """Check ``only_on`` / ``ignore_on`` keys in a metadata dictionary.

    Convenience wrapper around :func:`should_skip_for_os` for use with
    ``__ISH__`` metadata dictionaries.

    Args:
        metadata:    Parsed metadata dict (may be *None*).
        current_os:  Override for the detected OS (for testing).

    Returns:
        *True* if the item should be skipped on the current platform.
    """
    if metadata is None:
        return False

    only_on = metadata.get("only_on")
    ignore_on = metadata.get("ignore_on")

    if only_on is None and ignore_on is None:
        return False

    # Accept both a single string and a list
    if isinstance(only_on, str):
        only_on = [only_on]
    if isinstance(ignore_on, str):
        ignore_on = [ignore_on]

    return should_skip_for_os(
        only_on=only_on, ignore_on=ignore_on, current_os=current_os
    )


def _normalise_os(name: str) -> str:
    """Normalise an OS name to its canonical form.

    Accepts common aliases (case-insensitive) and maps them to the
    canonical identifiers used internally.

    Raises:
        ValueError: If the name is not recognised.
    """
    mapping = {
        "linux": "linux",
        "macos": "macos",
        "mac": "macos",
        "darwin": "macos",
        "windows": "windows",
        "win": "windows",
        "win32": "windows",
    }
    canonical = mapping.get(name.lower())
    if canonical is None:
        raise ValueError(
            f"Unrecognised OS name: {name!r}; "
            f"expected one of {', '.join(RECOGNISED_OS)}"
        )
    return canonical
