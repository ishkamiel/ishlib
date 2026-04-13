#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Script discovery and execution for the ``ishscripts`` folder.

Finds scripts in the scripts directory inside the ishfiles source folder,
preprocesses them through the ``@ish`` directive pipeline, and executes
them in sorted order.

Script naming convention
------------------------
Scripts are sorted lexically, so leading numeric prefixes control the
execution order::

    ishscripts/
        10_base.sh          # runs first
        50_optional.sh
        90_config.sh        # runs last

The ``__ISH__`` metadata block (TOML, extracted by
:func:`~pyishlib.ish_metadata.read_metadata`) may declare:

``run_when``
    ``"always"`` (default) -- run every time.
    ``"once"``              -- run only if no hash is recorded for this
                               script in the state file.
    ``"onchange"``          -- run only if the preprocessed content hash
                               differs from the recorded hash.

``tags``
    List of tag strings (same vocabulary as package tags).  If any tag
    fails to match the current context, the script is skipped.

``only_on`` / ``ignore_on``
    Existing OS-conditional keys (unchanged).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from ..command_runner import CommandRunner
from ..dotfile_script import DotfileScript
from ..file_preprocessor import FilePreprocessor
from ..ish_config import IshConfig
from ..ish_metadata import collect_metadata_packages, read_metadata
from ..environment import should_skip_for_os_from_metadata

if TYPE_CHECKING:
    from .script_logger import ScriptLogger
    from .script_state import ScriptState

log = logging.getLogger(__name__)


def find_scripts(cfg: IshConfig, source_dir: Path) -> List[Path]:
    """Return all script files in the scripts directory, sorted by name.

    Scripts are returned in lexical order so that numeric prefixes such as
    ``00_``, ``10_``, ``50_``, ``99_`` control execution order.

    All regular files are included; directories and hidden files
    (starting with ``.``) are skipped.  Files need not be executable
    as they are preprocessed and executed through the ``@ish`` pipeline.

    Args:
        cfg:        Resolved ishfiles configuration.
        source_dir: The root of the ishfiles source folder.
    """
    scripts_dir_name = cfg.get_opt("scripts_dir")
    scripts_dir = Path(source_dir) / scripts_dir_name
    if not scripts_dir.is_dir():
        log.debug("No scripts directory found: %s", scripts_dir)
        return []

    scripts = [
        p
        for p in sorted(scripts_dir.iterdir())
        if p.is_file() and not p.name.startswith(".")
    ]
    log.debug("Found %d script(s) in %s", len(scripts), scripts_dir)
    return scripts


def scan_scripts(
    cfg: IshConfig,
    scripts: Optional[Sequence[str]] = None,
    print_skipped: bool = False,
    all_scripts: Optional[List[Path]] = None,
) -> Tuple[List[Path], List[Dict[str, Any]]]:
    """Discover scripts, read metadata, and collect embedded packages.

    Performs OS filtering, tag filtering, and extracts any ``[packages]``
    sections from script metadata, without executing the scripts.

    Args:
        cfg:           Resolved ishfiles configuration.
        scripts:       Optional list of script names to include (default: all).
        print_skipped: When True, print a ``[skipped]`` line for each
                       excluded script.
        all_scripts:   Optional pre-discovered list of script paths to
                       filter (skips :func:`find_scripts`).

    Returns:
        A tuple of *(kept_scripts, packages)* where *kept_scripts* is the
        list of script paths that passed all filters, and *packages* is a
        list of package dicts collected from metadata.
    """
    if all_scripts is None:
        source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
        all_scripts = find_scripts(cfg, source_dir)

    if scripts:
        requested = set(scripts)
        all_scripts = [s for s in all_scripts if s.name in requested]

    kept: List[Path] = []
    packages: List[Dict[str, Any]] = []

    for script_path in all_scripts:
        try:
            meta = read_metadata(script_path)
        except (ValueError, ImportError):
            meta = None

        # -- OS filter --------------------------------------------------------
        if should_skip_for_os_from_metadata(meta):
            log.debug("Skipping %s (OS rules in metadata)", script_path.name)
            if print_skipped:
                print(f"  [skipped] {script_path.name} (OS rules)")
            continue

        # -- Tag filter -------------------------------------------------------
        tags = (meta or {}).get("tags", []) or []
        if tags and not _passes_tag_filter(tags, cfg):
            log.debug("Skipping %s (tag filter)", script_path.name)
            if print_skipped:
                print(f"  [skipped] {script_path.name} (tags)")
            continue

        packages.extend(collect_metadata_packages(meta, source=script_path.name))
        kept.append(script_path)

    return kept, packages


