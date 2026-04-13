#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""The ``external`` subcommand -- manage external git-repo dotfiles.

Subcommands:

- ``external apply [paths...] [--force]`` -- fetch (if stale) and copy
  externals into the target home directory.
- ``external update [paths...] [-y] [--include-prereleases]`` -- check
  remote repositories for newer tagged releases and prompt to update pins.
- ``external list`` -- show pinned revisions and cache status.

The ``apply_externals_stage`` helper is shared with
:func:`~pyishlib.ishfiles.commands.apply.run` which calls it as Phase 4b
of the main apply pipeline.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Optional, Sequence

from ...command_runner import CommandRunner
from ...ish_config import IshConfig
from ...userio import prompt_yes_no_always
from ..externals_config import ExternalSpec, load_externals
from ..externals_state import ExternalsState
from ..externals import ExternalsEngine

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``external`` subcommand with nested sub-subcommands."""
    p = subparsers.add_parser(
        "external",
        help="Manage external git-repo dotfiles",
    )
    sub = p.add_subparsers(dest="external_cmd", required=True)

    # -- apply -----------------------------------------------------------------
    pa = sub.add_parser(
        "apply",
        help="Fetch (if stale) and copy externals into the target home directory",
    )
    pa.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Restrict to specific externals (relative target paths, e.g. .fzf)",
    )
    pa.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-fetch from the remote even if the cached revision is still fresh",
    )
    pa.set_defaults(func=run_apply)

    # -- update ----------------------------------------------------------------
    pu = sub.add_parser(
        "update",
        help="Check remote repositories for newer tagged releases",
    )
    pu.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Restrict to specific externals",
    )
    pu.add_argument(
        "-y",
        "--yes",
        action="store_true",
        default=False,
        dest="update_yes",
        help="Accept all updates without prompting",
    )
    pu.add_argument(
        "--include-prereleases",
        action="store_true",
        default=False,
        dest="include_prereleases",
        help="Consider pre-release tags (rc, alpha, beta …) when checking for updates",
    )
    pu.set_defaults(func=run_update)

    # -- list ------------------------------------------------------------------
    pl = sub.add_parser(
        "list",
        help="Show pinned revisions and cache status",
    )
    pl.set_defaults(func=run_list)

    p.set_defaults(func=_dispatch)


def _dispatch(cfg: IshConfig) -> int:
    """Fallback: print help when no sub-subcommand is given."""
    print("Usage: ishfiles external <apply|update|list>")
    return 2


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def run_apply(cfg: IshConfig) -> int:
    """Execute ``external apply``."""
    paths = cfg.get_opt("paths") or []
    force = cfg.get_opt("force") or False
    return apply_externals_stage(cfg, paths=paths or None, force=force)


def run_update(cfg: IshConfig) -> int:
    """Execute ``external update``."""
    paths = cfg.get_opt("paths") or []
    auto_yes = cfg.get_opt("update_yes") or False
    include_pre = cfg.get_opt("include_prereleases") or False

    specs = load_externals(cfg)
    if not specs:
        print("No externals configured.")
        return 0

    if paths:
        specs = [s for s in specs if s.path in paths]

    runner = CommandRunner(cfg=cfg)
    state = ExternalsState.from_cfg(cfg)
    engine = ExternalsEngine(cfg, runner, state)

    source = Path(cfg.get_opt("source") or "").expanduser().resolve()
    config_dir = cfg.get_opt("config_dir")
    config_file = cfg.get_opt("externals_config_file")
    config_path = source / config_dir / config_file

    updated = 0
    for spec in specs:
        candidate = engine.check_update(spec, include_prereleases=include_pre)
        if candidate is None:
            print(f"  {spec.path}: already at latest ({spec.revision})")
            continue

        print(
            f"  {spec.path}: {candidate.current_rev} → {candidate.latest_tag} available"
        )

        if auto_yes:
            do_update = True
        else:
            choice = prompt_yes_no_always(
                f"Update {spec.path} to {candidate.latest_tag}?"
            )
            do_update = choice.yes or choice.always

        if do_update:
            engine.rewrite_revision(spec, candidate.latest_tag, config_path)
            # Re-fetch at the new revision.
            spec.revision = candidate.latest_tag
            try:
                engine.fetch(spec, force=True)
                print(f"  Updated {spec.path} to {candidate.latest_tag}")
                updated += 1
            except Exception as exc:  # noqa: BLE001
                log.error("Failed to fetch %s after update: %s", spec.path, exc)
        else:
            print(f"  Skipped {spec.path}")

    if updated:
        print(
            f"\n{updated} external(s) updated. "
            "Run 'ishfiles external apply' to copy into target."
        )
    return 0


def run_list(cfg: IshConfig) -> int:
    """Execute ``external list``."""
    specs = load_externals(cfg)
    if not specs:
        print("No externals configured.")
        return 0

    state = ExternalsState.from_cfg(cfg)
    cache_dir_base = (
        Path(cfg.get_opt("externals_cache_dir") or "").expanduser().resolve()
    )

    print(f"{'PATH':<30} {'PINNED':>12}  {'CACHED SHA':>12}  CACHE")
    print("-" * 70)
    for spec in specs:
        record = state.get(spec.path)
        cached_sha = record["commit_sha"][:12] if record else "(none)"
        cache_dir = cache_dir_base / spec.path.lstrip("/")
        cache_status = "ok" if cache_dir.exists() else "missing"
        print(
            f"  {spec.path:<28} {spec.revision:>12}  {cached_sha:>12}  {cache_status}"
        )
    return 0


# ---------------------------------------------------------------------------
# Shared pipeline helper
# ---------------------------------------------------------------------------


def apply_externals_stage(
    cfg: IshConfig,
    paths: Optional[Sequence[str]] = None,
    force: bool = False,
) -> int:
    """Fetch and apply all (or selected) externals, then seed ``cfg.context``.

    Called both by :func:`run_apply` and by Phase 4b of
    :func:`~pyishlib.ishfiles.commands.apply.run`.

    Fetch errors are logged and the external is skipped; file-copy errors
    are logged but the apply continues.  Returns 1 if any external failed
    to fetch; 0 otherwise.

    Args:
        cfg:   :class:`~pyishlib.ish_config.IshConfig` instance.
        paths: Restrict to externals whose ``path`` is in this sequence.
               ``None`` means apply all.
        force: When ``True``, bypass the refresh-period check.

    Returns:
        0 on success (or nothing to do), 1 if any external failed.
    """
    specs = load_externals(cfg)
    if not specs:
        return 0

    if paths:
        specs = [s for s in specs if s.path in paths]
        if not specs:
            log.warning("No externals matched the given paths: %s", list(paths))
            return 0

    runner = CommandRunner(cfg=cfg)
    state = ExternalsState.from_cfg(cfg)
    engine = ExternalsEngine(cfg, runner, state)

    target_root = Path(cfg.get_opt("target") or Path.home()).expanduser().resolve()
    had_error = False

    for spec in specs:
        log.info("Processing external: %s", spec.path)

        # Fetch -----------------------------------------------------------
        try:
            fetch_result = engine.fetch(spec, force=force)
        except Exception as exc:  # noqa: BLE001
            log.error("Failed to fetch external %s: %s", spec.path, exc)
            had_error = True
            _seed_context(cfg, spec, "")
            continue

        # Apply -----------------------------------------------------------
        try:
            apply_result = engine.apply(spec, target_root)
            log.info(
                "Applied %s: %d copied, %d skipped",
                spec.path,
                apply_result.copied,
                apply_result.skipped,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to apply external %s: %s", spec.path, exc)

        # Seed context ---------------------------------------------------
        _seed_context(cfg, spec, fetch_result.commit_sha)

    return 1 if had_error else 0


def _seed_context(cfg: IshConfig, spec: ExternalSpec, commit_sha: str) -> None:
    """Write ``ext_<safe>_revision`` and ``ext_<safe>_commit_sha`` into context.

    Scripts referencing ``${__ish_ext_fzf_revision}`` get a different
    preprocessed body when the revision changes, so :class:`ScriptState`
    naturally re-runs them on bump.

    Args:
        cfg:        Config object owning ``context``.
        spec:       External spec (``path`` and ``revision``).
        commit_sha: Resolved commit SHA (may be empty on dry-run or error).
    """
    safe = re.sub(r"[^a-zA-Z0-9]", "_", spec.path).strip("_")
    cfg.context.set(f"ext_{safe}_revision", spec.revision)
    cfg.context.set(f"ext_{safe}_commit_sha", commit_sha)
