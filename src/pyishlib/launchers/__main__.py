# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``python -m pyishlib.launchers`` — install ishlib tool launchers.

One-shot installer that writes launcher shims for every registered tool
into ``~/.local/bin``.  The only user-tunable surface is verbosity — the
destination (``~/.local/bin``) and baked-in source path (the ``src/``
dir containing this package) are auto-detected.  Programmatic callers
should call :func:`pyishlib.launchers.install_all` directly.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import install_all
from ..ish_logging import log_level_from_args, setup_logging

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pyishlib.launchers",
        description=(
            "Install launcher shims for all registered ishlib tools into "
            "~/.local/bin.  Source dir and destination are auto-detected."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Log the path of each installed launcher.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Log auto-detected paths and every up-to-date skip.",
    )
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    setup_logging(log_level_from_args(args))

    dest_dir = (Path.home() / ".local" / "bin").resolve()
    # Default: src/ two levels above this package's directory.
    source_dir = Path(__file__).resolve().parent.parent.parent

    if not source_dir.is_dir():
        log.error("ishlib source directory not found: %s", source_dir)
        return 1

    log.debug("installing launchers: source=%s dest=%s", source_dir, dest_dir)
    return install_all(dest_dir=dest_dir, source_dir=source_dir)


if __name__ == "__main__":
    raise SystemExit(main())
