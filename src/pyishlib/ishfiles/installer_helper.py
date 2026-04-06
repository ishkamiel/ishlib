#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Shared installer logic for ishfiles commands.

Loads a package configuration file from the ``ishconfig`` directory
inside the ishfiles source folder and provides helpers to install
the declared packages via the :class:`~pyishlib.installer.Installer`
framework.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Iterable, Optional

from ..command_runner import CommandRunner
from ..installer import Installer
from ..installer_config import InstallerConfigJSON, InstallerConfigTOML
from ..ish_config import IshConfig

log = logging.getLogger(__name__)

#: Recognised package-list filenames inside ``<source>/ishconfig/``.
_PACKAGE_FILES = [
    ("packages.toml", InstallerConfigTOML),
    ("packages.json", InstallerConfigJSON),
]


def find_package_config(source_dir: Path) -> Optional[Path]:
    """Return the first existing package config file, or *None*.

    Searches ``<source_dir>/ishconfig/`` for ``packages.toml`` then
    ``packages.json``.
    """
    config_dir = Path(source_dir) / "ishconfig"
    for filename, _ in _PACKAGE_FILES:
        candidate = config_dir / filename
        if candidate.is_file():
            log.debug("Found package config: %s", candidate)
            return candidate
    return None


def load_packages(config_file: Path) -> Iterable[dict]:
    """Load and return the platform-filtered package list from *config_file*."""
    suffix = config_file.suffix.lower()
    if suffix == ".toml":
        cfg = InstallerConfigTOML(config_file)
    elif suffix == ".json":
        cfg = InstallerConfigJSON(config_file)
    else:
        raise ValueError(f"Unsupported package config format: {config_file}")
    return cfg.get_pkgs()


def run_install(cfg: IshConfig, packages: Optional[Iterable[str]] = None) -> int:
    """Install packages defined in the ishfiles package config.

    Args:
        cfg:      Resolved ishfiles configuration.
        packages: Optional list of package names to install (default: all).

    Returns:
        0 on success or when no config file is found, 1 on errors.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
    config_file = find_package_config(source_dir)

    if config_file is None:
        log.info("No package config found in %s/ishconfig/", source_dir)
        return 0

    log.info("Loading packages from %s", config_file)
    all_pkgs = list(load_packages(config_file))

    if not all_pkgs:
        log.info("No packages defined in %s", config_file)
        return 0

    # Filter to requested packages if specified
    if packages:
        requested = set(packages)
        filtered = [p for p in all_pkgs if p["name"] in requested]
        unknown = requested - {p["name"] for p in filtered}
        if unknown:
            log.error("Unknown packages: %s", ", ".join(sorted(unknown)))
            return 1
        all_pkgs = filtered

    runner = CommandRunner(cfg=cfg)
    installer = Installer(cfg=cfg, runner=runner)

    missing = list(installer.get_missing_pkgs(all_pkgs))

    if not missing:
        if not cfg.quiet:
            print("All packages are already installed.")
        return 0

    if not cfg.quiet:
        names = [p["name"] for p in missing]
        print(f"Packages to install ({len(missing)}): {', '.join(names)}")

    if cfg.dry_run:
        return 0

    try:
        installer.install_pkgs(missing)
    except (subprocess.CalledProcessError, OSError) as exc:
        log.error("Package installation failed: %s", exc)
        return 1
    return 0
