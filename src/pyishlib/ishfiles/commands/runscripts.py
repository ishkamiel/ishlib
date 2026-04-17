# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``runscripts`` subcommand -- execute scripts from the ishscripts folder."""

from __future__ import annotations

import argparse
import logging

from ...ish_config import IshConfig
from ..script_logger import ScriptLogger
from ..script_runner import run_scripts
from ..script_state import ScriptState

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``runscripts`` subcommand."""
    parser = subparsers.add_parser(
        "runscripts",
        help="Run scripts from the ishscripts folder",
    )
    parser.add_argument(
        "scripts",
        nargs="*",
        default=None,
        help="Restrict to specific script names (default: all)",
    )
    parser.add_argument(
        "--force",
        nargs="*",
        metavar="SCRIPT",
        default=None,
        dest="force_scripts",
        help=(
            "Ignore run_when state for named scripts and re-run them. "
            "With no arguments, force-runs all scripts."
        ),
    )
    parser.set_defaults(func=run)


def run(cfg: IshConfig) -> int:
    """Execute the runscripts command.

    Returns:
        0 on success, 1 on error.
    """
    scripts = cfg.get_opt("scripts") or None
    force_scripts = cfg.get_opt("force_scripts")  # None = respect state

    with ScriptLogger(cfg) as slog:
        state = ScriptState.from_cfg(cfg)
        ret = run_scripts(
            cfg,
            scripts=scripts,
            script_logger=slog,
            script_state=state,
            force_scripts=force_scripts,
        )
        summary = slog.summary_line()
        if slog.log_path:
            log.info("Scripts done: %s. Log: %s", summary, slog.log_path)
        else:
            log.info("Scripts done: %s.", summary)

    return ret
