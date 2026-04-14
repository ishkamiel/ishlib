#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Project-ishfiles and host-ishfiles discovery for isholate.

Project-local state lives under an ``.ishlib/`` umbrella in the project
root directory (by default the current working directory, but overridable
via ``--project-root``):

- ``.ishlib/ishfiles/`` — project-local ishfiles source tree, mounted into
  the container as pass 2 of provisioning.
- ``.ishlib/isholate/config.toml`` — isholate project config (image, shell).

The two subdirectories are independent — either may exist without the other.

Provides three helpers:

- :func:`discover_project_overlay` — checks a project root directory for
  ``.ishlib/ishfiles/`` (the project-local ishfiles source tree).
- :func:`load_project_config` — reads ``.ishlib/isholate/config.toml``
  from a project root directory and returns its contents as a plain
  ``dict``. Returns an empty dict if the file is absent.
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

# Umbrella project-local config directory.
PROJECT_DIR_NAME = ".ishlib"

# Subdirectory under .ishlib/ that acts as a project-local ishfiles source
# tree. Mirrors the layout of a normal ishfiles source (with its own
# ``ishconfig/``, ``ishscripts/``, etc.).
OVERLAY_SUBDIR = "ishfiles"

# Subdirectory under .ishlib/ that holds isholate-specific project config.
ISHOLATE_SUBDIR = "isholate"
ISHOLATE_CONFIG_FILE = "config.toml"

# XDG state directory under $HOME where logs from failed containers are saved.
# Full path: <home> / FAILED_LOGS_STATE_DIR / <container-name> / logs/
FAILED_LOGS_STATE_DIR = Path(".local") / "state" / "isholate" / "failed-logs"


def discover_project_overlay(root: Path) -> Optional[Path]:
    """Check *root* for a ``.ishlib/ishfiles/`` project-local ishfiles dir.

    Only the directory itself is checked — parent directories are not
    searched.  Pass the explicit project root (from ``--project-root``) or
    ``Path.cwd()`` as the root.

    Args:
        root: Directory to check.

    Returns:
        Absolute path to the ``.ishlib/ishfiles/`` directory, or ``None``.
    """
    candidate = root.resolve() / PROJECT_DIR_NAME / OVERLAY_SUBDIR
    return candidate if candidate.is_dir() else None


def load_project_config(root: Path) -> Dict[str, Any]:
    """Load ``.ishlib/isholate/config.toml`` from *root*.

    Returns the parsed TOML as a plain ``dict``.  Returns an empty dict
    when the file is absent or when no TOML library is available.

    Loading is independent of the project overlay: the isholate config
    may be present without a ``.ishlib/ishfiles/`` directory, and vice
    versa.

    Recognised keys (all optional):

    - ``image`` — Incus image to use instead of the isholate default.
    - ``shell`` — Login shell to use inside the container.

    Args:
        root: Project root directory (from ``--project-root`` or cwd).

    Returns:
        Parsed config dict, possibly empty.
    """
    if tomllib is None:
        return {}
    config_file = (
        root.resolve() / PROJECT_DIR_NAME / ISHOLATE_SUBDIR / ISHOLATE_CONFIG_FILE
    )
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
