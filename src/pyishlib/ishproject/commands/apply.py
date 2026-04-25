# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject apply`` -- forward to ``ishfiles apply`` for the project."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable, Optional

from ...cli_command import CliCommand
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

    @staticmethod
    def TARGET_MAIN(argv):
        return ishfiles_main(argv)

    @staticmethod
    def TARGET_BUILD_PARSER():
        return ishfiles_build_parser()

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "rest",
            nargs=argparse.REMAINDER,
            help="Arguments forwarded to `ishfiles apply`.",
        )

    def run(self) -> int:
        return self.run_project_apply(self.cfg.ishproject_cfg, rest=self.cfg.rest)

    # ------------------------------------------------------------------
    # Shared entry point — also called from InitCommand --apply.
    # ------------------------------------------------------------------
    def run_project_apply(
        self,
        cfg: IshprojectConfig,
        *,
        rest: Iterable[str] = (),
        root: Optional[Path] = None,
        branch: Optional[str] = None,
    ) -> int:
        """Run the ishfiles apply pipeline for an ishproject worktree.

        Resolves ``(source, target)`` for the active branch, registers
        applied targets in the project repo's ``.git/info/exclude``,
        then forwards to ``ishfiles apply`` via :meth:`passthrough`.
        Returns 1 with a clear error when the worktree is missing;
        otherwise returns the ishfiles exit code.
        """
        resolved_root = root if root is not None else Path.cwd()
        resolved_branch = branch or cfg.resolve_active_branch(resolved_root)
        source, target = cfg.resolve_project_paths(
            resolved_root, branch=resolved_branch
        )
        if not source.is_dir():
            log.error(
                "Project dotfiles directory does not exist: %s "
                "(run `ishproject init` first)",
                source,
            )
            return 1

        rest_list = list(rest)
        # Project worktrees never contain ishlib/src, so launcher install is
        # always meaningless here. Default-skip; leave as-is if the caller
        # already requested it explicitly.
        if "--skip-launchers" not in rest_list:
            rest_list.insert(0, "--skip-launchers")
        global_args = ["--source", str(source), "--target", str(target)]
        self._update_project_excludes(
            source, target, rest_list, global_args=global_args
        )

        return self.passthrough("apply", rest_list, global_args=global_args)

    # ------------------------------------------------------------------
    # Pre-scan helpers
    # ------------------------------------------------------------------
    def _update_project_excludes(
        self,
        source: Path,
        target: Path,
        rest: Iterable[str],
        *,
        global_args: Iterable[str],
    ) -> None:
        """Register soon-to-be-applied dotfiles in the project repo's exclude.

        Parses the composed ishfiles argv so ``--dry-run``, ``--home``,
        ``--config``, and any positional file restriction are honoured
        identically to the passthrough.  Scans the resulting config
        with the same discovery ``ishfiles apply`` uses, then appends
        each target path to ``<target>/.git/info/exclude`` so applied
        files do not show up as untracked in ``git status``.  Silent
        no-op when *target* is not inside a git work tree (e.g. an
        isholate container mount) or when argv parsing fails (the real
        passthrough will surface the same error).
        """
        try:
            repo = GitRepo.discover(target)
        except NotAGitRepoError:
            log.debug("target %s is not a git repo; skipping exclude updates", target)
            return

        argv = self.compose_passthrough_argv("apply", rest, global_args=global_args)
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
