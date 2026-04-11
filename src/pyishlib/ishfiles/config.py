#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
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
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

from .._compat import tomllib
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


_SCHEMA: Path = (
    Path(__file__).resolve().parent.parent.parent / "schema" / "ishfiles_config.json"
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
    # Data template filename inside config_dir
    "data_file": "data.toml",
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

    # Seed the preprocessing context with any persisted [data] values.
    data = _load_data_section(cfg_path)
    if data:
        cfg.context.update({k: str(v) for k, v in data.items()})

    return cfg


def _load_data_section(config_path: Path) -> Dict[str, Any]:
    """Read the ``[data]`` section from the TOML config file.

    Returns an empty dict if the file does not exist, TOML is unavailable,
    or there is no ``[data]`` section.
    """
    if tomllib is None or not config_path.is_file():
        return {}
    try:
        with open(config_path, "rb") as fh:
            raw = tomllib.load(fh)
        result = raw.get("data", {})
        return result if isinstance(result, dict) else {}
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to read [data] from %s: %s", config_path, exc)
        return {}
