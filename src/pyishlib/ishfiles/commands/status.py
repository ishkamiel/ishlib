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
    """Return a display string for the deployed target path.

    Prefers a ``./<rel>`` form when the target is under cwd, then ``~/<rel>``
    when under ``$HOME``, and finally falls back to the absolute path.
    """
    try:
        rel_cwd = dotfile_target.resolve().relative_to(Path.cwd().resolve()).as_posix()
        return f"./{rel_cwd}" if rel_cwd and rel_cwd != "." else "."
    except (OSError, ValueError):
        pass
    try:
        rel_home = dotfile_target.relative_to(home)
        prefix = "~" if home == Path.home() else str(home)
        return f"{prefix}/{rel_home}"
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
        parser.add_argument(
            "--include-ignored",
            action="store_true",
            default=False,
            help=(
                "Also list git-ignored paths under 'Other source changes'. "
                "Used by `ishproject status` because the ishproject worktree "
                "tracks files that match the main repo's .git/info/exclude."
            ),
        )

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
            # Pass --ignored=traditional only when requested (e.g. by
            # `ishproject status`, which needs to surface dotfiles that
            # match .git/info/exclude in the shared ishproject worktree).
            include_ignored = self.cfg.get_opt("include_ignored", default=False)
            dirty_paths = repo.status_porcelain(include_ignored=include_ignored)
        except NotAGitRepoError:
            log.warning(
                "Source directory is not a git repository: %s", finder.source_dir
            )
            dirty_paths = {}

        home = finder.target_dir
        matched_paths: set = set()

        for dotfile in dotfiles:
            source_name = dotfile.rel_path.as_posix()
            source_dirty = source_name in dirty_paths
            target_changed = dotfile.get_change_type() is not None
            matched_paths.add(source_name)

            if not source_dirty and not target_changed:
                continue

            display = _display_target(dotfile.target, home)
            op = "!=" if target_changed else "=="
            suffix = " (source dirty)" if source_dirty else ""
            print(f"{display} {op} {source_name}{suffix}")

        other = {p: xy for p, xy in dirty_paths.items() if p not in matched_paths}
        if other:
            print("\nOther source changes:")
            for path, xy in sorted(other.items()):
                print(f"  {xy}  {path}")

        return 0
