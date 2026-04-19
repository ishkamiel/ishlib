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

Provides four helpers:

- :func:`discover_project_overlay` — checks a project root directory for
  ``.ishlib/ishfiles/`` (the project-local ishfiles source tree).
- :func:`load_project_config` — reads ``.ishlib/isholate/config.toml``
  from a project root directory and returns its contents as a plain
  ``dict``. Returns an empty dict if the file is absent.
- :func:`discover_host_ishfiles_source` — finds the host user's ishfiles
  source tree by reading ``~/.config/ishfiles/config.toml`` (the
  ``source`` key) and falling back to ``~/.local/share/ishfiles``.
  Returns ``None`` when the resolved path does not exist on disk.
- :func:`resolve_default_shell` — resolves the ``default_shell`` setting
  from ishfiles configs (project overlay, host user, host repo) so
  isholate can match the login shell that ``ishfiles apply`` configures
  inside the container.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .._compat import load_toml_file
from ..ishlib_folder import IshlibFolder

# Filename of isholate's per-project config inside ``.ishlib/isholate/``.
ISHOLATE_CONFIG_FILE = "config.toml"

# XDG state directory under $HOME where logs from failed containers are saved.
# Full path: <home> / FAILED_LOGS_STATE_DIR / <container-name> / logs/
FAILED_LOGS_STATE_DIR = Path(".local") / "state" / "isholate" / "failed-logs"

# XDG state directory under $HOME for per-base build locks.  One lock file
# per persistent base container name serializes concurrent invocations that
# would otherwise race ``incus init`` / ``incus copy`` / ``incus delete``
# against each other.  See :mod:`pyishlib.isholate.locks`.
# Full path: <home> / LOCKS_STATE_DIR / <container-name>.lock
LOCKS_STATE_DIR = Path(".local") / "state" / "isholate" / "locks"


def discover_project_overlay(root: Path) -> Optional[Path]:
    """Check *root* for a ``.ishlib/ishfiles/`` project-local ishfiles dir.

    Thin wrapper around :meth:`IshlibFolder.discover_ishfiles` kept under
    its historical name for the isholate call sites.

    Args:
        root: Directory to check.

    Returns:
        Absolute path to the ``.ishlib/ishfiles/`` directory, or ``None``.
    """
    return IshlibFolder(root).discover_tool("ishfiles")


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
    config_file = IshlibFolder(root).tool_dir("isholate") / ISHOLATE_CONFIG_FILE
    result = load_toml_file(config_file, default={})
    return result if isinstance(result, dict) else {}


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
    data = load_toml_file(config_file, default=None)
    if isinstance(data, dict):
        # The schema nests source under [ishfiles]; also accept a legacy
        # top-level key for backwards compatibility.
        ishfiles_section = data.get("ishfiles")
        if isinstance(ishfiles_section, dict) and ishfiles_section.get("source"):
            source = Path(ishfiles_section["source"])
        elif data.get("source"):
            source = Path(data["source"])

    if source is None:
        source = home / ".local" / "share" / "ishfiles"

    return source if source.exists() else None


# ---------------------------------------------------------------------------
# ishfiles default_shell resolution
# ---------------------------------------------------------------------------

# Subdirectory inside an ishfiles source tree that holds repo-level config.
_ISHFILES_CONFIG_DIR = "ishconfig"
_ISHFILES_REPO_CONFIG = "config.toml"


def _read_default_shell(toml_path: Path) -> Optional[str]:
    """Extract ``[ishfiles].default_shell`` from a TOML config file.

    Returns ``None`` if the file is missing, unreadable, or does not
    contain the key.
    """
    data = load_toml_file(toml_path, default=None)
    if not isinstance(data, dict):
        return None
    ishfiles_section = data.get("ishfiles")
    if not isinstance(ishfiles_section, dict):
        return None
    raw = ishfiles_section.get("default_shell")
    if not raw or not isinstance(raw, str):
        return None
    return raw.strip() or None


def _normalise_shell_path(shell: str) -> str:
    """Ensure *shell* is an absolute path suitable for ``incus exec``.

    The ``default_shell`` schema accepts basenames (``"zsh"``) and
    absolute paths (``"/usr/bin/zsh"``).  Inside an Ubuntu container
    ``/bin/<name>`` resolves correctly after ``ishfiles apply`` has
    installed the package, so basenames are prefixed with ``/bin/``.
    """
    if shell.startswith("/"):
        return shell
    return f"/bin/{shell}"


def resolve_default_shell(
    home: Path,
    host_source: Optional[Path],
    overlay_dir: Optional[Path],
) -> Optional[str]:
    """Resolve ``default_shell`` from ishfiles configs.

    Lookup order (first match wins):

    1. Project ishfiles overlay repo config
       (``<overlay>/ishconfig/config.toml``).
    2. Host user config (``~/.config/ishfiles/config.toml``).
    3. Host ishfiles repo config
       (``<host_source>/ishconfig/config.toml``).

    Returns an absolute path (e.g. ``/bin/zsh``) or ``None`` when no
    config provides a ``default_shell`` value.
    """
    # 1. Project overlay repo config
    if overlay_dir is not None:
        val = _read_default_shell(
            overlay_dir / _ISHFILES_CONFIG_DIR / _ISHFILES_REPO_CONFIG
        )
        if val:
            return _normalise_shell_path(val)

    # 2. Host user config
    val = _read_default_shell(home / ".config" / "ishfiles" / "config.toml")
    if val:
        return _normalise_shell_path(val)

    # 3. Host ishfiles repo config
    if host_source is not None:
        val = _read_default_shell(
            host_source / _ISHFILES_CONFIG_DIR / _ISHFILES_REPO_CONFIG
        )
        if val:
            return _normalise_shell_path(val)

    return None
