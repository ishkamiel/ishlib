#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Configuration loading for ishfiles.

Handles loading of settings from the TOML config file
(``~/.config/ishfiles/config.toml``), CLI arguments, and built-in
defaults.  The resolved values are exposed through :class:`IshfilesConfig`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    """Load a TOML file and return its contents as a dict.

    Returns an empty dict when the file does not exist or TOML support
    is unavailable.
    """
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


@dataclass
class IshfilesConfig:
    """Resolved configuration for the ishfiles tool.

    Resolution priority (highest to lowest):
    1. CLI arguments
    2. Config file (``~/.config/ishfiles/config.toml``)
    3. Built-in defaults

    Attributes:
        source_dir:   Root of the dotfile repository.
        target_dir:   Where dotfiles are installed (typically ``$HOME``).
        config_file:  Path to the TOML configuration file.
        ignore_patterns: Extra ignore patterns from the config file.
        dry_run:      When True, show what would be done without making changes.
        log_level:    Logging verbosity.
    """

    source_dir: Path = field(default_factory=lambda: DEFAULT_SOURCE_DIR)
    target_dir: Path = field(default_factory=lambda: DEFAULT_TARGET_DIR)
    config_file: Path = field(default_factory=lambda: DEFAULT_CONFIG_FILE)
    ignore_patterns: List[str] = field(default_factory=list)
    dry_run: bool = False
    log_level: int = field(default=logging.WARNING)

    @classmethod
    def load(
        cls,
        config_file: Optional[Path] = None,
        args: Optional[Any] = None,
    ) -> "IshfilesConfig":
        """Build an :class:`IshfilesConfig` by merging all sources.

        Args:
            config_file: Override path to the TOML config file.
            args:        An argparse namespace with CLI overrides.
        """
        cfg_path = config_file or DEFAULT_CONFIG_FILE
        if args is not None and getattr(args, "config", None) is not None:
            cfg_path = Path(args.config)

        file_data = _load_toml(cfg_path)
        ishfiles_section = file_data.get("ishfiles", {})
        ignore_section = file_data.get("ignore", {})

        # --- resolve source_dir ---
        if args is not None and getattr(args, "source", None) is not None:
            source_dir = Path(args.source).expanduser()
        elif "source" in ishfiles_section:
            source_dir = Path(ishfiles_section["source"]).expanduser()
        else:
            source_dir = DEFAULT_SOURCE_DIR

        # --- resolve target_dir ---
        if args is not None and getattr(args, "target", None) is not None:
            target_dir = Path(args.target).expanduser()
        elif "target" in ishfiles_section:
            target_dir = Path(ishfiles_section["target"]).expanduser()
        else:
            target_dir = DEFAULT_TARGET_DIR

        # --- resolve ignore patterns from config file ---
        ignore_patterns: List[str] = list(ignore_section.get("patterns", []))

        # --- resolve log level ---
        log_level = logging.WARNING
        if args is not None:
            if getattr(args, "debug", False):
                log_level = logging.DEBUG
            elif getattr(args, "verbose", False):
                log_level = logging.INFO
            elif getattr(args, "quiet", False):
                log_level = logging.ERROR

        # --- resolve dry_run ---
        dry_run = False
        if args is not None:
            dry_run = getattr(args, "dry_run", False)

        return cls(
            source_dir=source_dir,
            target_dir=target_dir,
            config_file=cfg_path,
            ignore_patterns=ignore_patterns,
            dry_run=dry_run,
            log_level=log_level,
        )
