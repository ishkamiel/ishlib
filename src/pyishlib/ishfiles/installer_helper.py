# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Shared installer logic for ishfiles commands.

Loads package configuration files from the config directory inside the
ishfiles source folder and provides helpers to install the declared packages
via the :class:`~pyishlib.installer.Installer` framework.

Package config files are discovered in ``<source>/ishconfig/``:

- ``packages.toml`` / ``packages.json`` — main config (no implicit OS filter)
- ``packages.<tag>.toml`` — tagged config; every package in the file gets
  ``<tag>`` prepended to its ``only_on`` list (AND semantics)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..command_runner import CommandRunner, UserDeclinedError
from ..environment import normalise_os
from ..installer import Installer
from ..installer_config import InstallerConfigJSON, InstallerConfigTOML
from ..ish_config import IshConfig
from ..userio import prompt_bool

log = logging.getLogger(__name__)

#: Map of file suffix to config loader class.
_SUFFIX_LOADERS = {
    ".toml": InstallerConfigTOML,
    ".json": InstallerConfigJSON,
}


def find_package_configs(
    cfg: IshConfig, source_dir: Path
) -> List[Tuple[Path, Optional[str]]]:
    """Return all package config files with their implicit ``only_on`` tag.

    Searches ``<source_dir>/<config_dir>/`` for:

    1. The main config file (``packages.toml`` or ``packages.json``) —
       returned with tag ``None`` (no implicit OS filter).
    2. Tagged configs ``packages.<tag>.toml`` — returned with *tag* as the
       implicit ``only_on`` value prepended to every package's filter.

    Returns:
        List of ``(path, implicit_tag)`` tuples in discovery order.
    """
    config_dir_name = cfg.get_opt("config_dir")
    package_files = cfg.get_opt("package_files")
    config_dir = Path(source_dir) / config_dir_name
    results: List[Tuple[Path, Optional[str]]] = []

    # Main config file (first match wins)
    for filename in package_files:
        candidate = config_dir / filename
        if candidate.is_file():
            log.debug("Found main package config: %s", candidate)
            results.append((candidate, None))
            break

    # Tagged configs: packages.<tag>.toml
    if config_dir.is_dir():
        for path in sorted(config_dir.glob("packages.*.toml")):
            # Extract tag from stem "packages.<tag>"
            tag = path.stem[len("packages.") :]
            if not tag:
                continue
            # Validate that the tag is a recognised OS/platform name
            try:
                normalise_os(tag)
            except ValueError:
                log.warning(
                    "Skipping %s: %r is not a recognised OS tag", path.name, tag
                )
                continue
            log.debug("Found tagged package config: %s (implicit tag: %s)", path, tag)
            results.append((path, tag))

    return results


# Keep old name as alias for callers that pass a single path directly
def find_package_config(cfg: IshConfig, source_dir: Path) -> Optional[Path]:
    """Return the first existing main package config file, or *None*.

    Deprecated: use :func:`find_package_configs` instead.
    """
    configs = find_package_configs(cfg, source_dir)
    if configs:
        path, tag = configs[0]
        if tag is None:
            return path
    return None


def _apply_implicit_tag(pkgs: List[Dict[str, Any]], tag: str) -> List[Dict[str, Any]]:
    """Prepend *tag* to the ``only_on`` list of every package in *pkgs*."""
    result = []
    for pkg in pkgs:
        p = dict(pkg)
        existing = list(p.get("only_on") or [])
        if tag not in existing:
            p["only_on"] = [tag] + existing
        result.append(p)
    return result


