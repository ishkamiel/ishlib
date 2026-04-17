# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``log`` subcommand -- view recent ishfiles run logs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ...ish_config import IshConfig

_LOG_DIR_SUFFIX = ".local/state/ishfiles/logs"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``log`` subcommand."""
    parser = subparsers.add_parser(
        "log",
        help="View recent ishfiles run logs",
    )
    parser.add_argument(
        "-n",
        metavar="N",
        type=int,
        default=1,
        dest="log_n",
        help="Show the Nth most recent log (default: 1 = most recent)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        default=False,
        dest="log_list",
        help="List available log files",
    )
    parser.add_argument(
        "--path",
        action="store_true",
        default=False,
        dest="log_path",
        help="Print the path to the most recent log",
    )
    parser.set_defaults(func=run)


def _log_dir(cfg: IshConfig) -> Path:
    target = Path(cfg.get_opt("target") or Path.home()).expanduser().resolve()
    return target / _LOG_DIR_SUFFIX


def _get_logs(cfg: IshConfig):
    """Return log files sorted newest-first."""
    log_dir = _log_dir(cfg)
    if not log_dir.is_dir():
        return []
    return sorted(
        log_dir.glob("run-*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def run(cfg: IshConfig) -> int:
    """Execute the log command.

    Returns:
        0 on success, 1 on error.
    """
    logs = _get_logs(cfg)

    list_mode = cfg.get_opt("log_list") or False
    path_mode = cfg.get_opt("log_path") or False
    n = cfg.get_opt("log_n") or 1

    if not logs:
        print("No run logs found.")
        return 0

    if list_mode:
        for i, lp in enumerate(logs, 1):
            print(f"  {i:2d}. {lp.name}")
        return 0

    if path_mode:
        print(logs[0])
        return 0

    idx = int(n) - 1
    if idx < 0 or idx >= len(logs):
        print(
            f"Only {len(logs)} log(s) available (requested #{n}).",
            file=sys.stderr,
        )
        return 1

    print(logs[idx].read_text(encoding="utf-8", errors="replace"), end="")
    return 0
