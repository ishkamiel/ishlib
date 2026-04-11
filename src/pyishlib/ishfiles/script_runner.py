#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Script discovery and execution for the ``ishscripts`` folder.

Finds scripts in the scripts directory inside the ishfiles source
folder, preprocesses them through the ``@ish`` directive pipeline,
and executes them in sorted order.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..command_runner import CommandRunner
from ..dotfile_script import DotfileScript
from ..file_preprocessor import FilePreprocessor
from ..ish_config import IshConfig
from ..ish_metadata import collect_metadata_packages, read_metadata
from ..environment import should_skip_for_os_from_metadata

log = logging.getLogger(__name__)


def find_scripts(cfg: IshConfig, source_dir: Path) -> List[Path]:
    """Return all script files in the scripts directory.

    Scripts are returned sorted by name so that execution order is
    predictable (e.g. ``00-setup.sh`` runs before ``10-install.sh``).

    All regular files are included; directories and hidden files
    (starting with ``.``) are skipped.  Files need not be executable
    as they are preprocessed and executed through the ``@ish`` pipeline.
    """
    scripts_dir_name = cfg.get_opt("scripts_dir")
    scripts_dir = Path(source_dir) / scripts_dir_name
    if not scripts_dir.is_dir():
        log.debug("No scripts directory found: %s", scripts_dir)
        return []

    scripts = [
        p
        for p in sorted(scripts_dir.iterdir())
        if p.is_file() and not p.name.startswith(".")
    ]
    log.debug("Found %d script(s) in %s", len(scripts), scripts_dir)
    return scripts


def scan_scripts(
    cfg: IshConfig,
    scripts: Optional[Sequence[str]] = None,
    print_skipped: bool = False,
    all_scripts: Optional[List[Path]] = None,
) -> Tuple[List[Path], List[Dict[str, Any]]]:
    """Discover scripts, read metadata, and collect embedded packages.

    Performs OS filtering and extracts any ``[packages]`` sections from
    script metadata, without executing the scripts.

    Args:
        cfg:           Resolved ishfiles configuration.
        scripts:       Optional list of script names to include (default: all).
        print_skipped: When True, print a ``[skipped]`` line for each script
                       excluded by OS rules.
        all_scripts:   Optional pre-discovered list of script paths to filter

    Returns:
        A tuple of *(kept_scripts, packages)* where *kept_scripts* is
        the list of script paths that passed OS filtering, and *packages*
        is a list of package dicts collected from metadata.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
    all_scripts = (
        all_scripts if all_scripts is not None else find_scripts(cfg, source_dir)
    )

    if scripts:
        requested = set(scripts)
        all_scripts = [s for s in all_scripts if s.name in requested]

    kept: List[Path] = []
    packages: List[Dict[str, Any]] = []

    for script_path in all_scripts:
        try:
            meta = read_metadata(script_path)
        except (ValueError, ImportError):
            meta = None
        if should_skip_for_os_from_metadata(meta):
            log.debug("Skipping %s (OS rules in metadata)", script_path.name)
            if print_skipped:
                print(f"  [skipped] {script_path.name} (OS rules)")
            continue

        packages.extend(collect_metadata_packages(meta, source=script_path.name))
        kept.append(script_path)

    return kept, packages


def run_scanned_scripts(
    cfg: IshConfig,
    script_paths: List[Path],
) -> int:
    """Execute pre-scanned scripts (OS filtering already applied).

    Use this after :func:`scan_scripts` has already performed discovery
    and OS filtering.

    Args:
        cfg:          Resolved ishfiles configuration.
        script_paths: Script paths from :func:`scan_scripts`.

    Returns:
        0 on success or when no scripts are found, 1 on error.
    """
    if not script_paths:
        return 0

    if not cfg.quiet:
        names = [s.name for s in script_paths]
        print(f"Scripts to run ({len(script_paths)}): {', '.join(names)}")

    runner = CommandRunner(cfg=cfg)
    preprocessor = FilePreprocessor(variables=cfg.context.as_dict())

    for script_path in script_paths:
        script = DotfileScript(
            path=script_path,
            preprocessor=preprocessor,
            runner=runner,
        )

        if cfg.dry_run:
            log.info("Would run script: %s", script_path.name)
            if not cfg.quiet:
                print(f"  [dry-run] {script_path.name}")
            continue

        try:
            if not cfg.quiet:
                print(f"  Running: {script_path.name}")
            script.execute()
        except subprocess.CalledProcessError:
            log.error("Script failed: %s", script_path.name)
            return 1
        except FileNotFoundError:
            log.error("Script not found: %s", script_path)
            return 1

    return 0


def run_scripts(
    cfg: IshConfig,
    scripts: Optional[Sequence[str]] = None,
) -> int:
    """Discover and execute scripts from the scripts directory.

    Args:
        cfg:     Resolved ishfiles configuration.
        scripts: Optional list of script names to run (default: all).

    Returns:
        0 on success or when no scripts are found, 1 on error.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
    scripts_dir_name = cfg.get_opt("scripts_dir")
    all_found = find_scripts(cfg, source_dir)

    if not all_found:
        log.info("No scripts found in %s/%s/", source_dir, scripts_dir_name)
        return 0

    if scripts:
        requested = set(scripts)
        unknown = requested - {s.name for s in all_found}
        if unknown:
            log.error("Unknown scripts: %s", ", ".join(sorted(unknown)))
            return 1

    kept, _ = scan_scripts(
        cfg, scripts=scripts, print_skipped=not cfg.quiet, all_scripts=all_found
    )
    return run_scanned_scripts(cfg, kept)
