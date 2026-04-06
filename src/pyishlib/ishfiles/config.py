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

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from ..ish_config import IshConfig

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

DEFAULT_SOURCE_DIR = Path.home() / ".local" / "share" / "ishfiles"
DEFAULT_TARGET_DIR = Path.home()
DEFAULT_CONFIG_FILE = Path.home() / ".config" / "ishfiles" / "config.toml"


def _load_toml(path: Path) -> Dict[str, Any]:
    """Load a TOML file, returning an empty dict on missing file or no TOML support."""
    if not path.is_file():
        log.debug("Config file not found: %s", path)
        return {}
    if tomllib is None:
        log.warning(
            "TOML support unavailable (need Python 3.11+ or 'tomli'); " "ignoring %s",
            path,
        )
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _toml_to_namespace(file_data: Dict[str, Any]) -> SimpleNamespace:
    """Flatten the ``[ishfiles]`` and ``[ignore]`` TOML sections into a namespace.

    The resulting namespace has attributes ``source``, ``target``, and
    ``ignore_patterns`` that :class:`IshConfig` can resolve via
    ``__getattr__``.
    """
    ishfiles_section = file_data.get("ishfiles", {})
    ignore_section = file_data.get("ignore", {})

    attrs: Dict[str, Any] = {}
    if "source" in ishfiles_section:
        attrs["source"] = str(Path(ishfiles_section["source"]).expanduser())
    if "target" in ishfiles_section:
        attrs["target"] = str(Path(ishfiles_section["target"]).expanduser())

    attrs["ignore_patterns"] = list(ignore_section.get("patterns", []))

    return SimpleNamespace(**attrs)


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

    file_data = _load_toml(cfg_path)
    conf = _toml_to_namespace(file_data) if file_data else None

    # Filter out None-valued args so they don't shadow conf/defaults in
    # IshConfig's resolution chain (hasattr returns True for None attrs).
    filtered_args = None
    if args is not None:
        non_none = {k: v for k, v in vars(args).items() if v is not None}
        filtered_args = SimpleNamespace(**non_none)

    defaults = {
        "source": str(DEFAULT_SOURCE_DIR),
        "target": str(DEFAULT_TARGET_DIR),
        "ignore_patterns": [],
    }

    return IshConfig.from_args(args=filtered_args, conf=conf, defaults=defaults)
