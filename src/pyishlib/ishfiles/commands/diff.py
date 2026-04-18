# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``diff`` subcommand -- show what would change without applying."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from ...cli_command import CliCommand
from ...diff import print_diff, print_new_file, print_binary_diff
from ...dotfile import DotFile, ChangeType
from ...ish_config import IshConfig
from ...json_merge import canonical_json
from ..applier import make_applier, make_finder


def _show_diff(dotfile: DotFile) -> None:
    """Print a diff for a single dotfile using :mod:`pyishlib.diff`."""
    change = dotfile.get_change_type()

    if change == ChangeType.NEW:
        try:
            dotfile.effective_source.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            print_binary_diff("/dev/null", str(dotfile.target))
            return
        print_new_file(dotfile.effective_source, str(dotfile.target))
        return

    try:
        dotfile.target.read_bytes().decode("utf-8")
        dotfile.effective_source.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        print_binary_diff(str(dotfile.target), str(dotfile.effective_source))
        return

    if dotfile.mergejson:
        try:
            target_data = json.loads(dotfile.target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            target_data = None
        if target_data is not None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                delete=False,
            ) as tmp:
                tmp.write(canonical_json(target_data))
                tmp_path = Path(tmp.name)
            try:
                print_diff(
                    tmp_path,
                    dotfile.effective_source,
                    old_label=str(dotfile.target),
                    new_label=str(dotfile.effective_source),
                    force_python=True,
                )
            finally:
                tmp_path.unlink(missing_ok=True)
            return

    print_diff(
        dotfile.target,
        dotfile.effective_source,
        old_label=str(dotfile.target),
        new_label=str(dotfile.effective_source),
    )


class DiffCommand(CliCommand):
    """Show a unified diff of what would change."""

    NAME = "diff"
    HELP = "Show a unified diff of what would change"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "files",
            nargs="*",
            default=None,
            help="Restrict to specific files (source or target paths)",
        )
        parser.add_argument(
            "--name-only",
            action="store_true",
            default=False,
            help="Show only the names of changed files, not the diff",
        )

    def run(self, cfg: IshConfig) -> int:
        finder = make_finder(cfg)
        applier = make_applier(cfg, finder=finder)

        files = cfg.get_opt("files") or None
        rel_files = finder.get_rel_paths(files) if files else None

        dotfiles = applier.discover(files=rel_files)
        if not dotfiles:
            if not cfg.quiet:
                print("No dotfiles found.")
            return 0

        dotfiles = applier.prepare(dotfiles)
        changes = applier.get_changes(dotfiles)

        if not changes:
            if not cfg.quiet:
                print("Everything is up to date.")
            return 0

        name_only = cfg.get_opt("name_only", default=False)
        for dotfile in changes:
            if name_only:
                print(dotfile.target)
            else:
                _show_diff(dotfile)

        return 1
