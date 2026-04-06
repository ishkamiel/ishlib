#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Configuration loading for ishfiles.

Loads the TOML config file (``~/.config/ishfiles/config.toml``) and
merges it with CLI arguments and built-in defaults through
:class:`~pyishlib.ish_config.IshConfig`.

All reserved directory and file names used by the ishfiles tool are
defined here as module-level constants and registered as read-only
config options so that every component resolves them from the
:class:`IshConfig` instance.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from ..ish_config import IshConfig
from ..installer_custom import INSTALLERS_DIR_NAME

DEFAULT_SOURCE_DIR = Path.home() / ".local" / "share" / "ishfiles"
DEFAULT_TARGET_DIR = Path.home()
DEFAULT_CONFIG_FILE = Path.home() / ".config" / "ishfiles" / "config.toml"

#: Reserved directory for package configuration files.
CONFIG_DIR: str = "ishconfig"

#: Reserved directory for user scripts executed on apply/runscripts.
SCRIPTS_DIR: str = "ishscripts"

#: Reserved directory for custom installer scripts (re-exported from
#: :mod:`~pyishlib.installer_custom`).
INSTALLERS_DIR: str = INSTALLERS_DIR_NAME

#: Name of the per-repo ignore file.
IGNORE_FILE: str = ".ishignore"

#: Package config filenames recognised inside :data:`CONFIG_DIR`.
PACKAGE_FILES: list = ["packages.toml", "packages.json"]

_SCHEMA: Path = (
    Path(__file__).resolve().parent.parent.parent / "schema" / "ishfiles_config.json"
)

#: Read-only config options registered on every IshConfig built by
#: :func:`load_config`.  These cannot be overridden by CLI args or
#: TOML config.
_CONSTANTS = {
    "config_dir": CONFIG_DIR,
    "scripts_dir": SCRIPTS_DIR,
    "installers_dir": INSTALLERS_DIR,
    "ignore_file": IGNORE_FILE,
    "package_files": PACKAGE_FILES,
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
    cfg_path = DEFAULT_CONFIG_FILE
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
        "source": str(DEFAULT_SOURCE_DIR),
        "target": str(DEFAULT_TARGET_DIR),
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

    return cfg
