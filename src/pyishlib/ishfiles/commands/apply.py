#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging

from ...ish_comp import prompt_yes_no_always
from ...ish_config import IshConfig
from ..applier import make_applier, make_finder
from ..installer_helper import run_install
from ..script_runner import run_scanned_scripts, scan_scripts

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``apply`` subcommand."""
    parser = subparsers.add_parser(
        "apply",
        help="Apply dotfiles from the ishfiles folder to the target directory",
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=None,
        help="Restrict to specific files (source or target paths)",
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the apply command.

    The pipeline runs in five phases:

    1. **Scan** -- discover dotfiles and scripts, read metadata, apply
       OS filtering, and collect embedded package declarations.
    2. **Merge** -- combine metadata packages with the main package list.
    3. **Install** -- install all packages (main + metadata).
    4. **Apply** -- preprocess and install changed dotfiles.
    5. **Scripts** -- execute scripts.

    Returns:
        0 on success, 1 on error.
    """
    finder = make_finder(cfg)
    applier = make_applier(cfg, finder=finder)

    files = cfg.get_opt("files") or None
    rel_files = finder.get_rel_paths(files) if files else None

    # -- Phase 1: Scan -------------------------------------------------------
    log.info("Phase 1: Scanning dotfiles and scripts for metadata")

    dotfiles = applier.discover(files=rel_files)
    dotfiles, dotfile_pkgs = applier.scan(dotfiles)

    script_paths, script_pkgs = scan_scripts(cfg)

    # -- Phase 2: Merge ------------------------------------------------------
    extra_packages = dotfile_pkgs + script_pkgs
    if extra_packages:
        log.info("Collected %d package(s) from file metadata", len(extra_packages))

    # -- Phase 3: Install ----------------------------------------------------
    ret = run_install(cfg, extra_packages=extra_packages)
    if ret != 0:
        return ret

    # -- Phase 4: Apply dotfiles ---------------------------------------------
    dotfiles = applier.prepare(dotfiles)
    changes = applier.get_changes(dotfiles)
    applier.print_changes(changes)

    if changes:
        if not cfg.dry_run:
            choice = prompt_yes_no_always(f"Apply {len(changes)} change(s)?")
            if choice.no:
                print("Aborted.")
                return 0

        applied = applier.apply_changes(changes)
        if applied and not cfg.quiet:
            print(f"Applied {applied} file(s).")

    # -- Phase 5: Run scripts ------------------------------------------------
    ret = run_scanned_scripts(cfg, script_paths)
    if ret != 0:
        return ret

    return 0
