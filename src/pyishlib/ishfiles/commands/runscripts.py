# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``runscripts`` subcommand -- execute scripts from the ishscripts folder."""

from __future__ import annotations

import argparse
import logging

from ...cli_command import CliCommand
from ...ish_config import IshConfig
from ..script_logger import ScriptLogger
from ..script_runner import run_scripts
from ..script_state import ScriptState

log = logging.getLogger(__name__)


class RunscriptsCommand(CliCommand):
    """Run scripts from the ishscripts folder."""

    NAME = "runscripts"
    HELP = "Run scripts from the ishscripts folder"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
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

    def run(self, cfg: IshConfig) -> int:
        scripts = cfg.get_opt("scripts") or None
        force_scripts = cfg.get_opt("force_scripts")

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
