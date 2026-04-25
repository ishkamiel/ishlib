# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ...ish_config import IshConfig
from ...launchers import install_all as _install_launchers_impl
from ...userio import prompt_yes_no_always
from ..applier import make_applier, make_finder
from ..default_shell import apply_default_shell_stage
from ..installer_helper import run_install
from ..script_logger import ScriptLogger
from ..script_runner import run_scanned_scripts, scan_scripts
from ..script_state import ScriptState
from .external import apply_externals_stage

log = logging.getLogger(__name__)


def _install_launchers(cfg: IshConfig) -> int:
    """Generate and install tool launcher scripts into ``~/.local/bin``.

    Delegates to :func:`pyishlib.launchers.install_all` with paths derived
    from *cfg*.  The source directory is ``<source>/ishlib/src``; the
    destination is ``<target>/.local/bin``.

    Returns 0 on success or when the source directory simply does not
    exist (a normal condition for project worktrees that don't bundle
    ishlib).  Returns 1 only when an actual write failure occurs.
    """
    source = Path(cfg.get_opt("source")).expanduser()
    target = Path(cfg.get_opt("target")).expanduser()
    source_dir = source / "ishlib" / "src"
    dest_dir = target / ".local" / "bin"
    if not source_dir.is_dir():
        log.info("Skipping launcher installation: %s does not exist", source_dir)
        return 0
    return _install_launchers_impl(
        dest_dir=dest_dir,
        source_dir=source_dir,
        dry_run=cfg.dry_run,
    )


def _print_log_summary(slog: ScriptLogger, cfg: IshConfig) -> None:
    """Log run summary and log path."""
    issues = slog.script_issues()
    if issues:
        for name, counts in issues:
            parts = [
                f"{counts[lvl]} {lvl}"
                for lvl in ("warning", "error", "critical")
                if counts.get(lvl)
            ]
            log.warning("Script issues — %s: %s", name, ", ".join(parts))
    summary = slog.summary_line()
    if slog.log_path:
        log.info("Scripts done: %s. Log: %s", summary, slog.log_path)
    else:
        log.info("Scripts done: %s.", summary)


class ApplyCommand(CliCommand):
    """Apply dotfiles from the ishfiles folder to the target directory."""

    NAME = "apply"
    HELP = "Apply dotfiles from the ishfiles folder to the target directory"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "files",
            nargs="*",
            default=None,
            help="Restrict to specific files (source or target paths)",
        )
        parser.add_argument(
            "--dotfiles-only",
            action="store_true",
            default=False,
            help="Skip package installation and scripts; apply dotfiles only",
        )
        parser.add_argument(
            "--skip-launchers",
            action="store_true",
            default=False,
            dest="skip_launchers",
            help="Skip Phase 0 (tool launcher installation in ~/.local/bin).",
        )
        parser.add_argument(
            "--force-scripts",
            nargs="*",
            metavar="SCRIPT",
            default=None,
            dest="force_scripts",
            help=(
                "Ignore run_when state for named scripts and re-run them. "
                "With no arguments, force-runs all scripts."
            ),
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            default=False,
            dest="yes",
            help="Skip confirmation prompts and apply all changes automatically",
        )
        parser.add_argument(
            "--isholate",
            action="store_true",
            default=False,
            help=argparse.SUPPRESS,
        )

    def run(self) -> int:
        """Execute the apply pipeline."""
        dotfiles_only = self.cfg.get_opt("dotfiles_only", default=False)
        force_scripts_arg = self.cfg.get_opt("force_scripts")
        force_scripts = force_scripts_arg

        had_errors = False
        if self.cfg.get_opt("skip_launchers", default=False):
            log.debug("Skipping Phase 0: launcher installation (--skip-launchers)")
        else:
            log.info("Phase 0: Installing tool launchers in ~/.local/bin")
            launcher_ret = _install_launchers(self.cfg)
            if launcher_ret != 0:
                log.warning("Some tool launchers could not be installed")
                had_errors = True

        finder = make_finder(self.cfg)
        applier = make_applier(self.cfg, finder=finder)

        files = self.cfg.get_opt("files") or None
        rel_files = finder.get_rel_paths(files) if files else None

        log.info("Phase 1: Scanning dotfiles and scripts for metadata")

        dotfiles = applier.discover(files=rel_files)
        dotfiles, dotfile_pkgs = applier.scan(dotfiles)

        if not dotfiles_only:
            script_paths, script_pkgs = scan_scripts(self.cfg)
        else:
            script_paths, script_pkgs = [], []

        extra_packages = dotfile_pkgs + script_pkgs
        if extra_packages:
            log.info("Collected %d package(s) from file metadata", len(extra_packages))

        if not dotfiles_only:
            ret = run_install(self.cfg, extra_packages=extra_packages)
            if ret != 0:
                return ret

        dotfiles = applier.prepare(dotfiles)
        changes = applier.get_changes(dotfiles)
        applier.print_changes(changes)

        if changes:
            if not self.cfg.dry_run:
                yes = self.cfg.get_opt("yes", default=False)
                if not yes:
                    choice = prompt_yes_no_always(f"Apply {len(changes)} change(s)?")
                    if choice.no:
                        log.info("Aborted.")
                        return 0

            applied = applier.apply_changes(changes)
            if applied:
                log.info("Applied %d file(s).", applied)

        if not dotfiles_only:
            log.info("Phase 4b: Applying externals")
            ext_ret = apply_externals_stage(self.cfg)
            if ext_ret != 0:
                log.warning("Some externals failed to fetch; continuing with scripts")
                had_errors = True

        if not dotfiles_only and script_paths:
            with ScriptLogger(self.cfg) as slog:
                state = ScriptState.from_cfg(self.cfg)
                ret = run_scanned_scripts(
                    self.cfg,
                    script_paths,
                    script_logger=slog,
                    script_state=state,
                    force_scripts=force_scripts,
                )
                _print_log_summary(slog, self.cfg)
            if ret != 0:
                return ret

        if not dotfiles_only:
            log.info("Phase 6: Setting default login shell")
            sh_ret = apply_default_shell_stage(self.cfg)
            if sh_ret != 0:
                had_errors = True

        if had_errors:
            log.warning("Apply completed with errors.")
        else:
            log.info("Apply complete.")
        return 1 if had_errors else 0
