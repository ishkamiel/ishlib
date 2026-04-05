# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Dotfile applier for managing dotfile repositories"""

import filecmp
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .command_runner import CommandRunner
from .ish_comp import IshComp


class ChangeType(Enum):
    """Type of change to apply"""

    NEW = "new"
    MODIFIED = "modified"


class DotfileChange:
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
        self.runner: CommandRunner = (
            runner
            if runner is not None
            else CommandRunner(
                args=self._args,
                conf=self._conf,
                dry_run=self._dry_run,
            )
        )

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
            The number of files successfully applied.
        """
        applied = 0
        for change in changes:
            self.runner.mkdir(change.target.parent, parents=True)
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
            The number of files applied, or ``0`` if the user declined
            or there were no changes.
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
