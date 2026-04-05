# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Dotfile applier for managing dotfile repositories.

Applies files from a dotfile repository to a target directory (typically
``$HOME``), translating chezmoi-style ``dot_`` prefixes to literal ``.``
prefixes.  Compares source and target to detect new or modified files,
prompts the user, and copies with dry-run support.
"""

from __future__ import annotations

import argparse
import filecmp
import logging
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .command_runner import CommandRunner
from .ish_comp import IshComp


class ChangeType(Enum):
    """Type of change to apply"""

    NEW = "new"
    MODIFIED = "modified"


class DotfileChange:  # pylint: disable=R0903
    """Represents a single dotfile change to be applied"""

    def __init__(
        self, source: Path, target: Path, change_type: ChangeType
    ) -> None:
        self.source: Path = source
        self.target: Path = target
        self.change_type: ChangeType = change_type

    def __repr__(self) -> str:
        return f"DotfileChange({self.change_type.value}: {self.source} -> {self.target})"


class DotfileApplier(IshComp):
    """Applies dotfiles from a source repository to a target directory.

    Handles chezmoi-style naming conventions:
    - ``dot_`` prefix in file/directory names is converted to ``.``
      (e.g., ``dot_bashrc`` becomes ``.bashrc``)

    The applier scans the source directory, computes changes against the
    target directory, prompts the user for confirmation, and applies the
    changes using a :class:`CommandRunner` for dry-run support.
    """

    DOT_PREFIX = "dot_"
    DEFAULT_IGNORE = frozenset({".git", ".github", ".gitignore", "__pycache__"})

    def __init__(
        self,
        source_dir: Path,
        target_dir: Path,
        runner: Optional[CommandRunner] = None,
        ignore: Optional[frozenset] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._source_dir: Path = Path(source_dir)
        self._target_dir: Path = Path(target_dir)
        self._ignore: frozenset = ignore if ignore is not None else self.DEFAULT_IGNORE
        if runner is not None:
            self.runner: CommandRunner = runner
        else:
            self.runner = CommandRunner(
                args=self._args, conf=self._conf, dry_run=self._dry_run
            )
        self.runner.dry_run = self.dry_run

    @property
    def source_dir(self) -> Path:
        """The source dotfile repository directory"""
        return self._source_dir

    @property
    def target_dir(self) -> Path:
        """The target directory (typically $HOME)"""
        return self._target_dir

    @staticmethod
    def translate_name(name: str) -> str:
        """Translate a single path component from dotfile repo naming.

        Converts the ``dot_`` prefix to a literal ``.`` prefix.

        Args:
            name: A single file or directory name (not a full path).

        Returns:
            The translated name.
        """
        if name.startswith(DotfileApplier.DOT_PREFIX):
            return "." + name[len(DotfileApplier.DOT_PREFIX) :]
        return name

    @staticmethod
    def translate_path(rel_path: Path) -> Path:
        """Translate all components of a relative path.

        Each component is passed through :meth:`translate_name`.

        Args:
            rel_path: A relative path from the source directory.

        Returns:
            The translated relative path.
        """
        parts = [DotfileApplier.translate_name(part) for part in rel_path.parts]
        return Path(*parts) if parts else rel_path

    def scan_source(self) -> List[Tuple[Path, Path]]:
        """Scan the source directory for dotfiles.

        Returns:
            A list of ``(source_path, target_path)`` tuples for every
            regular file found under the source directory (excluding
            ignored entries).
        """
        pairs: List[Tuple[Path, Path]] = []
        self._scan_dir(self._source_dir, Path(), pairs)
        pairs.sort(key=lambda p: p[1])
        return pairs

    def _scan_dir(
        self,
        current: Path,
        rel_prefix: Path,
        pairs: List[Tuple[Path, Path]],
    ) -> None:
        """Recursively scan a directory, collecting file pairs."""
        for entry in sorted(current.iterdir()):
            if entry.name in self._ignore:
                self.log.debug("Ignoring %s", entry)
                continue

            rel = rel_prefix / entry.name if rel_prefix != Path() else Path(entry.name)

            if entry.is_dir():
                self._scan_dir(entry, rel, pairs)
            elif entry.is_file():
                translated = self.translate_path(rel)
                target = self._target_dir / translated
                pairs.append((entry, target))

    def get_changes(self) -> List[DotfileChange]:
        """Compare source and target, returning needed changes.

        Returns:
            A list of :class:`DotfileChange` objects for files that are
            new or modified relative to the target directory.
        """
        changes: List[DotfileChange] = []
        for source, target in self.scan_source():
            if not target.exists():
                changes.append(DotfileChange(source, target, ChangeType.NEW))
            elif not target.is_file():
                self.log.debug(
                    "Target exists but is not a regular file, treating as modified: %s",
                    target,
                )
                changes.append(DotfileChange(source, target, ChangeType.MODIFIED))
            elif not filecmp.cmp(source, target, shallow=False):
                changes.append(DotfileChange(source, target, ChangeType.MODIFIED))
            else:
                self.log.debug("Unchanged: %s", target)
        return changes

    def print_changes(self, changes: List[DotfileChange]) -> None:
        """Print a human-readable summary of pending changes."""
        if not changes:
            self.print("No changes to apply.")
            return

        self.print(f"Changes to apply ({len(changes)}):")
        for change in changes:
            label = "NEW" if change.change_type == ChangeType.NEW else "MOD"
            self.print(f"  [{label}] {change.target}")

    def apply_changes(self, changes: List[DotfileChange]) -> int:
        """Apply a list of changes using the runner.

        Args:
            changes: The list of changes to apply.

        Returns:
            The number of changes processed. In dry-run mode, this is
            the number of changes that would be applied.
        """
        applied = 0
        for change in changes:
            if self.runner.copy(change.source, change.target):
                applied += 1
                self.log.info(
                    "Applied %s -> %s", change.source, change.target
                )
        return applied

    def apply(self) -> int:
        """Scan, prompt, and apply dotfile changes.

        This is the main entry point. It scans for changes, displays
        them, asks for user confirmation, and applies the changes.

        Returns:
            The number of changes processed by :meth:`apply_changes`,
            or ``0`` if the user declined or there were no changes.
            In dry-run mode, this is the number of changes that would
            be applied.
        """
        changes = self.get_changes()
        self.print_changes(changes)

        if not changes:
            return 0

        if not self.dry_run:
            choice = self.prompt_yes_no_always(
                f"Apply {len(changes)} change(s)?"
            )
            if choice.no:
                self.print("Aborted.")
                return 0

        return self.apply_changes(changes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)


def register_cli(subparsers: argparse._SubParsersAction) -> None:
    """Register dotfile subcommands onto an existing subparsers group.

    This allows a parent CLI to embed the dotfile commands as part of a
    larger tool, e.g.::

        parent_sub = parent_parser.add_subparsers(...)
        dotfile_applier.register_cli(parent_sub)

    Args:
        subparsers: An ``argparse._SubParsersAction`` to add commands to.
    """
    apply_parser = subparsers.add_parser(
        "dotfile-apply", help="Apply dotfiles from a source directory"
    )
    apply_parser.add_argument(
        "source",
        type=Path,
        help="Source dotfile repository directory",
    )
    apply_parser.add_argument(
        "-t",
        "--target",
        type=Path,
        default=Path.home(),
        help="Target directory (default: $HOME)",
    )
    apply_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be done without making changes",
    )
    apply_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )
    apply_parser.add_argument(
        "--ignore",
        action="append",
        dest="ignore",
        help="Additional names to ignore (may be repeated)",
    )
    apply_parser.set_defaults(func=_cmd_apply)

    status_parser = subparsers.add_parser(
        "dotfile-status", help="Show pending dotfile changes without applying"
    )
    status_parser.add_argument(
        "source",
        type=Path,
        help="Source dotfile repository directory",
    )
    status_parser.add_argument(
        "-t",
        "--target",
        type=Path,
        default=Path.home(),
        help="Target directory (default: $HOME)",
    )
    status_parser.add_argument(
        "--ignore",
        action="append",
        dest="ignore",
        help="Additional names to ignore (may be repeated)",
    )
    status_parser.set_defaults(func=_cmd_status)


def _build_applier(args: argparse.Namespace) -> DotfileApplier:
    """Construct a DotfileApplier from parsed CLI arguments."""
    ignore = DotfileApplier.DEFAULT_IGNORE
    if args.ignore:
        ignore = ignore | frozenset(args.ignore)

    log_level = logging.INFO if getattr(args, "verbose", False) else logging.WARNING

    return DotfileApplier(
        source_dir=args.source,
        target_dir=args.target,
        ignore=ignore,
        dry_run=getattr(args, "dry_run", False),
        log_level=log_level,
    )


def _cmd_apply(args: argparse.Namespace) -> int:
    """Handler for the dotfile-apply subcommand."""
    applier = _build_applier(args)
    applied = applier.apply()
    if applied:
        log.info("Applied %d file(s)", applied)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Handler for the dotfile-status subcommand."""
    applier = _build_applier(args)
    changes = applier.get_changes()
    applier.print_changes(changes)
    return 0 if not changes else 1


def _cli_main(argv=None):
    """CLI entry point for standalone dotfile_applier usage."""
    parser = argparse.ArgumentParser(
        prog="dotfile_applier",
        description="Apply dotfiles from a chezmoi-style source repository",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_cli(subparsers)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(_cli_main())
