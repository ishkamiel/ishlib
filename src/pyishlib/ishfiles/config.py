# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Configuration loading for ishfiles.

Loads the TOML config file (``~/.config/ishfiles/config.toml``) and
merges it with CLI arguments and built-in defaults through
:class:`~pyishlib.ish_config.IshConfig`.

Reserved directory and file names are registered as read-only constants
on :class:`IshConfig` so that every component resolves them via
``cfg.get_opt()``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

from .._compat import load_toml_file
from ..ish_config import IshConfig

log = logging.getLogger(__name__)

DEFAULT_SOURCE_DIR = Path.home() / ".local" / "share" / "ishfiles"
DEFAULT_TARGET_DIR = Path.home()
DEFAULT_CONFIG_FILE = Path.home() / ".config" / "ishfiles" / "config.toml"


def _default_paths(home: Path) -> "tuple[Path, Path, Path]":
    """Return (source_dir, target_dir, config_file) for a given home base."""
    return (
        home / ".local" / "share" / "ishfiles",
        home,
        home / ".config" / "ishfiles" / "config.toml",
    )


def _xdg_externals_cache_dir(home: Path) -> Path:
    """Return the XDG-compliant path for the externals git cache.

    Resolves to ``$XDG_CACHE_HOME/ishfiles/external`` when the environment
    variable is set, otherwise falls back to ``~/.cache/ishfiles/external``.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "ishfiles" / "external"
    return home / ".cache" / "ishfiles" / "external"


_SCHEMA: Path = (
    Path(__file__).resolve().parent.parent.parent / "schema" / "ishfiles_config.json"
)

_REPO_SCHEMA: Path = (
    Path(__file__).resolve().parent.parent.parent
    / "schema"
    / "ishfiles_repo_config.json"
)

# Read-only config options registered on every IshConfig built by
# load_config().  These cannot be overridden by CLI args or TOML config.
_CONSTANTS = {
    # Reserved directory for package configuration files
    "config_dir": "ishconfig",
    # Reserved directory for user scripts executed on apply/runscripts
    "scripts_dir": "ishscripts",
    # Reserved directory for custom per-package install scripts
    "installers_dir": "ishinstallers",
    # Name of the per-repo ignore file
    "ignore_file": ".ishignore",
    # Package config filenames recognised inside config_dir
    "package_files": ["packages.toml", "packages.json"],
    # Repo-level config filename inside config_dir (lower priority than user config)
    "repo_config_file": "config.toml",
    # Data template filename inside config_dir (per-machine prompted values)
    "data_file": "config-local.toml",
    # Externals config filename inside config_dir
    "externals_config_file": "externals.toml",
    # Externals state filename inside <target>/.config/ishfiles/
    "externals_state_filename": "externals-state.json",
}


def load_config(
    args: Optional[Any] = None,
    config_file: Optional[Path] = None,
) -> IshConfig:
    """Build an :class:`IshConfig` for ishfiles.

    Resolution priority: CLI *args* > TOML config file > built-in defaults.

    Read-only options (reserved directory names, ignore file name) are
    registered as constants and cannot be overridden.

    Args:
        args:        An argparse namespace with CLI overrides.
        config_file: Override path to the TOML config file (for testing).
    """
    # Determine effective home base for default paths.
    home = Path.home()
    if args is not None and getattr(args, "home", None) is not None:
        home = Path(args.home).expanduser()

    source_default, target_default, config_default = _default_paths(home)

    cfg_path = config_default
    if config_file is not None:
        cfg_path = config_file
    elif args is not None and getattr(args, "config", None) is not None:
        cfg_path = Path(args.config)

    # Filter out None-valued args so they don't shadow conf/defaults in
    # IshConfig's resolution chain (hasattr returns True for None attrs).
    filtered_args = None
    if args is not None:
        non_none = {k: v for k, v in vars(args).items() if v is not None}
        filtered_args = SimpleNamespace(**non_none)

    defaults = {
        "source": str(source_default),
        "target": str(target_default),
        "patterns": [],
    }

    cfg = IshConfig.from_toml(
        toml_path=cfg_path,
        schema=_SCHEMA,
        args=filtered_args,
        defaults=defaults,
    )

    for name, value in _CONSTANTS.items():
        cfg.set_constant(name, value)

    # The resolved config file path is fixed for this invocation.
    cfg.set_constant("config_file", cfg_path)

    # XDG-compliant externals cache directory (outside the source tree).
    cfg.set_constant("externals_cache_dir", str(_xdg_externals_cache_dir(home)))

    # Pass 2: load repo-level config from <source>/ishconfig/config.toml.
    # 'source' is now resolvable (from args/user-conf/defaults), so we can
    # locate the file inside the dotfiles source tree.  The repo-level config
    # sits between the user config and built-in defaults in the lookup chain.
    source_dir = Path(cfg.get_opt("source"))
    repo_cfg_path = (
        source_dir / cfg.get_opt("config_dir") / cfg.get_opt("repo_config_file")
    )
    cfg.repo_conf = IshConfig.load_toml(repo_cfg_path, schema=_REPO_SCHEMA)

    # Seed the preprocessing context with any persisted [data] values.
    data = _load_data_section(cfg_path)
    if data:
        cfg.context.update({k: str(v) for k, v in data.items()})

    # Resolve the effective username for user-scoped operations and scripts.
    # Custom value (via --custom-username) takes precedence; otherwise fall back
    # to the current process's login name.
    custom_username = cfg.get_opt("custom_username", default=None)
    if custom_username:
        effective_username = str(custom_username)
    else:
        try:
            import pwd  # local import: POSIX-only

            effective_username = pwd.getpwuid(os.getuid()).pw_name
        except Exception:  # noqa: BLE001
            effective_username = (
                os.environ.get("USER") or os.environ.get("LOGNAME") or ""
            )
    cfg.context.set("username", effective_username)

    return cfg


def _load_data_section(config_path: Path) -> Dict[str, Any]:
    """Read the ``[data]`` section from the TOML config file.

    Returns an empty dict if the file does not exist, TOML is unavailable,
    or there is no ``[data]`` section.
    """
    raw = load_toml_file(config_path, default={})
    result = raw.get("data", {}) if isinstance(raw, dict) else {}
    return result if isinstance(result, dict) else {}
