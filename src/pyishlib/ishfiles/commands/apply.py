#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``apply`` subcommand -- install dotfiles into the target directory."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from ...userio import prompt_yes_no_always
from ...ish_config import IshConfig
from ..applier import make_applier, make_finder
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


_SELF_LINK_NAMES = ["ishfiles", "isholate"]


def _same_file(a: Path, b: Path) -> bool:
    """Return True if *a* and *b* refer to the same filesystem object."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _install_self_links(cfg: IshConfig) -> int:
    """Create ``~/.local/bin`` symlinks for ``ishfiles`` and ``isholate``.

    Links ``{target}/.local/bin/{name}`` → ``{source}/ishlib/bin/{name}``
    for each tool.  Existing correct symlinks are silently skipped.
    Stale symlinks (wrong target) are replaced.  Regular files at the
    destination are left untouched with a warning.

    Returns 0 on success, 1 if any link could not be created.
    """
    source = Path(cfg.get_opt("source")).expanduser().resolve()
    target = Path(cfg.get_opt("target")).expanduser().resolve()
    bin_src = source / "ishlib" / "bin"
    bin_dst = target / ".local" / "bin"

    had_error = False

    for name in _SELF_LINK_NAMES:
        src = bin_src / name
        dst = bin_dst / name

        if not src.exists():
            log.warning("Self-link: source not found, skipping: %s", src)
            had_error = True
            continue

        try:
            if dst.is_symlink():
                if _same_file(dst, src):
                    log.debug("Self-link already correct: %s", dst)
                    continue
                # Stale symlink — replace it
                if cfg.dry_run:
                    print(f"ln -sf {src} {dst}")
                    continue
                dst.unlink()
            elif dst.exists():
                log.warning("Self-link: %s exists as a regular file; skipping", dst)
                had_error = True
                continue
            else:
                if cfg.dry_run:
                    print(f"ln -s {src} {dst}")
                    continue

            bin_dst.mkdir(parents=True, exist_ok=True)
            os.symlink(src, dst)
            if not cfg.quiet:
                print(f"Linked: {dst} -> {src}")
        except OSError as exc:
            log.warning("Self-link: failed to link %s: %s", name, exc)
            had_error = True

    return 1 if had_error else 0


def run(cfg: IshConfig) -> int:
    """Execute the apply command.

    The pipeline runs in six phases:

    0. **Self-links** -- create ``~/.local/bin`` symlinks for ``ishfiles``
       and ``isholate`` so the tools are on the user's PATH.
    1. **Scan** -- discover dotfiles and scripts, read metadata, apply
       OS/tag filtering, and collect embedded package declarations.
    2. **Merge** -- combine metadata packages with the main package list.
    3. **Install** -- install all packages (main + metadata).
    4. **Apply** -- preprocess and install changed dotfiles.
    5. **Scripts** -- execute scripts (with logging and run_when gating).

    Returns:
        0 on success, 1 on error.
    """
    dotfiles_only = cfg.get_opt("dotfiles_only", default=False)
    force_scripts_arg = cfg.get_opt("force_scripts")
    # None → not passed; [] → flag present with no args (force all)
    force_scripts = force_scripts_arg  # None means "respect state"

    # -- Phase 0: Self-links -------------------------------------------------
    # Best-effort: self-link failures are warnings only.  The most common
    # cause (ishlib/bin/ missing because the submodule hasn't been
    # initialised yet) should not abort the rest of apply.
    log.info("Phase 0: Installing self-links in ~/.local/bin")
    _install_self_links(cfg)
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
                    print("Aborted.")
                    return 0

        applied = applier.apply_changes(changes)
        if applied and not cfg.quiet:
            print(f"Applied {applied} file(s).")

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

    if not cfg.quiet:
        if had_errors:
            print("Apply completed with errors.")
        else:
            print("Apply complete.")
    return 1 if had_errors else 0


def _print_log_summary(slog: ScriptLogger, cfg: IshConfig) -> None:
    """Print run summary and log path (unless quiet)."""
    if cfg.quiet:
        return
    issues = slog.script_issues()
    if issues:
        for name, counts in issues:
            parts = [
                f"{counts[lvl]} {lvl}"
                for lvl in ("warn", "error", "fatal")
                if counts.get(lvl)
            ]
            print(f"  {name}: {', '.join(parts)}")
    if cfg.verbose or issues:
        summary = slog.summary_line()
        if slog.log_path:
            print(f"Scripts done: {summary}. Log: {slog.log_path}")
        else:
            print(f"Scripts done: {summary}.")
