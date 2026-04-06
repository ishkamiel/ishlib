#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
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
import logging
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

from .command_runner import CommandRunner
from .dotfile import ChangeType, DotFile
from .dotfile_finder import DotfileFinder
from .dotfile_ignore import DotfileIgnore
from .dotfile_preprocessor import DotFilePreprocessor
from .ish_config import IshConfig
from .ish_comp import prompt_yes_no_always, setup_logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DotfileApplier
# ---------------------------------------------------------------------------


class DotfileApplier:  # pylint: disable=too-many-instance-attributes
    """Three-stage dotfile applier.

    1. :meth:`discover` -- find dotfiles in *source_dir* or from an
       explicit list (delegated to :class:`DotfileFinder`).
    2. :meth:`prepare` -- stage files into a temporary directory with
       preprocessing (metadata extraction, variable substitution, etc.).
    3. :meth:`apply` -- compare staged files with *target_dir*, prompt
       the user, and install changed files.

    Args:
        source_dir: Root of the dotfile repository.
        target_dir: Installation target (default ``$HOME``).
        cfg: Shared :class:`IshConfig` (created automatically if *None*).
        runner: Optional :class:`CommandRunner` (created automatically
                if *None*).
        dotfile_ignore: :class:`DotfileIgnore` controlling which files
                   to skip during discovery.
        variables: Optional dictionary of preprocessing variables
                   available for ``${__ish_<name>}`` substitution.
        finder: Optional pre-built :class:`DotfileFinder`.  When given,
                *source_dir* and *target_dir* are read from it.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
        cfg: Optional[IshConfig] = None,
        runner: Optional[CommandRunner] = None,
        dotfile_ignore: Optional[DotfileIgnore] = None,
        variables: Optional[dict] = None,
        finder: Optional[DotfileFinder] = None,
    ) -> None:
        if runner is not None:
            self.cfg: IshConfig = cfg if cfg is not None else runner.cfg
            self.runner: CommandRunner = runner
        else:
            self.cfg = cfg if cfg is not None else IshConfig()
            self.runner = CommandRunner(cfg=self.cfg)

        if finder is not None:
            self._finder = finder
        else:
            sd = Path(source_dir) if source_dir is not None else None
            td = Path(target_dir) if target_dir is not None else None
            # Pass explicit dirs only when provided; DotfileFinder reads
            # source/target from cfg for any that are None.  Fall back to
            # Path.home() for target_dir only when neither the explicit
            # argument nor cfg provides one.
            self._finder = DotfileFinder(
                self.cfg, source_dir=sd, target_dir=td or Path.home()
            )

        if dotfile_ignore is not None:
            self._dotfile_ignore = dotfile_ignore
        else:
            self._dotfile_ignore = DotfileIgnore(self._finder.source_dir)
        self._staging_dir: Optional[tempfile.TemporaryDirectory] = None
        self._variables: dict = dict(variables) if variables else {}

    @property
    def finder(self) -> DotfileFinder:
        """The :class:`DotfileFinder` used for path resolution."""
        return self._finder

    @property
    def source_dir(self) -> Path:
        """The source dotfile repository directory."""
        return self._finder.source_dir

    @property
    def target_dir(self) -> Path:
        """The target directory (typically ``$HOME``)."""
        return self._finder.target_dir

    # -- Stage 1: Discover ---------------------------------------------------

    def discover(self, files: Optional[Sequence[Path]] = None) -> List[DotFile]:
        """Discover dotfiles to process.

        Delegates to :meth:`DotfileFinder.discover`, passing the
        configured ignore rules for recursive scans.

        Args:
            files: Optional explicit list of relative paths inside the
                   source directory.

        Returns:
            Sorted list of :class:`DotFile` objects.
        """
        return self._finder.discover(files=files, dotfile_ignore=self._dotfile_ignore)

    # -- Stage 2: Prepare ----------------------------------------------------

    def prepare(self, dotfiles: List[DotFile]) -> List[DotFile]:
        """Stage discovered dotfiles for installation.

        Copies each file into a temporary staging directory, preserving
        the translated relative path.  Each text file is preprocessed:
        ``__ISH__`` metadata is extracted and stored, metadata blocks and
        ``@ish`` directive lines are stripped, and ``${__ish_<name>}``
        variable references are substituted.  Binary files that cannot
        be decoded as UTF-8 are copied verbatim.

        Args:
            dotfiles: Files from :meth:`discover`.

        Returns:
            The same list, with each :attr:`DotFile.staged` set.
        """
        self._staging_dir = tempfile.TemporaryDirectory()  # pylint: disable=R1732
        staging_root = Path(self._staging_dir.name)
        preprocessor = DotFilePreprocessor(variables=self._variables)

        for dotfile in dotfiles:
            staged_path = staging_root / dotfile.translated
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

    # -- Stage 3: Apply ------------------------------------------------------

    def get_changes(self, dotfiles: List[DotFile]) -> List[DotFile]:
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
                log.debug("Unchanged: %s", dotfile.target)
        return changed

    def print_changes(self, changes: List[DotFile]) -> None:
        """Print a human-readable summary of pending changes."""
        if not changes:
            print("No changes to apply.")
            return

        print(f"Changes to apply ({len(changes)}):")
        for dotfile in changes:
            change = dotfile.get_change_type()
            label = "NEW" if change == ChangeType.NEW else "MOD"
            print(f"  [{label}] {dotfile.target}")

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
                log.info("Applied %s -> %s", dotfile.effective_source, dotfile.target)
        return applied

    # -- Full pipeline -------------------------------------------------------

    def apply(self, files: Optional[Sequence[Path]] = None) -> int:
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

        if not self.cfg.dry_run:
            choice = prompt_yes_no_always(f"Apply {len(changes)} change(s)?")
            if choice.no:
                print("Aborted.")
                return 0

        return self.apply_changes(changes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
    extra_patterns = list(args.ignore) if args.ignore else []

    log_level = logging.INFO if getattr(args, "verbose", False) else logging.WARNING
    cfg = IshConfig(
        dry_run=getattr(args, "dry_run", False),
        log_level=log_level,
    )
    setup_logging(cfg.log_level)

    di = DotfileIgnore(
        source_dir=args.source,
        extra_patterns=extra_patterns,
    )
    return DotfileApplier(
        source_dir=args.source,
        target_dir=args.target,
        cfg=cfg,
        dotfile_ignore=di,
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
