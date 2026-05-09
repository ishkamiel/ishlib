# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
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

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .command_runner import CommandRunner
from .dotfile import ChangeType, DotFile
from .dotfile_finder import DotfileFinder
from .dotfile_ignore import DotfileIgnore
from .ish_metadata import collect_metadata_packages, read_metadata
from .dotfile_preprocessor import DotFilePreprocessor
from .ish_config import IshConfig
from .json_merge import canonical_json, deep_merge_json
from .userio import prompt_yes_no_always
from .environment import is_windows, should_skip_for_os_from_metadata

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DotfileApplier
# ---------------------------------------------------------------------------


class DotfileApplier:
    """Three-stage dotfile applier.

    1. :meth:`discover` -- find dotfiles in *source_dir* or from an
       explicit list (delegated to :class:`DotfileFinder`).
    2. :meth:`prepare` -- stage files into a temporary directory with
       preprocessing (metadata extraction, variable substitution, etc.).
    3. :meth:`apply` -- compare staged files with *target_dir*, prompt
       the user, and install changed files.

    Preprocessing variables are read from ``cfg.context``.

    Args:
        source_dir: Root of the dotfile repository.
        target_dir: Installation target (default ``$HOME``).
        cfg: Shared :class:`IshConfig` (created automatically if *None*).
             Its ``context`` attribute provides preprocessing variables.
        runner: Optional :class:`CommandRunner` (created automatically
                if *None*).
        dotfile_ignore: :class:`DotfileIgnore` controlling which files
                   to skip during discovery.
        finder: Optional pre-built :class:`DotfileFinder`.  When given,
                *source_dir* and *target_dir* are read from it.
    """

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
        cfg: Optional[IshConfig] = None,
        runner: Optional[CommandRunner] = None,
        dotfile_ignore: Optional[DotfileIgnore] = None,
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
            # source/target from cfg for any that are None.
            self._finder = DotfileFinder(self.cfg, source_dir=sd, target_dir=td)

        if dotfile_ignore is not None:
            self._dotfile_ignore = dotfile_ignore
        else:
            self._dotfile_ignore = DotfileIgnore(self._finder.source_dir)
        self._staging_dir: Optional[tempfile.TemporaryDirectory] = None

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

    # -- Stage 1b: Scan -------------------------------------------------------

    def scan(
        self, dotfiles: List[DotFile]
    ) -> Tuple[List[DotFile], List[Dict[str, Any]]]:
        """Read metadata from discovered dotfiles and collect embedded packages.

        For each dotfile, reads ``__ISH__`` metadata and applies OS filtering.
        Files that are excluded by OS rules are silently dropped.  For kept
        files, any ``[packages]`` section in the metadata is extracted and
        converted to the installer package-dict format.

        This method should be called **before** :meth:`prepare` so that
        package information from all files can be merged with the main
        package list before installation begins.

        Args:
            dotfiles: Files from :meth:`discover`.

        Returns:
            A tuple of *(kept_dotfiles, packages)* where *kept_dotfiles*
            have their :attr:`~DotFile.metadata` set, and *packages* is
            a list of package dicts (``{"name": ..., ...}``).
        """
        kept: List[DotFile] = []
        packages: List[Dict[str, Any]] = []

        for dotfile in dotfiles:
            try:
                meta = read_metadata(dotfile.source)
            except (ValueError, ImportError):
                meta = None
            if should_skip_for_os_from_metadata(meta):
                log.debug("Skipping %s (OS rules in metadata)", dotfile.source)
                continue

            dotfile.metadata = meta
            packages.extend(collect_metadata_packages(meta, source=str(dotfile.source)))
            kept.append(dotfile)

        return kept, packages

    # -- Stage 2: Prepare ----------------------------------------------------

    def prepare(self, dotfiles: List[DotFile]) -> List[DotFile]:
        """Stage discovered dotfiles for installation.

        Copies each file into a temporary staging directory, preserving
        the translated relative path.  Each text file is preprocessed:
        ``__ISH__`` metadata is extracted and stored, metadata blocks and
        ``@ish`` directive lines are stripped, and ``${__ish_<name>}``
        variable references are substituted.  Binary files that cannot
        be decoded as UTF-8 are copied verbatim.

        If :meth:`scan` has already been called, dotfiles will have their
        metadata pre-populated and OS filtering already applied.  Otherwise,
        this method reads metadata and performs OS filtering itself.

        Args:
            dotfiles: Files from :meth:`scan` or :meth:`discover`.

        Returns:
            The list of staged dotfiles (excluding OS-skipped ones),
            with each :attr:`DotFile.staged` set.
        """
        self._staging_dir = tempfile.TemporaryDirectory()
        staging_root = Path(self._staging_dir.name)
        preprocessor = DotFilePreprocessor(variables=self.cfg.context.as_dict())

        kept: List[DotFile] = []
        for dotfile in dotfiles:
            if dotfile.scanned:
                # scan() already read metadata and applied OS filtering.
                # Use the stored metadata, falling back to an empty dict
                # so the preprocessor skips redundant metadata reads.
                meta: Optional[Dict[str, Any]] = (
                    dotfile.metadata if dotfile.metadata is not None else {}
                )
            else:
                try:
                    meta = read_metadata(dotfile.source)
                except (ValueError, ImportError):
                    meta = None
                if should_skip_for_os_from_metadata(meta):
                    log.debug("Skipping %s (OS rules in metadata)", dotfile.source)
                    continue

            staged_path = staging_root / dotfile.translated
            staged_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                processed = preprocessor.preprocess(dotfile, metadata=meta)
                staged_path.write_text(processed, encoding="utf-8")
            except UnicodeDecodeError:
                log.debug("Binary file, copying verbatim: %s", dotfile.source)
                shutil.copy2(dotfile.source, staged_path)

            if dotfile.mergejson and not self._merge_json_stage(dotfile, staged_path):
                # Source did not parse as JSON; drop the file so the rest of
                # the pipeline is unaffected.
                continue

            dotfile.staged = staged_path
            log.debug("Staged %s -> %s", dotfile.source, staged_path)
            kept.append(dotfile)

        return kept

    # -- Stage 2b: mergejson post-step --------------------------------------

    def _merge_json_stage(self, dotfile: DotFile, staged_path: Path) -> bool:
        """Replace *staged_path* with its RFC 7396 merge against the target.

        Reads the just-staged source text as a JSON patch, merges it on
        top of the target (or an empty object when the target is missing
        or unparsable), and writes the canonical merged result back to
        *staged_path*.

        Args:
            dotfile: The owning :class:`DotFile` (used for logging only).
            staged_path: The staging-area path written by the text
                preprocessor.  Will be overwritten in place.

        Returns:
            ``True`` on success, ``False`` when the source is not valid
            JSON (in which case a warning has been logged and the caller
            should drop the file).
        """
        try:
            patch = json.loads(staged_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as err:
            log.warning(
                "mergejson source is not valid JSON, skipping %s: %s",
                dotfile.source,
                err,
            )
            return False

        base: Any = {}
        target = dotfile.target
        if target.exists() and target.is_file():
            try:
                base = json.loads(target.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as err:
                log.warning(
                    "mergejson target is not valid JSON, overwriting %s: %s",
                    target,
                    err,
                )
                base = {}

        merged = deep_merge_json(base, patch)
        staged_path.write_text(canonical_json(merged), encoding="utf-8")
        return True

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

    def is_target_up_to_date(self, dotfile: DotFile) -> bool:
        """Return True iff applying *dotfile* would produce no change.

        Runs :meth:`prepare` on a single dotfile and inspects the
        resulting :meth:`DotFile.get_change_type`.  Comparison is done
        in the same way as the real apply pipeline — byte-for-byte for
        plain files, semantic JSON match for ``mergejson_`` sources,
        and including the executable-bit check for ``executable_``
        files.  Useful for callers like ``ishfiles add`` that want to
        detect "nothing to do" before writing back into the source.

        Note:
            This invokes the full preprocessing pipeline, including
            any ``@ish`` directives the source may contain.  Callers
            that need to avoid interactive ``@ish prompt*`` directives
            should pre-check the source themselves (see
            :func:`pyishlib.file_preprocessor.has_prompt_directives`)
            and only call this method when it is safe to preprocess
            non-interactively.
        """
        prepared = self.prepare([dotfile])
        if not prepared:
            # OS-filtered or otherwise dropped — we can't say it's up
            # to date, so let the caller decide what to do.
            return False
        return prepared[0].get_change_type() is None

    def print_changes(self, changes: List[DotFile]) -> None:
        """Print a human-readable summary of pending changes."""
        if not changes:
            if self.cfg.verbose:
                print("No changes to apply.")
            return

        print(f"Changes to apply ({len(changes)}):")
        for dotfile in changes:
            change = dotfile.get_change_type()
            label = "NEW" if change == ChangeType.NEW else "MOD"
            print(f"  [{label}] {dotfile.target}")

    def apply_changes(self, changes: List[DotFile]) -> int:
        """Copy changed files into the target directory.

        Files whose source name carries the ``executable_`` prefix are made
        executable (``chmod +x``) after copying.

        Args:
            changes: Dotfiles from :meth:`get_changes`.

        Returns:
            Number of files applied (or that would be applied in
            dry-run mode).
        """
        applied = 0
        for dotfile in changes:
            if self.runner.copy(dotfile.effective_source, dotfile.target):
                if dotfile.executable and not is_windows():
                    if self.runner.dry_run:
                        print(f"chmod +x {dotfile.target}")
                    else:
                        dotfile.target.chmod(dotfile.target.stat().st_mode | 0o111)
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
