#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Project-overlay and host-ishfiles discovery for isholate.

Provides three helpers:

- :func:`discover_project_overlay` — walks up from *cwd* looking for a
  ``.isholate/`` directory (analogous to git's ``.git/`` discovery).
- :func:`load_project_config` — reads
  ``.isholate/ishconfig/isholate.toml`` and returns its contents as a
  plain ``dict``.  Returns an empty dict if the file is absent.
- :func:`discover_host_ishfiles_source` — finds the host user's ishfiles
  source tree by reading ``~/.config/ishfiles/config.toml`` (the
  ``source`` key) and falling back to ``~/.local/share/ishfiles``.
  Returns ``None`` when the resolved path does not exist on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# The .isholate/ directory that acts as a project-local ishfiles source tree.
OVERLAY_DIR_NAME = ".isholate"

# Reserved config dir name inside the overlay — mirrors ishfiles' "ishconfig".
# isholate.toml lives here so ishfiles ignores it during dotfile application.
_OVERLAY_CONFIG_DIR = "ishconfig"
_ISHOLATE_CONFIG_FILE = "isholate.toml"

# XDG state directory under $HOME where logs from failed containers are saved.
# Full path: <home> / FAILED_LOGS_STATE_DIR / <container-name> / logs/
FAILED_LOGS_STATE_DIR = Path(".local") / "state" / "isholate" / "failed-logs"


def discover_project_overlay(cwd: Path) -> Optional[Path]:
    """Walk up from *cwd* looking for a ``.isholate/`` directory.

    Returns the first ``.isholate/`` directory found, or ``None`` if the
    filesystem root is reached without finding one.

    Args:
        cwd: Starting directory for the search (typically ``Path.cwd()``).

    Returns:
        Absolute path to the ``.isholate/`` directory, or ``None``.
    """
    current = cwd.resolve()
    while True:
        candidate = current / OVERLAY_DIR_NAME
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_project_config(overlay_dir: Path) -> Dict[str, Any]:
    """Load ``.isholate/ishconfig/isholate.toml``.

    Returns the parsed TOML as a plain ``dict``.  Returns an empty dict
    when the file is absent or when no TOML library is available.

    Recognised keys (all optional):

    - ``image`` — Incus image to use instead of the isholate default.
    - ``shell`` — Login shell to use inside the container.

    Args:
        overlay_dir: The ``.isholate/`` directory returned by
            :func:`discover_project_overlay`.

    Returns:
        Parsed config dict, possibly empty.
    """
    if tomllib is None:
        return {}
    config_file = overlay_dir / _OVERLAY_CONFIG_DIR / _ISHOLATE_CONFIG_FILE
    if not config_file.is_file():
        return {}
    with open(config_file, "rb") as fh:
        return tomllib.load(fh)


def discover_host_ishfiles_source(home: Path) -> Optional[Path]:
    """Find the host user's ishfiles source tree.

    Resolution order:

    1. Read ``<home>/.config/ishfiles/config.toml`` and return the value
       of the ``source`` key if present.
    2. Fall back to ``<home>/.local/share/ishfiles`` (ishfiles' own
       default).

    Returns ``None`` if the resolved path does not exist on disk so
    callers can safely skip provisioning when ishfiles is not installed.

    Args:
        home: The host user's home directory (typically ``Path.home()``).

    Returns:
        Absolute path to the ishfiles source tree, or ``None``.
    """
    source: Optional[Path] = None

    config_file = home / ".config" / "ishfiles" / "config.toml"
    if config_file.is_file() and tomllib is not None:
        with open(config_file, "rb") as fh:
            data = tomllib.load(fh)
        raw = data.get("source")
        if raw:
            source = Path(raw)

    if source is None:
        source = home / ".local" / "share" / "ishfiles"

    return source if source.exists() else None
