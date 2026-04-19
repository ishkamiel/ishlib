# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``python -m pyishlib.launchers`` — install ishlib tool launchers."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import install_all
from ..ish_logging import log_level_from_args, setup_logging


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    """Attach the unified ishlib ``-v/--debug/-q/--log-file`` flags."""
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug output",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress non-essential output",
    )
    parser.add_argument(
        "--log-file",
        metavar="FILE",
        default=None,
        help=(
            "Append all log output (DEBUG and above) to this file, "
            "regardless of terminal verbosity."
        ),
    )


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
    _add_common_flags(install)
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    log_file = Path(args.log_file) if args.log_file else None
    setup_logging(log_level_from_args(args), log_file=log_file, quiet=args.quiet)

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