def load_packages(
    config_file: Path,
    cfg: Optional[IshConfig] = None,
    implicit_tag: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load and return the filtered package list from *config_file*.

    Args:
        config_file:   Path to a ``packages.toml`` or ``packages.json`` file.
        cfg:           IshConfig for tag/context filtering (optional).
        implicit_tag:  If set, prepend this tag to every package's
                       ``only_on`` list before filtering.
    """
    suffix = config_file.suffix.lower()
    loader = _SUFFIX_LOADERS.get(suffix)
    if loader is None:
        raise ValueError(f"Unsupported package config format: {config_file}")
    installer_cfg = loader(config_file, cfg=cfg)
    pkgs = list(installer_cfg.get_pkgs())
    if implicit_tag:
        pkgs = _apply_implicit_tag(pkgs, implicit_tag)
    return pkgs


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

    Discovers all package config files (main + tagged), loads and merges
    them, then installs missing packages.

    Each missing package is first checked against
    :meth:`Installer.pkg_is_available`.  Optional packages that are not
    available in the configured repos are silently skipped with a
    warning.  Required packages that are not available, or whose install
    actually fails, prompt the user (via :func:`prompt_bool`) whether to
    continue or abort -- the function returns 1 on abort, 0 on continue.
    Optional install failures still log a warning and continue.

    The ``--yes`` config flag (set by ``ishfiles apply --yes``) skips
    both prompts and treats them as "continue".

    Args:
        cfg:            Resolved ishfiles configuration.
        packages:       Optional list of package names to install (default: all).
        extra_packages: Additional package dicts (e.g. from file metadata)
                        to merge with the main config packages.

    Returns:
        0 on success, on user-confirmed continue past a required failure,
        or when no packages need installing; 1 on user-aborted required
        failure or unknown requested package names.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
    configs = find_package_configs(cfg, source_dir)

    all_pkgs: List[Dict[str, Any]] = []
    for config_file, implicit_tag in configs:
        log.info("Loading packages from %s (tag=%s)", config_file, implicit_tag)
        pkgs = list(load_packages(config_file, cfg=cfg, implicit_tag=implicit_tag))
        all_pkgs = merge_package_lists(all_pkgs, pkgs)

    if not all_pkgs:
        config_dir_name = cfg.get_opt("config_dir")
        log.info("No package config found in %s/%s/", source_dir, config_dir_name)

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
    missing: List[Dict[str, Any]] = [
        dict(p) for p in installer.get_missing_pkgs(all_pkgs)
    ]

    if not missing:
        if cfg.verbose:
            print("All packages are already installed.")
        return 0

    # Split into required and optional
    required = [p for p in missing if not p.get("optional")]
    optional = [p for p in missing if p.get("optional")]

    # Pre-filter both required and optional by repo availability so we don't
    # try to install packages the configured backends report as unknown
    # (e.g. an apt package that's actually only on snap, or a package that
    # needs a PPA that isn't configured).
    available_required: List[Dict[str, Any]] = []
    unavailable_required: List[Dict[str, Any]] = []
    for pkg in required:
        if installer.pkg_is_available(pkg):
            available_required.append(pkg)
        else:
            unavailable_required.append(pkg)

    available_optional: List[Dict[str, Any]] = []
    for pkg in optional:
        if installer.pkg_is_available(pkg):
            available_optional.append(pkg)
        else:
            log.warning(
                "Skipping optional package %s (not available in configured repos)",
                pkg["name"],
            )

    yes_flag = bool(cfg.get_opt("yes", default=False))

    if unavailable_required:
        unavailable_names = ", ".join(p["name"] for p in unavailable_required)
        log.error(
            "Required package(s) not available in configured repos: %s",
            unavailable_names,
        )
        if not yes_flag and not prompt_bool(
            "Continue without these packages?", default=False
        ):
            return 1

    to_install = available_required + available_optional

    if not to_install:
        if cfg.verbose:
            if missing:
                print("All installable packages are already installed.")
            else:
                print("All packages are already installed.")
        return 0

    if not cfg.quiet:
        names = [p["name"] for p in to_install]
        print(f"Packages to install ({len(to_install)}): {', '.join(names)}")

    if cfg.dry_run:
        return 0

    if available_required:
        try:
            installer.install_pkgs(available_required)
        except UserDeclinedError:
            log.warning("Skipping required packages (user declined sudo)")
        except (subprocess.CalledProcessError, OSError) as exc:
            log.error("Required package installation failed: %s", exc)
            if not yes_flag and not prompt_bool(
                "Continue despite install failure?", default=False
            ):
                return 1

    if available_optional:
        try:
            installer.install_pkgs(available_optional)
        except UserDeclinedError:
            log.warning("Skipping optional packages (user declined sudo)")
        except (subprocess.CalledProcessError, OSError) as exc:
            log.warning("Optional package installation failed: %s", exc)

    return 0
