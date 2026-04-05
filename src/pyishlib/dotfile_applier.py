# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Dotfile applier for managing dotfile repositories.

Applies files from a dotfile repository to a target directory (typically
``$HOME``), translating chezmoi-style ``dot_`` prefixes to literal ``.``
prefixes.  The pipeline has three stages:

1. **Discover** -- scan a source directory (or accept an explicit file list)
   and build a list of :class:`DotFile` objects.
2. **Prepare** -- copy discovered files into a temporary staging directory
   where future preprocessing can be applied.
3. **Apply** -- compare the staged files against the target, prompt the
   user, and copy changed files into place.
"""

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import logging
import shutil
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Sequence

from .command_runner import CommandRunner
from .ish_comp import IshComp

DOT_PREFIX = "dot_"


# ---------------------------------------------------------------------------
# DotFile
# ---------------------------------------------------------------------------


class ChangeType(Enum):
    """Type of change to apply."""

    NEW = "new"
    MODIFIED = "modified"


def translate_name(name: str) -> str:
    """Translate a single path component from dotfile repo naming.

    Converts the ``dot_`` prefix to a literal ``.`` prefix.
    """
    if name.startswith(DOT_PREFIX):
        return "." + name[len(DOT_PREFIX) :]
    return name


def translate_path(rel_path: Path) -> Path:
    """Translate all components of a relative path.

    Each component is passed through :func:`translate_name`.
    """
    parts = [translate_name(part) for part in rel_path.parts]
    return Path(*parts) if parts else rel_path


class DotFile:
    """Represents a single dotfile managed by the applier.

    A *DotFile* knows its source path inside the repository, the
    translated relative path (with ``dot_`` resolved), and the
    absolute target path where it should be installed.  It also
    tracks an optional *staged* path used during the prepare step.

    Args:
        source: Absolute path to the file in the source repo.
        rel_path: Path of the file relative to the source root
                  (before translation).
        target_dir: The root target directory (e.g. ``$HOME``).
    """

    def __init__(self, source: Path, rel_path: Path, target_dir: Path) -> None:
        self._source: Path = source
        self._rel_path: Path = rel_path
        self._target_dir: Path = target_dir
        self._translated: Path = translate_path(rel_path)
        self._staged: Optional[Path] = None

    @property
    def source(self) -> Path:
        """Absolute path to the file in the source repository."""
        return self._source

    @property
    def rel_path(self) -> Path:
        """Relative path inside the source repository (untranslated)."""
        return self._rel_path

    @property
    def translated(self) -> Path:
        """Relative path after ``dot_`` translation."""
        return self._translated

    @property
    def target(self) -> Path:
        """Absolute path where the file should be installed."""
        return self._target_dir / self._translated

    @property
    def staged(self) -> Optional[Path]:
        """Absolute path to the staged (preprocessed) copy, if any."""
        return self._staged

    @staged.setter
    def staged(self, path: Optional[Path]) -> None:
        self._staged = path

    @property
    def effective_source(self) -> Path:
        """The file to compare / copy: staged copy if available, else source."""
        return self._staged if self._staged is not None else self._source

    def get_change_type(self) -> Optional[ChangeType]:
        """Compare the effective source against the target.

        Returns:
            :attr:`ChangeType.NEW` if the target does not exist,
            :attr:`ChangeType.MODIFIED` if it differs, or *None* if
            the files are identical.
        """
        if not self.target.exists():
            return ChangeType.NEW
        if not self.target.is_file():
            return ChangeType.MODIFIED
        if not filecmp.cmp(self.effective_source, self.target, shallow=False):
            return ChangeType.MODIFIED
        return None

    def __repr__(self) -> str:
        return (
            f"DotFile(source={self._source}, "
            f"translated={self._translated}, "
            f"target={self.target})"
        )


# ---------------------------------------------------------------------------
# Ignore handling
# ---------------------------------------------------------------------------


DEFAULT_IGNORE = frozenset({".git", ".github", ".gitignore", "__pycache__"})

_DOTFILEIGNORE = ".dotfileignore"


def _load_ignore_file(path: Path) -> List[str]:
    """Load gitignore-style patterns from *path*, skipping blanks/comments."""
    patterns: List[str] = []
    if not path.is_file():
        return patterns
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def _is_ignored(
    name: str,
    ignore_set: frozenset,
    ignore_patterns: Sequence[str],
) -> bool:
    """Return True if *name* should be ignored."""
    if name in ignore_set:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in ignore_patterns)


# ---------------------------------------------------------------------------
# DotfileApplier
# ---------------------------------------------------------------------------


class DotfileApplier(IshComp):
    """Three-stage dotfile applier.

    1. :meth:`discover` -- find dotfiles in *source_dir* or from an
       explicit list.
    2. :meth:`prepare` -- stage files into a temporary directory (a
       no-op copy for now; future preprocessing goes here).
    3. :meth:`apply` -- compare staged files with *target_dir*, prompt
       the user, and install changed files.

    Args:
        source_dir: Root of the dotfile repository.
        target_dir: Installation target (default ``$HOME``).
        runner: Optional :class:`CommandRunner` (created automatically
                if *None*).
        ignore: Extra names to ignore on top of :data:`DEFAULT_IGNORE`.
        **kwargs: Forwarded to :class:`IshComp`.
    """

    def __init__(
        self,
        source_dir: Path,
        target_dir: Optional[Path] = None,
        runner: Optional[CommandRunner] = None,
        ignore: Optional[frozenset] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._source_dir: Path = Path(source_dir)
        self._target_dir: Path = Path(target_dir) if target_dir is not None else Path.home()
        self._ignore: frozenset = ignore if ignore is not None else DEFAULT_IGNORE
        self._ignore_patterns: List[str] = _load_ignore_file(
            self._source_dir / _DOTFILEIGNORE
        )
        self._staging_dir: Optional[tempfile.TemporaryDirectory] = None

        if runner is not None:
            self.runner: CommandRunner = runner
        else:
            self.runner = CommandRunner(
                args=self._args, conf=self._conf, dry_run=self._dry_run
            )
        self.runner.dry_run = self.dry_run

    @property
    def source_dir(self) -> Path:
        """The source dotfile repository directory."""
        return self._source_dir

    @property
    def target_dir(self) -> Path:
        """The target directory (typically ``$HOME``)."""
        return self._target_dir

    # -- Stage 1: Discover ---------------------------------------------------

    def discover(
        self, files: Optional[Sequence[Path]] = None
    ) -> List[DotFile]:
        """Discover dotfiles to process.

        When *files* is given, each path is treated as relative to the
        source directory and looked up directly.  Otherwise the source
        directory is scanned recursively.

        Args:
            files: Optional explicit list of relative paths inside the
                   source directory.

        Returns:
            Sorted list of :class:`DotFile` objects.
        """
        if files is not None:
            return self._discover_explicit(files)
        return self._discover_scan()

    def _discover_scan(self) -> List[DotFile]:
        """Recursively scan source_dir for dotfiles."""
        dotfiles: List[DotFile] = []
        self._scan_dir(self._source_dir, Path(), dotfiles)
        dotfiles.sort(key=lambda df: df.translated)
        return dotfiles

    def _scan_dir(
        self,
        current: Path,
        rel_prefix: Path,
        dotfiles: List[DotFile],
    ) -> None:
        for entry in sorted(current.iterdir()):
            if _is_ignored(entry.name, self._ignore, self._ignore_patterns):
                self.log.debug("Ignoring %s", entry)
                continue

            rel = rel_prefix / entry.name if rel_prefix != Path() else Path(entry.name)

            if entry.is_dir():
                self._scan_dir(entry, rel, dotfiles)
            elif entry.is_file():
                dotfiles.append(DotFile(entry, rel, self._target_dir))

    def _discover_explicit(self, files: Sequence[Path]) -> List[DotFile]:
        """Build DotFile objects for an explicit list of relative paths."""
        dotfiles: List[DotFile] = []
        for rel in files:
            source = self._source_dir / rel
            if not source.is_file():
                self.log.warning("File not found, skipping: %s", source)
                continue
            dotfiles.append(DotFile(source, rel, self._target_dir))
        dotfiles.sort(key=lambda df: df.translated)
        return dotfiles

    # -- Stage 2: Prepare ----------------------------------------------------

    def prepare(self, dotfiles: List[DotFile]) -> List[DotFile]:
        """Stage discovered dotfiles for installation.

        Copies each file into a temporary staging directory, preserving
        the translated relative path.  Future preprocessing (template
        expansion, variable substitution, etc.) would be added here.

        Args:
            dotfiles: Files from :meth:`discover`.

        Returns:
            The same list, with each :attr:`DotFile.staged` set.
        """
        self._staging_dir = tempfile.TemporaryDirectory()  # pylint: disable=R1732
        staging_root = Path(self._staging_dir.name)

        for dotfile in dotfiles:
            staged_path = staging_root / dotfile.translated
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dotfile.source, staged_path)
            dotfile.staged = staged_path
            self.log.debug("Staged %s -> %s", dotfile.source, staged_path)

        return dotfiles

    # -- Stage 3: Apply ------------------------------------------------------

    def get_changes(
        self, dotfiles: List[DotFile]
    ) -> List[DotFile]:
        """Filter dotfiles to only those that would change the target.

        Args:
            dotfiles: Files from :meth:`prepare` (or :meth:`discover`).

        Returns:
            Subset of *dotfiles* that are new or modified.
        """
        changed: List[DotFile] = []
        for dotfile in dotfiles:
            change = dotfile.get_change_type()
            if change is not None:
                changed.append(dotfile)
            else:
                self.log.debug("Unchanged: %s", dotfile.target)
        return changed

    def print_changes(self, changes: List[DotFile]) -> None:
        """Print a human-readable summary of pending changes."""
        if not changes:
            self.print("No changes to apply.")
            return

        self.print(f"Changes to apply ({len(changes)}):")
        for dotfile in changes:
            change = dotfile.get_change_type()
            label = "NEW" if change == ChangeType.NEW else "MOD"
            self.print(f"  [{label}] {dotfile.target}")

    def apply_changes(self, changes: List[DotFile]) -> int:
        """Copy changed files into the target directory.

        Args:
            changes: Dotfiles from :meth:`get_changes`.

        Returns:
            Number of files applied (or that would be applied in
            dry-run mode).
        """
        applied = 0
        for dotfile in changes:
            if self.runner.copy(dotfile.effective_source, dotfile.target):
                applied += 1
                self.log.info("Applied %s -> %s", dotfile.effective_source, dotfile.target)
        return applied

    # -- Full pipeline -------------------------------------------------------

    def apply(
        self, files: Optional[Sequence[Path]] = None
    ) -> int:
        """Run the full discover / prepare / apply pipeline.

        Args:
            files: Optional explicit list of relative source paths.
                   If *None*, the source directory is scanned.

        Returns:
            Number of files applied, or 0 if the user declined or
            there were no changes.
        """
        dotfiles = self.discover(files)
        dotfiles = self.prepare(dotfiles)
        changes = self.get_changes(dotfiles)
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
    _add_common_args(apply_parser)
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
        "-f",
        "--file",
        action="append",
        type=Path,
        dest="files",
        help="Specific file to apply (relative to source, may be repeated)",
    )
    apply_parser.set_defaults(func=_cmd_apply)

    status_parser = subparsers.add_parser(
        "dotfile-status", help="Show pending dotfile changes without applying"
    )
    _add_common_args(status_parser)
    status_parser.set_defaults(func=_cmd_status)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments shared between apply and status subcommands."""
    parser.add_argument(
        "source",
        type=Path,
        help="Source dotfile repository directory",
    )
    parser.add_argument(
        "-t",
        "--target",
        type=Path,
        default=Path.home(),
        help="Target directory (default: $HOME)",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        dest="ignore",
        help="Additional names to ignore (may be repeated)",
    )


def _build_applier(args: argparse.Namespace) -> DotfileApplier:
    """Construct a DotfileApplier from parsed CLI arguments."""
    ignore = DEFAULT_IGNORE
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
    explicit = args.files if args.files else None
    applied = applier.apply(files=explicit)
    if applied:
        log.info("Applied %d file(s)", applied)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Handler for the dotfile-status subcommand."""
    applier = _build_applier(args)
    dotfiles = applier.discover()
    dotfiles = applier.prepare(dotfiles)
    changes = applier.get_changes(dotfiles)
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
