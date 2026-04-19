# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...launchers import install_all as _install_launchers_impl
from ...userio import prompt_yes_no_always
from ...ish_config import IshConfig
from ..applier import make_applier, make_finder
from ..default_shell import apply_default_shell_stage
from ..installer_helper import run_install
from ..script_logger import ScriptLogger
from ..script_runner import run_scanned_scripts, scan_scripts
from ..script_state import ScriptState
from .external import apply_externals_stage

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``apply`` subcommand."""
    parser = subparsers.add_parser(
        "apply",
        help="Apply dotfiles from the ishfiles folder to the target directory",
    )
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
        help=argparse.SUPPRESS,  # internal: used by isholate when provisioning
    )
    parser.set_defaults(func=run)


def _install_launchers(cfg: IshConfig) -> int:
    """Generate and install tool launcher scripts into ``~/.local/bin``.

    Delegates to :func:`pyishlib.launchers.install_all` with paths derived
    from *cfg*.  The source directory is ``<source>/ishlib/src``; the
    destination is ``<target>/.local/bin``.

    Returns 0 on success, 1 if any launcher could not be written.
    """
    source = Path(cfg.get_opt("source")).expanduser().resolve()
    target = Path(cfg.get_opt("target")).expanduser().resolve()
    source_dir = source / "ishlib" / "src"
    dest_dir = target / ".local" / "bin"
    return _install_launchers_impl(
        dest_dir=dest_dir,
        source_dir=source_dir,
        dry_run=cfg.dry_run,
    )


def run(cfg: IshConfig) -> int:
    """Execute the apply command.

    The pipeline runs in the following phases:

    0. **Launchers** -- generate tool launcher scripts into ``~/.local/bin``
       so all registered ishlib tools are on the user's PATH.
    1. **Scan** -- discover dotfiles and scripts, read metadata, apply
       OS/tag filtering, and collect embedded package declarations.
    2. **Merge** -- combine metadata packages with the main package list.
    3. **Install** -- install all packages (main + metadata).
    4. **Apply** -- preprocess and install changed dotfiles.
    4b. **Externals** -- fetch and apply configured external git-repo
        dotfiles after the main dotfile apply and before scripts.
    5. **Scripts** -- execute scripts (with logging and run_when gating).
    6. **Default shell** -- set the login shell via ``chsh`` when
       ``default_shell`` is configured.

    Returns:
        0 on success, 1 on error.
    """
    dotfiles_only = cfg.get_opt("dotfiles_only", default=False)
    force_scripts_arg = cfg.get_opt("force_scripts")
    # None → not passed; [] → flag present with no args (force all)
    force_scripts = force_scripts_arg  # None means "respect state"

    # -- Phase 0: Launchers --------------------------------------------------
    # Best-effort: launcher failures are warnings only.  The most common
    # cause (ishlib/src/ missing because the submodule hasn't been
    # initialised yet) should not abort the rest of apply.
    log.info("Phase 0: Installing tool launchers in ~/.local/bin")
    _install_launchers(cfg)
    had_errors = False

    finder = make_finder(cfg)
    applier = make_applier(cfg, finder=finder)

    files = cfg.get_opt("files") or None
    rel_files = finder.get_rel_paths(files) if files else None

    # -- Phase 1: Scan -------------------------------------------------------
    log.info("Phase 1: Scanning dotfiles and scripts for metadata")

    dotfiles = applier.discover(files=rel_files)
    dotfiles, dotfile_pkgs = applier.scan(dotfiles)

    if not dotfiles_only:
        script_paths, script_pkgs = scan_scripts(cfg)
    else:
        script_paths, script_pkgs = [], []

    # -- Phase 2: Merge ------------------------------------------------------
    extra_packages = dotfile_pkgs + script_pkgs
    if extra_packages:
        log.info("Collected %d package(s) from file metadata", len(extra_packages))

    # -- Phase 3: Install ----------------------------------------------------
    if not dotfiles_only:
        ret = run_install(cfg, extra_packages=extra_packages)
        if ret != 0:
            return ret

    # -- Phase 4: Apply dotfiles ---------------------------------------------
    dotfiles = applier.prepare(dotfiles)
    changes = applier.get_changes(dotfiles)
    applier.print_changes(changes)

    if changes:
        if not cfg.dry_run:
            yes = cfg.get_opt("yes", default=False)
            if not yes:
                choice = prompt_yes_no_always(f"Apply {len(changes)} change(s)?")
                if choice.no:
                    log.info("Aborted.")
                    return 0

        applied = applier.apply_changes(changes)
        if applied:
            log.info("Applied %d file(s).", applied)

    # -- Phase 4b: Apply externals -------------------------------------------
    if not dotfiles_only:
        log.info("Phase 4b: Applying externals")
        ext_ret = apply_externals_stage(cfg)
        if ext_ret != 0:
            log.warning("Some externals failed to fetch; continuing with scripts")
            had_errors = True
    else:
        pass  # had_errors already set from Phase 0

    # -- Phase 5: Run scripts ------------------------------------------------
    if not dotfiles_only and script_paths:
        with ScriptLogger(cfg) as slog:
            state = ScriptState.from_cfg(cfg)
            ret = run_scanned_scripts(
                cfg,
                script_paths,
                script_logger=slog,
                script_state=state,
                force_scripts=force_scripts,
            )
            _print_log_summary(slog, cfg)
        if ret != 0:
            return ret

    # -- Phase 6: Set default login shell ------------------------------------
    if not dotfiles_only:
        log.info("Phase 6: Setting default login shell")
        sh_ret = apply_default_shell_stage(cfg)
        if sh_ret != 0:
            had_errors = True

    if had_errors:
        log.warning("Apply completed with errors.")
    else:
        log.info("Apply complete.")
    return 1 if had_errors else 0


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
