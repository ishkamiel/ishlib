# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject apply`` -- forward to ``ishfiles apply`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable, List

from ...cli_command import CliCommand
from ...cli_passthrough import passthrough_to_cli
from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ishfiles.applier import make_applier, make_finder
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ...ishfiles.config import load_config as ishfiles_load_config
from ...ishlib_folder import PROJECT_DIR_NAME
from ..config import IshprojectConfig

log = logging.getLogger(__name__)


def _compose_ishfiles_argv(
    source: Path, target: Path, rest: Iterable[str]
) -> List[str]:
    """Compose the exact argv ``passthrough_to_cli`` will hand to ishfiles.

    Passes a capture callback as *main_fn* so we get the composed argv
    without running anything. Keeping this in one place ensures the
    pre-scan parses the same flags the real passthrough will execute.
    """
    captured: List[List[str]] = []

    def _capture(argv: List[str]) -> int:
        captured.append(argv)
        return 0

    passthrough_to_cli(
        _capture,
        subcommand="apply",
        remainder=rest,
        global_args=["--source", str(source), "--target", str(target)],
        target_parser=ishfiles_build_parser(),
    )
    return captured[0]


def _update_project_excludes(source: Path, target: Path, rest: Iterable[str]) -> None:
    """Register the soon-to-be-applied dotfiles in the project repo's exclude.

    Parses the composed ishfiles argv so ``--dry-run``, ``--home``,
    ``--config``, and any positional file restriction are honoured
    identically to the passthrough. Scans the resulting config with
    the same discovery ``ishfiles apply`` uses, then appends each
    target path to ``<target>/.git/info/exclude`` so applied files do
    not show up as untracked in ``git status``. Silent no-op when
    *target* is not inside a git work tree (e.g. an isholate
    container mount) or when argv parsing fails (the real passthrough
    will surface the same error).
    """
    try:
        repo = GitRepo.discover(target)
    except NotAGitRepoError:
        log.debug("target %s is not a git repo; skipping exclude updates", target)
        return

    argv = _compose_ishfiles_argv(source, target, rest)
    try:
        ishfiles_args = ishfiles_build_parser().parse_args(argv)
    except SystemExit:
        # Bad argv -- let the real passthrough report the error.
        return
    ish_cfg = ishfiles_load_config(args=ishfiles_args)

    repo.runner = CommandRunner(cfg=IshConfig(dry_run=ish_cfg.dry_run))
    repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")

    finder = make_finder(ish_cfg)
    applier = make_applier(ish_cfg, finder=finder)
    files = ish_cfg.get_opt("files") or None
    rel_files = finder.get_rel_paths(files) if files else None
    kept, _pkgs = applier.scan(applier.discover(files=rel_files))
    for df in kept:
        try:
            repo.ensure_path_excluded(df.target)
        except ValueError as exc:
            log.warning("could not exclude %s: %s", df.target, exc)


class ApplyCommand(CliCommand):
    """Apply project dotfiles to the project root."""

    NAME = "apply"
    HELP = "Apply project dotfiles from the active ishproject worktree"
    DESCRIPTION = (
        "Thin wrapper around `ishfiles apply` with --source and --target "
        "pointed at the current project. When the current branch has a "
        "`<prefix>/<current>/<postfix>` variant it is used; otherwise "
        "the default `<prefix>/<postfix>` worktree is used. All "
        "remaining arguments are forwarded to ishfiles. Before "
        "forwarding, each target path is appended to the project "
        "repo's .git/info/exclude so applied files do not appear as "
        "untracked."
    )
    ADD_COMMON_FLAGS = False

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles apply`.",
        )

    def run(self, args: argparse.Namespace) -> int:
        cfg: IshprojectConfig = args.ishproject_cfg
        root = Path.cwd()

        branch = cfg.resolve_active_branch(root)
        source, target = cfg.resolve_project_paths(root, branch=branch)
        if not source.is_dir():
            log.error(
                "Project dotfiles directory does not exist: %s "
                "(run `ishproject init` first)",
                source,
            )
            return 1

        _update_project_excludes(source, target, args.rest)

        return passthrough_to_cli(
            ishfiles_main,
            subcommand="apply",
            remainder=args.rest,
            global_args=["--source", str(source), "--target", str(target)],
            target_parser=ishfiles_build_parser(),
        )
