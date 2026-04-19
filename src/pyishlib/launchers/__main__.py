# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``python -m pyishlib.launchers`` — install ishlib tool launchers."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import install_all
from ..ish_logging import setup_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pyishlib.launchers",
        description="Generate and install ishlib tool launcher scripts.",
    )
    subparsers = parser.add_subparsers(
        dest="subcommand", required=True, metavar="COMMAND"
    )

    install = subparsers.add_parser(
        "install",
        help="Install launcher scripts into a destination directory.",
        description=(
            "Generate self-contained bash launcher scripts for all "
            "registered ishlib tools and write them into DEST."
        ),
    )
    install.add_argument(
        "--dest",
        default=str(Path.home() / ".local" / "bin"),
        metavar="DIR",
        help="Destination directory (default: ~/.local/bin)",
    )
    install.add_argument(
        "--source",
        default=None,
        metavar="DIR",
        help=(
            "Path to the pyishlib src/ directory. "
            "Baked into each launcher as ISHLIB_SRC. "
            "Defaults to the src/ sibling of this package."
        ),
    )
    install.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be installed without writing files.",
    )
    install.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v=info, -vv=debug).",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    level = (
        logging.DEBUG
        if args.verbose >= 2
        else logging.INFO
        if args.verbose
        else logging.WARNING
    )
    setup_logging(level, log_file=None, quiet=False)

    if args.subcommand == "install":
        dest_dir = Path(args.dest).expanduser().resolve()

        if args.source:
            source_dir = Path(args.source).expanduser().resolve()
        else:
            # Default: src/ two levels above this package's directory.
            source_dir = Path(__file__).resolve().parent.parent.parent

        return install_all(
            dest_dir=dest_dir, source_dir=source_dir, dry_run=args.dry_run
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
