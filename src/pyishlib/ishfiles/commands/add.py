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
from typing import List, Sequence, Tuple

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...completions import FILE as _COMPLETE_FILE
from ...dotfile_finder import DotfileFinder
from ...file_preprocessor import (
    has_directives,
    has_prompt_directives,
    has_variable_refs,
)
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ish_metadata import has_metadata
from ..applier import make_applier, make_finder

log = logging.getLogger(__name__)


def _detect_template_constructs(source: Path) -> Tuple[List[str], bool]:
    '''Return ``(labels, has_prompts)`` for templating in *source*.

    *labels* is a list of human-readable descriptions of every
    templating construct found — variable references, ``@ish``
    directives, ``__ISH__`` metadata (any embed form, including the
    Python ``__ish__ = """..."""`` assignment, plus the ``.ish``
    sidecar).  *has_prompts* is True when the source contains an
    interactive ``@ish prompt*`` directive that would block the
    preprocessor on stdin; callers using the equality fast-path can
    skip it in that case.

    Both values are derived from the central detection helpers in
    :mod:`pyishlib.file_preprocessor` and :mod:`pyishlib.ish_metadata`
    so this command stays in sync with whatever the preprocessor
    actually understands.
    '''
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    found: List[str] = []
    if text and has_variable_refs(text):
        found.append("${__ish_*} variable references")
    if text and has_directives(text):
        found.append("@ish directives")
    if has_metadata(source):
        found.append("__ISH__ metadata")
    prompts = bool(text) and has_prompt_directives(text)
    return found, prompts


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
            nargs="*",
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
            "-u",
            "--update",
            action="store_true",
            default=False,
            help=(
                "Re-add every file already tracked in the dotfiles "
                "repository. Identical files are skipped (existing "
                "duplicate detection), so only changed files are "
                "actually copied. Combine with explicit FILES to "
                "include extra paths."
            ),
        )
        parser.add_argument(
            "--overwrite-template",
            action="store_true",
            default=False,
            help=(
                "Allow overwriting an existing source file that contains "
                "templating constructs (${__ish_*} references, @ish "
                "directives, or __ISH__ metadata). Refused by default to "
                "prevent silent loss of template syntax."
            ),
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
        4. If the source carries templating (``${__ish_*}`` references,
           ``@ish`` directives, or an ``__ISH__`` metadata block in any
           embed form), guard the overwrite:

           a. If the source has no interactive ``@ish prompt*``
              directives, ask the applier whether the live target is
              already up to date with the preprocessed source — if so,
              log at ``info`` and skip (the target was produced by a
              prior ``apply`` and there is nothing new to capture; the
              skip is intentionally quiet at default verbosity, matching
              ``diff``'s "everything is up to date" report).
           b. Otherwise refuse unless ``--overwrite-template`` is
              given, since a blind byte copy would silently destroy
              the template syntax.
        5. If the source exists and differs from the target, classify
           the source's git state: a clean tracked source is overwritten
           (this is the normal *update* path), a source with uncommitted
           edits is refused unless ``--force`` is given, and a source
           outside any git repo is refused unless ``--force`` is given
           (we can't tell what we'd lose).
        6. Copy the target file into the source directory.

        Returns:
            0 on success, 1 if any file could not be added.
        """
        finder = make_finder(self.cfg)
        applier = make_applier(self.cfg, finder=finder)
        force = self.cfg.get_opt("force", False)
        update = self.cfg.get_opt("update", False)
        overwrite_template = self.cfg.get_opt("overwrite_template", False)
        explicit = list(self.cfg.get_opt("files", []) or [])

        if not finder.source_dir.is_dir():
            log.error("Source directory does not exist: %s", finder.source_dir)
            return 1

        if not explicit and not update:
            log.error("No files given (specify FILES or use -u/--update).")
            return 1

        files = _expand_directory_args(explicit, finder)
        if update:
            # Canonicalise dedup keys via DotfileFinder.translate_arg so the
            # same dotfile referenced two different ways (explicit
            # ``.bashrc`` vs. update-discovered ``/home/u/.bashrc``, or
            # source-relative ``dot_bashrc`` vs. absolute target path)
            # collapses to a single entry instead of being processed twice.
            seen = {finder.translate_arg(p) for p in files}
            for df in finder.discover():
                if not df.target.is_file():
                    continue
                path = str(df.target)
                key = finder.translate_arg(path)
                if key in seen:
                    continue
                files.append(path)
                seen.add(key)

        source_repo, source_status = self._probe_source_repo(finder.source_dir)

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

                template_constructs, has_prompts = _detect_template_constructs(
                    dotfile.source
                )
                # Equality fast-path: only meaningful for templated sources
                # (a non-templated source can't reduce to anything other
                # than itself, and filecmp above already covered that
                # case).  Skip it when prompt directives are present so
                # the preprocessor never blocks waiting for stdin.
                if template_constructs and not has_prompts:
                    if applier.is_target_up_to_date(dotfile):
                        log.info(
                            "Already tracked (identical after preprocessing): %s",
                            dotfile.translated,
                        )
                        continue

                if template_constructs and not overwrite_template:
                    log.error(
                        "Refusing to overwrite templated source file: %s "
                        "(contains %s; use --overwrite-template to override)",
                        dotfile.rel_path,
                        ", ".join(template_constructs),
                    )
                    errors += 1
                    continue

                if self._source_is_clean_in_git(
                    dotfile.source, source_repo, source_status
                ):
                    log.info("Updating tracked file: %s", dotfile.rel_path)
                elif not force:
                    if source_repo is None:
                        log.error(
                            "Refusing to overwrite existing file in non-git "
                            "dotfiles repository: %s "
                            "(use -f/--force to override)",
                            dotfile.rel_path,
                        )
                    else:
                        log.error(
                            "Refusing to overwrite dirty file in dotfiles "
                            "repository: %s (use -f/--force to override)",
                            dotfile.rel_path,
                        )
                    errors += 1
                    continue
                else:
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

    @staticmethod
    def _probe_source_repo(source_dir: Path):
        """Resolve the git repo enclosing *source_dir* and snapshot its status.

        Returns ``(repo, status)`` where ``repo`` is a :class:`GitRepo` or
        ``None`` (when *source_dir* is not inside any git working tree),
        and ``status`` is the result of :meth:`GitRepo.status_porcelain`
        — a ``{rel_path: XY_code}`` dict. The status is collected once up
        front so the per-file dirty check does not re-shell out to git.

        ``include_ignored=True`` is required because ishproject worktrees
        share their parent repo's ``.git/info/exclude``, which carries
        ``/.ishlib/`` and any per-file dotfile patterns. Without it,
        managed-but-not-tracked files would be invisible in the snapshot
        and the dirty check would misclassify them as clean.
        """
        try:
            repo = GitRepo.discover(source_dir)
        except NotAGitRepoError:
            return None, {}
        return repo, repo.status_porcelain(include_ignored=True)

    @staticmethod
    def _source_is_clean_in_git(source_path: Path, repo, status: dict) -> bool:
        """Return True iff *source_path* is tracked and clean in *repo*.

        "Clean" means: the path lives inside the work tree and does not
        appear in ``git status --porcelain`` output, i.e. it has no
        uncommitted modifications, no staged changes, and is not
        untracked. Returns False when there is no enclosing repo, when
        the path resolves outside the work tree, or when git reports
        any status code for it.
        """
        if repo is None:
            return False
        try:
            rel = source_path.resolve().relative_to(repo.work_tree)
        except ValueError:
            return False
        # ``status_porcelain`` returns POSIX-style paths from git; on
        # Windows ``str(rel)`` would use backslashes and miss every key.
        return rel.as_posix() not in status
