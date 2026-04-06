#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Configuration loading for ishfiles.

Loads the TOML config file (``~/.config/ishfiles/config.toml``) and
merges it with CLI arguments and built-in defaults through
:class:`~pyishlib.ish_config.IshConfig`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from ..ish_config import IshConfig

DEFAULT_SOURCE_DIR = Path.home() / ".local" / "share" / "ishfiles"
DEFAULT_TARGET_DIR = Path.home()
DEFAULT_CONFIG_FILE = Path.home() / ".config" / "ishfiles" / "config.toml"

_SCHEMA: Path = (
    Path(__file__).resolve().parent.parent.parent / "schema" / "ishfiles_config.json"
)


def load_config(
    args: Optional[Any] = None,
    config_file: Optional[Path] = None,
) -> IshConfig:
    """Build an :class:`IshConfig` for ishfiles.

    Resolution priority: CLI *args* > TOML config file > built-in defaults.

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

    return IshConfig.from_toml(
        toml_path=cfg_path,
        schema=_SCHEMA,
        args=filtered_args,
        defaults=defaults,
    )
