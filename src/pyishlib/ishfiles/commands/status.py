# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``status`` subcommand -- show dotfile and git status."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ...cli_command import CliCommand
from ...git_repo import GitRepo, NotAGitRepoError
from ..applier import make_applier, make_finder

log = logging.getLogger(__name__)


def _display_target(dotfile_target: Path, home: Path) -> str:
    """Return a display string for the deployed target path."""
    try:
        rel = dotfile_target.relative_to(home)
        prefix = "~" if home == Path.home() else str(home)
        return f"{prefix}/{rel}"
    except ValueError:
        return str(dotfile_target)


class StatusCommand(CliCommand):
    """Show dotfile and git status."""

    NAME = "status"
    HELP = "Show dotfile target/source status and git working-tree state"
    DESCRIPTION = (
        "For each dotfile, compares the deployed target file against the "
        "preprocessed source and shows whether they differ.  Also shows "
        "which source files are dirty in git.  Non-dotfile changes "
        "(ishscripts, ishconfig, untracked files, …) are listed separately."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self) -> int:
        finder = make_finder(self.cfg)

        if not finder.source_dir.is_dir():
            print(
                f"Source directory does not exist: {finder.source_dir}",
                file=sys.stderr,
            )
            return 1

        applier = make_applier(self.cfg, finder=finder)
        dotfiles = applier.discover()
        dotfiles = applier.prepare(dotfiles)

        try:
            repo = GitRepo.discover(finder.source_dir)
            # include_ignored: the dotfiles source is typically an
            # ishproject worktree where managed files may match the
            # shared .git/info/exclude (ishproject writes those
            # patterns so the main worktree stays clean). We still want
            # to see those files here — they are the user's new/edited
            # dotfiles, not something to silently hide.
            dirty_paths = repo.status_porcelain(include_ignored=True)
        except NotAGitRepoError:
            log.warning(
                "Source directory is not a git repository: %s", finder.source_dir
            )
            dirty_paths = {}

        home = finder.target_dir
        matched_paths: set = set()

        for dotfile in dotfiles:
            source_rel = dotfile.rel_path.as_posix()
            source_dirty = source_rel in dirty_paths
            target_changed = dotfile.get_change_type() is not None
            matched_paths.add(source_rel)

            if not source_dirty and not target_changed:
                continue

            display = _display_target(dotfile.target, home)
            source_name = dotfile.rel_path.as_posix()

            if source_dirty and target_changed:
                annotation = "(dirty)"
            elif target_changed:
                annotation = "(unchanged)"
            else:
                annotation = "(source dirty)"

            op = "!=" if target_changed else "=="
            print(f"{display} {op} {source_name} {annotation}")

        other = {p: xy for p, xy in dirty_paths.items() if p not in matched_paths}
        if other:
            print("\nOther source changes:")
            for path, xy in sorted(other.items()):
                print(f"  {xy}  {path}")

        return 0
