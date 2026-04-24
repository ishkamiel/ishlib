# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``add`` subcommand -- add files to the dotfiles repository."""

from __future__ import annotations

import argparse
import filecmp
import logging
import os
import shutil
from pathlib import Path
from typing import List, Sequence

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...completions import FILE as _COMPLETE_FILE
from ...dotfile_finder import DotfileFinder
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ..applier import make_finder

log = logging.getLogger(__name__)


def _expand_directory_args(
    files: Sequence[str],
    finder: DotfileFinder,
) -> List[str]:
    """Expand directory arguments into their contained regular files.

    Mirrors ``git add <dir>`` semantics: when an argument resolves to a
    directory on the target filesystem, it is walked recursively and
    every regular file inside becomes an individual argument. Arguments
    that do not resolve to an existing directory pass through unchanged.

    Symlinks are skipped on both sides — walking does not descend into
    symlinked subdirectories and symlinked files are not included —
    because ``DotfileFinder`` later resolves arguments via
    :meth:`Path.resolve`, which would relocate a followed symlink's
    target outside the intended tree.
    """
    expanded: List[str] = []
    for arg in files:
        dotfile = finder.get(arg)
        if dotfile is None or not dotfile.target.is_dir():
            expanded.append(arg)
            continue
        matches: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(dotfile.target, followlinks=False):
            dir_path = Path(dirpath)
            for fname in filenames:
                fpath = dir_path / fname
                if fpath.is_symlink() or not fpath.is_file():
                    continue
                matches.append(fpath)
        matches.sort()
        if not matches:
            log.warning("Directory is empty, skipping: %s", dotfile.target)
            continue
        log.debug(
            "Expanding directory %s into %d file(s)", dotfile.target, len(matches)
        )
        expanded.extend(str(p) for p in matches)
    return expanded


class AddCommand(CliCommand):
    """Add files to the dotfiles repository."""

    NAME = "add"
    HELP = "Add files to the dotfiles repository"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        files_arg = parser.add_argument(
            "files",
            nargs="+",
            help="File(s) to add to the dotfiles repository",
        )
        files_arg.complete = _COMPLETE_FILE  # type: ignore[attr-defined]
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="Overwrite dirty files in the dotfiles repository",
        )
        parser.add_argument(
            "--no-git-add",
            dest="git_add",
            action="store_false",
            default=True,
            help="Do not stage added files with 'git add' in the dotfiles repo",
        )

    def run(self) -> int:
        """Execute the add command.

        For each file argument:

        1. Resolve it to a :class:`DotFile` via :class:`DotfileFinder`.
        2. The target must exist on the filesystem.
        3. If the source already exists and is identical, warn and skip.
        4. If the source exists and differs (dirty), refuse unless
           ``--force`` is given.
        5. Copy the target file into the source directory.

        Returns:
            0 on success, 1 if any file could not be added.
        """
        finder = make_finder(self.cfg)
        force = self.cfg.get_opt("force", False)
        files = _expand_directory_args(self.cfg.get_opt("files", []), finder)

        if not finder.source_dir.is_dir():
            log.error("Source directory does not exist: %s", finder.source_dir)
            return 1

        errors = 0
        added = 0
        staged_paths: List[Path] = []

        for file_arg in files:
            dotfile = finder.get(file_arg)

            if dotfile is None:
                log.error("Cannot resolve file: %s", file_arg)
                errors += 1
                continue

            if not dotfile.target.is_file():
                log.error("File does not exist: %s", dotfile.target)
                errors += 1
                continue

            if dotfile.source.exists() and not dotfile.source.is_file():
                log.error("Source path is not a regular file: %s", dotfile.source)
                errors += 1
                continue

            if dotfile.source.exists():
                if filecmp.cmp(str(dotfile.source), str(dotfile.target), shallow=False):
                    log.warning("Already tracked (identical): %s", dotfile.translated)
                    continue

                if not force:
                    log.error(
                        "Refusing to overwrite dirty file in dotfiles repository: "
                        "%s (use -f/--force to override)",
                        dotfile.rel_path,
                    )
                    errors += 1
                    continue

                log.info("Overwriting (--force): %s", dotfile.rel_path)

            dotfile.source.parent.mkdir(parents=True, exist_ok=True)

            if self.cfg.dry_run:
                log.info("Would add: %s -> %s", dotfile.target, dotfile.source)
            else:
                shutil.copy2(str(dotfile.target), str(dotfile.source))
                log.info("Added: %s -> %s", dotfile.translated, dotfile.rel_path)

            staged_paths.append(dotfile.source)
            added += 1

        if added and not self.cfg.dry_run:
            log.info("Added %d file(s).", added)

        if staged_paths and self.cfg.get_opt("git_add", True):
            self._stage_in_git(self.cfg, finder.source_dir, staged_paths)

        return 1 if errors else 0

    @staticmethod
    def _stage_in_git(
        cfg: IshConfig,
        source_dir: Path,
        paths: Sequence[Path],
    ) -> None:
        """Stage *paths* in the dotfiles source repo via :meth:`GitRepo.stage`.

        A soft no-op when *source_dir* is not a git working tree.
        Failures from ``git add`` are logged as warnings; the ``add``
        command's return code reflects only the copy step, since staging
        is a convenience layered on top.
        """
        try:
            repo = GitRepo.discover(source_dir)
        except NotAGitRepoError:
            log.debug(
                "Source is not a git repository, skipping staging: %s", source_dir
            )
            return

        repo.runner = CommandRunner(cfg)
        result = repo.stage(paths)
        if result.returncode != 0:
            log.warning(
                "git add returned non-zero exit code %d; files were copied but not staged",
                result.returncode,
            )
