#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Shared installer logic for ishfiles commands.

Loads a package configuration file from the config directory
inside the ishfiles source folder and provides helpers to install
the declared packages via the :class:`~pyishlib.installer.Installer`
framework.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..command_runner import CommandRunner
from ..installer import Installer
from ..installer_config import InstallerConfigJSON, InstallerConfigTOML
from ..ish_config import IshConfig

log = logging.getLogger(__name__)

#: Map of file suffix to config loader class.
_SUFFIX_LOADERS = {
    ".toml": InstallerConfigTOML,
    ".json": InstallerConfigJSON,
}


def find_package_config(cfg: IshConfig, source_dir: Path) -> Optional[Path]:
    """Return the first existing package config file, or *None*.

    Searches ``<source_dir>/<config_dir>/`` for each filename listed in
    the ``package_files`` config option.
    """
    config_dir_name = cfg.get_opt("config_dir")
    package_files = cfg.get_opt("package_files")
    config_dir = Path(source_dir) / config_dir_name
    for filename in package_files:
        candidate = config_dir / filename
        if candidate.is_file():
            log.debug("Found package config: %s", candidate)
            return candidate
    return None


def load_packages(config_file: Path) -> Iterable[dict]:
    """Load and return the platform-filtered package list from *config_file*."""
    suffix = config_file.suffix.lower()
    loader = _SUFFIX_LOADERS.get(suffix)
    if loader is None:
        raise ValueError(f"Unsupported package config format: {config_file}")
    return loader(config_file).get_pkgs()


def merge_package_lists(
    base: List[Dict[str, Any]],
    extra: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge two package lists, deduplicating by name.

    Packages from *base* take precedence when the same name appears in
    both lists (i.e., the main config wins over metadata-embedded
    packages).

    Args:
        base:  The primary package list (e.g. from ``packages.toml``).
        extra: Additional packages (e.g. collected from file metadata).

    Returns:
        A merged list with no duplicate names.
    """
    seen = {p["name"] for p in base}
    merged = list(base)
    for pkg in extra:
        if pkg["name"] not in seen:
            merged.append(pkg)
            seen.add(pkg["name"])
        else:
            log.debug(
                "Package %r from metadata already in main config, skipping",
                pkg["name"],
            )
    return merged


def run_install(
    cfg: IshConfig,
    packages: Optional[Iterable[str]] = None,
    extra_packages: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Install packages defined in the ishfiles package config.

    Args:
        cfg:            Resolved ishfiles configuration.
        packages:       Optional list of package names to install (default: all).
        extra_packages: Additional package dicts (e.g. from file metadata)
                        to merge with the main config packages.

    Returns:
        0 on success or when no config file is found and no extra
        packages are provided, 1 on errors.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
    config_file = find_package_config(cfg, source_dir)

    if config_file is not None:
        log.info("Loading packages from %s", config_file)
        all_pkgs = list(load_packages(config_file))
    else:
        config_dir_name = cfg.get_opt("config_dir")
        log.info("No package config found in %s/%s/", source_dir, config_dir_name)
        all_pkgs = []

    # Merge in extra packages from file metadata
    if extra_packages:
        all_pkgs = merge_package_lists(all_pkgs, extra_packages)

    if not all_pkgs:
        return 0

    # Filter to requested packages if specified
    if packages and all_pkgs:
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

    if not cfg.dry_run:
        try:
            installer.install_pkgs(missing)
        except (subprocess.CalledProcessError, OSError) as exc:
            log.error("Package installation failed: %s", exc)
            return 1
    return 0
