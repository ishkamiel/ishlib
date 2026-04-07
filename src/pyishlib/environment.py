#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""OS, distro, and desktop environment detection utilities.

This module is the single home for all platform detection, OS/distro
identification, and environment checks used across the library.

Key functions:

- :func:`detect_os` — ``"linux"``, ``"macos"``, or ``"windows"``
- :func:`detect_distro` — ``"debian"``, ``"fedora"``, or *None*
- :func:`detect_os_tags` — e.g. ``["linux", "debian"]``
- :func:`normalise_os` — canonicalise aliases (``"ubuntu"`` → ``"debian"``)
- :func:`should_skip_for_os` / :func:`should_skip_for_os_from_metadata`
  — OS-conditional filtering
- :func:`is_windows`, :func:`is_ubuntu`, :func:`is_gnome`,
  :func:`is_linux_desktop` — simple boolean environment checks
"""

import logging
import os
import sys
from typing import Any, Dict, Optional, Sequence

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OS / distro detection utilities
# ---------------------------------------------------------------------------

#: Recognised OS and distro identifiers for ``only_on`` / ``ignore_on``.
#: Platform level: ``linux``, ``macos``, ``windows``.
#: Distro families: ``debian`` (Ubuntu, Debian, …), ``fedora`` (Fedora,
#: Asahi Remix, …).
RECOGNISED_OS = ("linux", "macos", "windows", "debian", "fedora")

# Distro family detection rules.  Each entry maps a canonical family name
# to a set of patterns matched against os-release ``ID`` and ``ID_LIKE``
# tokens.  Because derivative distros often use compound IDs containing
# hyphens (e.g. ``pop-os``, ``fedora-asahi-remix``) or set ``ID_LIKE``
# to one or more ancestor IDs (e.g. ``"rhel centos fedora"``), we check
# whether any token *starts with* a pattern rather than requiring an
# exact match.  This avoids having to enumerate every derivative.
#
# Patterns are checked against:
#   1. Each space-separated word in ``ID_LIKE`` (preferred -- this is
#      the canonical way distros declare their lineage).
#   2. The ``ID`` value itself (fallback for root distros like ``debian``
#      and ``fedora`` that don't set ``ID_LIKE``).
_DISTRO_FAMILY_PATTERNS: Dict[str, list] = {
    "debian": ["debian", "ubuntu", "raspbian"],
    "fedora": ["fedora", "rhel", "centos"],
}


def _read_os_release() -> Dict[str, str]:
    """Parse ``/etc/os-release`` into a dict.

    Returns an empty dict when the file does not exist or cannot be read.
    """
    result: Dict[str, str] = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as fh:
            text = fh.read()
    except (FileNotFoundError, PermissionError):
        return result
    for line in text.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip optional quotes
        value = value.strip('"').strip("'")
        result[key] = value
    return result


def _match_distro_family(tokens: list) -> Optional[str]:
    """Match a list of os-release tokens against distro family patterns.

    Each token is checked with :func:`str.startswith` against the
    patterns in :data:`_DISTRO_FAMILY_PATTERNS`, so ``"fedora-asahi-remix"``
    matches the ``"fedora"`` pattern and ``"pop-os"`` does not need to be
    listed explicitly because ``ID_LIKE=ubuntu debian`` already covers it.

    Args:
        tokens: Lowercased ID / ID_LIKE tokens to match.

    Returns:
        The canonical family name, or *None*.
    """
    for family, patterns in _DISTRO_FAMILY_PATTERNS.items():
        for token in tokens:
            for pat in patterns:
                if token.startswith(pat):
                    return family
    return None


def detect_distro() -> Optional[str]:
    """Detect the Linux distro family from ``/etc/os-release``.

    Detection uses ``ID_LIKE`` first (the canonical lineage declaration)
    then falls back to ``ID``.  Tokens are matched with startswith so
    that compound IDs like ``fedora-asahi-remix`` or ``pop-os`` are
    handled automatically.

    Returns:
        ``"debian"`` for Debian-like distros (Ubuntu, Mint, Pop!_OS, …),
        ``"fedora"`` for Fedora-like distros (Fedora, RHEL, Asahi Remix, …),
        or *None* if the distro is unknown or not on Linux.
    """
    if not sys.platform.startswith("linux"):
        return None

    info = _read_os_release()
    if not info:
        return None

    # Prefer ID_LIKE -- it's how distros declare their ancestry
    id_like = info.get("ID_LIKE", "").lower().split()
    result = _match_distro_family(id_like)
    if result is not None:
        return result

    # Fall back to ID (handles root distros like "debian", "fedora")
    distro_id = info.get("ID", "").lower()
    if distro_id:
        return _match_distro_family([distro_id])

    return None


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


def detect_os_tags() -> list:
    """Return all OS/distro tags that apply to the current platform.

    The list always starts with the broad OS identifier (``linux``,
    ``macos``, ``windows``) and may include a distro family tag
    (``debian``, ``fedora``) when running on Linux.

    This is used by :func:`should_skip_for_os` so that rules like
    ``only_on = ["debian"]`` match on Ubuntu, and ``only_on = ["linux"]``
    still matches on any Linux distro.
    """
    tags = [detect_os()]
    distro = detect_distro()
    if distro is not None:
        tags.append(distro)
    return tags


def normalise_os(name: str) -> str:
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
        "debian": "debian",
        "ubuntu": "debian",
        "fedora": "fedora",
    }
    canonical = mapping.get(name.lower())
    if canonical is None:
        raise ValueError(
            f"Unrecognised OS name: {name!r}; "
            f"expected one of {', '.join(RECOGNISED_OS)}"
        )
    return canonical


def should_skip_for_os(
    only_on: Optional[Sequence[str]] = None,
    ignore_on: Optional[Sequence[str]] = None,
    current_os: Optional[str] = None,
) -> bool:
    """Determine whether an item should be skipped based on OS rules.

    Matching is hierarchical: a rule specifying ``linux`` matches any
    Linux system, while ``debian`` matches only Debian-family distros.
    Conversely, a system running Ubuntu matches rules for both
    ``debian`` and ``linux``.

    Args:
        only_on:     If set, the item applies *only* on these OSes.
                     It is skipped on all others.
        ignore_on:   If set, the item is skipped on these OSes.
        current_os:  Override for the detected OS (for testing).
                     Can be a single tag or comma-separated tags
                     (e.g. ``"linux,debian"``).

    Returns:
        *True* if the item should be skipped on the current platform.
    """
    if current_os is not None:
        current_tags = [t.strip() for t in current_os.split(",")]
    else:
        current_tags = detect_os_tags()

    if only_on is not None:
        try:
            normalised = [normalise_os(o) for o in only_on]
        except ValueError as exc:
            log.warning("Bad only_on value, skipping OS filter: %s", exc)
            return False
        if not any(tag in normalised for tag in current_tags):
            return True

    if ignore_on is not None:
        try:
            normalised = [normalise_os(o) for o in ignore_on]
        except ValueError as exc:
            log.warning("Bad ignore_on value, skipping OS filter: %s", exc)
            return False
        if any(tag in normalised for tag in current_tags):
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


# ---------------------------------------------------------------------------
# Simple boolean environment checks
# ---------------------------------------------------------------------------


def is_windows() -> bool:
    """Return *True* if running on Windows."""
    return sys.platform == "win32"


def is_ubuntu() -> bool:
    """Return *True* if the system identifies as Ubuntu.

    Checks ``/etc/os-release`` for ``ubuntu`` in its content.
    """
    try:
        info = _read_os_release()
        return info.get("ID", "").lower() == "ubuntu"
    except (FileNotFoundError, PermissionError):
        return False


def is_gnome() -> bool:
    """Return *True* if the current desktop session is GNOME.

    Reads the ``XDG_CURRENT_DESKTOP`` environment variable.
    """
    cur_desk = os.environ.get("XDG_CURRENT_DESKTOP")
    return cur_desk is not None and cur_desk.lower() == "gnome"


def is_linux_desktop() -> bool:
    """Return *True* if running on a Linux desktop (X11 or Wayland).

    Checks that the platform is Linux and ``XDG_SESSION_TYPE`` is
    ``"x11"`` or ``"wayland"``.
    """
    if not sys.platform.startswith("linux"):
        return False
    session_type = os.environ.get("XDG_SESSION_TYPE")
    return session_type in ("x11", "wayland")