def run_scanned_scripts(
    cfg: IshConfig,
    script_paths: List[Path],
    script_logger: Optional["ScriptLogger"] = None,
    script_state: Optional["ScriptState"] = None,
    force_scripts: Optional[List[str]] = None,
) -> int:
    """Execute pre-scanned scripts (OS and tag filtering already applied).

    Use this after :func:`scan_scripts` has already performed discovery
    and filtering.

    Scripts are run in the order given (lexical by name from
    :func:`find_scripts`).  The ``run_when`` metadata key controls whether
    each script is skipped based on the :class:`~script_state.ScriptState`.

    If *script_logger* is set, the bash log helpers are injected into every
    shell script and all output is captured into the run log.  A ``fatal``
    message from any script sets the abort flag and prevents subsequent
    scripts from running.

    Args:
        cfg:            Resolved ishfiles configuration.
        script_paths:   Script paths from :func:`scan_scripts`.
        script_logger:  Optional :class:`~script_logger.ScriptLogger`.
        script_state:   Optional :class:`~script_state.ScriptState` for
                        ``run_once`` / ``run_onchange`` gating.
        force_scripts:  Script names whose state records should be ignored
                        (force a re-run regardless of ``run_when``).

    Returns:
        0 on success or when no scripts are found, 1 on error.
    """
    if not script_paths:
        return 0

    force_set = set(force_scripts or [])

    if not cfg.quiet:
        names = [s.name for s in script_paths]
        print(f"Scripts to run ({len(script_paths)}): {', '.join(names)}")

    # Expose the scripts directory as ${__ish_scripts_dir} so scripts can
    # locate sibling data files even when executed from a temp path.
    # set() is intentional: this is a system-computed path that must always
    # reflect the real ishscripts/ location; user-defined context values with
    # the same name should not override it.
    source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
    scripts_dir_path = source_dir / cfg.get_opt("scripts_dir")
    cfg.context.set("scripts_dir", str(scripts_dir_path))

    runner = CommandRunner(cfg=cfg)
    preprocessor = FilePreprocessor(variables=cfg.context.as_dict())

    for script_path in script_paths:
        # -- Abort check ------------------------------------------------------
        if script_logger is not None and script_logger.aborted:
            log.error("Aborting after fatal error; skipping %s", script_path.name)
            return 1

        # -- run_when gating --------------------------------------------------
        script = DotfileScript(
            path=script_path,
            preprocessor=preprocessor,
            runner=runner,
        )

        if script_state is not None and script_path.name not in force_set:
            run_when = _get_run_when(script_path)
            if run_when == "once":
                if script_state.seen(script_path.name):
                    log.debug(
                        "Skipping %s (run_when=once, already run)",
                        script_path.name,
                    )
                    if not cfg.quiet:
                        print(f"  [skip/once] {script_path.name}")
                    continue
            elif run_when == "onchange":
                try:
                    content = script.preprocess()
                except (FileNotFoundError, OSError) as exc:
                    log.error("Cannot preprocess %s: %s", script_path.name, exc)
                    return 1
                if not script_state.changed(script_path.name, content):
                    log.debug(
                        "Skipping %s (run_when=onchange, unchanged)",
                        script_path.name,
                    )
                    if not cfg.quiet:
                        print(f"  [skip/unchanged] {script_path.name}")
                    continue

        if cfg.dry_run:
            log.info("Would run script: %s", script_path.name)
            if not cfg.quiet:
                print(f"  [dry-run] {script_path.name}")
            continue

        # -- Execute ----------------------------------------------------------
        try:
            if not cfg.quiet:
                print(f"  Running: {script_path.name}")
            if script_logger is not None:
                script_logger.set_current_script(script_path.name)
            script.execute(script_logger=script_logger)
        except subprocess.CalledProcessError:
            log.error("Script failed: %s", script_path.name)
            return 1
        except FileNotFoundError:
            log.error("Script not found: %s", script_path)
            return 1

        # Record successful execution.
        if script_state is not None:
            try:
                content = script._preprocessed_text or script.preprocess()
                script_state.record(script_path.name, content)
            except OSError as exc:
                log.warning("Could not record state for %s: %s", script_path.name, exc)

    return 0


def run_scripts(
    cfg: IshConfig,
    scripts: Optional[Sequence[str]] = None,
    script_logger: Optional["ScriptLogger"] = None,
    script_state: Optional["ScriptState"] = None,
    force_scripts: Optional[List[str]] = None,
) -> int:
    """Discover and execute scripts from the scripts directory.

    Args:
        cfg:           Resolved ishfiles configuration.
        scripts:       Optional list of script names to run (default: all).
        script_logger: Optional :class:`~script_logger.ScriptLogger`.
        script_state:  Optional :class:`~script_state.ScriptState`.
        force_scripts: Names to force re-run ignoring ``run_when``.

    Returns:
        0 on success or when no scripts are found, 1 on error.
    """
    source_dir = Path(cfg.get_opt("source")).expanduser().resolve()
    scripts_dir_name = cfg.get_opt("scripts_dir")
    all_found = find_scripts(cfg, source_dir)

    if not all_found:
        log.info("No scripts found in %s/%s/", source_dir, scripts_dir_name)
        return 0

    if scripts:
        requested = set(scripts)
        unknown = requested - {s.name for s in all_found}
        if unknown:
            log.error("Unknown scripts: %s", ", ".join(sorted(unknown)))
            return 1

    kept, _ = scan_scripts(
        cfg, scripts=scripts, print_skipped=not cfg.quiet, all_scripts=all_found
    )
    return run_scanned_scripts(
        cfg,
        kept,
        script_logger=script_logger,
        script_state=script_state,
        force_scripts=force_scripts,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_run_when(script_path: Path) -> str:
    """Return the ``run_when`` value from a script's ``__ISH__`` metadata.

    Falls back to ``"always"`` when the key is absent or the metadata
    cannot be parsed.

    Args:
        script_path: Path to the script file.
    """
    try:
        meta = read_metadata(script_path)
    except (ValueError, ImportError, OSError):
        return "always"
    if meta is None:
        return "always"
    value = meta.get("run_when", "always")
    if value not in ("once", "onchange", "always"):
        log.warning(
            "Unknown run_when value %r in %s; defaulting to 'always'",
            value,
            script_path.name,
        )
        return "always"
    return value


def _passes_tag_filter(tags: List[str], cfg: IshConfig) -> bool:
    """Return True if all *tags* pass against the current context.

    Consults ``cfg.data_template`` for type information (bool, tags,
    ordered_tags).  Delegates to the shared
    :func:`~pyishlib.tag_filter.passes_tags` helper.

    Args:
        tags: List of tag strings from the script's ``__ISH__`` metadata.
        cfg:  Resolved ishfiles configuration.
    """
    from ..tag_filter import passes_tags

    return passes_tags(tags, cfg)
