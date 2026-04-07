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
from typing import List, Optional, Sequence

from ..command_runner import CommandRunner
from ..dotfile_script import DotfileScript
from ..file_preprocessor import FilePreprocessor
from ..ish_config import IshConfig
from ..command_runner import should_skip_for_os_from_metadata

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


def run_scripts(  # pylint: disable=too-many-return-statements,too-many-branches
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
    all_scripts = find_scripts(cfg, source_dir)

    if not all_scripts:
        log.info("No scripts found in %s/%s/", source_dir, scripts_dir_name)
        return 0

    # Filter to requested scripts if specified
    if scripts:
        requested = set(scripts)
        filtered = [s for s in all_scripts if s.name in requested]
        unknown = requested - {s.name for s in filtered}
        if unknown:
            log.error("Unknown scripts: %s", ", ".join(sorted(unknown)))
            return 1
        all_scripts = filtered

    if not all_scripts:
        return 0

    if not cfg.quiet:
        names = [s.name for s in all_scripts]
        print(f"Scripts to run ({len(all_scripts)}): {', '.join(names)}")

    runner = CommandRunner(cfg=cfg)
    preprocessor = FilePreprocessor(variables=cfg.context.as_dict())

    for script_path in all_scripts:
        script = DotfileScript(
            path=script_path,
            preprocessor=preprocessor,
            runner=runner,
        )

        # Preprocess to extract metadata for OS filtering
        try:
            script.preprocess()
        except (UnicodeDecodeError, FileNotFoundError):
            log.error("Cannot read script: %s", script_path)
            return 1

        if should_skip_for_os_from_metadata(script.metadata):
            log.debug("Skipping %s (OS rules in metadata)", script_path.name)
            if not cfg.quiet:
                print(f"  [skipped] {script_path.name} (OS rules)")
            continue

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
