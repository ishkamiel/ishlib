#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging

from ...command_runner import CommandRunner
from ...dotfile import DotFile, ChangeType
from ...dotfile_preprocessor import DotFilePreprocessor
from ...ish_comp import prompt_yes_no_always
from ...ish_config import IshConfig
from ..config import IshfilesConfig
from ..scanner import IshfilesScanner

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``apply`` subcommand."""
    parser = subparsers.add_parser(
        "apply",
        help="Apply dotfiles from the ishfiles folder to the target directory",
    )
    parser.set_defaults(func=run)


def run(ishfiles_cfg: IshfilesConfig) -> int:
    """Execute the apply command.

    Returns:
        0 on success, 1 on failure.
    """
    cfg = IshConfig(dry_run=ishfiles_cfg.dry_run, log_level=ishfiles_cfg.log_level)
    runner = CommandRunner(cfg=cfg)

    scanner = IshfilesScanner(
        source_dir=ishfiles_cfg.source_dir,
        target_dir=ishfiles_cfg.target_dir,
        extra_patterns=ishfiles_cfg.ignore_patterns,
    )
    dotfiles = scanner.scan()

    if not dotfiles:
        print("No dotfiles found.")
        return 0

    dotfiles = _prepare(dotfiles)
    changes = _get_changes(dotfiles)

    if not changes:
        print("Everything is up to date.")
        return 0

    _print_changes(changes)

    if not cfg.dry_run:
        choice = prompt_yes_no_always(f"Apply {len(changes)} change(s)?")
        if choice.no:
            print("Aborted.")
            return 0

    applied = 0
    for dotfile in changes:
        if runner.copy(dotfile.effective_source, dotfile.target):
            applied += 1
            log.info("Applied %s", dotfile.target)

    print(f"Applied {applied} file(s).")
    return 0


def _prepare(dotfiles: list) -> list:
    """Run preprocessing on discovered dotfiles (in-place staging)."""
    import shutil
    import tempfile
    from pathlib import Path

    staging_dir = tempfile.mkdtemp(prefix="ishfiles-")
    preprocessor = DotFilePreprocessor()

    for dotfile in dotfiles:
        staged_path = Path(staging_dir) / dotfile.translated
        staged_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            processed = preprocessor.preprocess(dotfile)
            staged_path.write_text(processed, encoding="utf-8")
        except UnicodeDecodeError:
            log.debug("Binary file, copying verbatim: %s", dotfile.source)
            shutil.copy2(dotfile.source, staged_path)

        dotfile.staged = staged_path
        log.debug("Staged %s -> %s", dotfile.source, staged_path)

    return dotfiles


def _get_changes(dotfiles: list) -> list:
    """Filter to only dotfiles that would change the target."""
    changed = []
    for dotfile in dotfiles:
        change = dotfile.get_change_type()
        if change is not None:
            changed.append(dotfile)
        else:
            log.debug("Unchanged: %s", dotfile.target)
    return changed


def _print_changes(changes: list) -> None:
    """Print a summary of pending changes."""
    print(f"Changes to apply ({len(changes)}):")
    for dotfile in changes:
        change = dotfile.get_change_type()
        label = "NEW" if change == ChangeType.NEW else "MOD"
        print(f"  [{label}] {dotfile.target}")
