#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Command-line interface for isholate.

Entry point for the ``isholate`` tool.  Launches an ephemeral Incus
container with the host user mirrored and optional bind mounts.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .container import (
    get_host_user_info,
    launch_and_exec,
    purge_containers,
)

DEFAULT_IMAGE = "images:ubuntu/24.04"
DEFAULT_SHELL = "/bin/bash"


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for isholate."""
    parser = argparse.ArgumentParser(
        prog="isholate",
        description=(
            "Launch an isolated Incus container with the host user mirrored. "
            "The container is ephemeral and auto-deleted when it stops."
        ),
    )

    parser.add_argument(
        "--image",
        metavar="IMAGE",
        default=DEFAULT_IMAGE,
        help=f"Incus image to use (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--name",
        metavar="NAME",
        default=None,
        help="Container name (auto-generated if omitted)",
    )
    parser.add_argument(
        "--shell",
        metavar="SHELL",
        default=DEFAULT_SHELL,
        help=f"Shell to run when no command is given (default: {DEFAULT_SHELL})",
    )
    parser.add_argument(
        "--ro-home",
        action="store_true",
        default=False,
        help="Mount the host home directory read-only as the container home",
    )

    cwd_group = parser.add_mutually_exclusive_group()
    cwd_group.add_argument(
        "--rw-cwd",
        action="store_true",
        default=False,
        help="Mount the current working directory read-write into the container",
    )
    cwd_group.add_argument(
        "--ro-cwd",
        action="store_true",
        default=False,
        help="Mount the current working directory read-only into the container",
    )

    parser.add_argument(
        "--purge",
        action="store_true",
        default=False,
        help="Delete all isholate containers belonging to the current user",
    )

    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run inside the container (default: interactive shell)",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    if sys.platform != "linux":
        print("isholate: error: isholate is only supported on Linux", file=sys.stderr)
        return 1

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.purge:
        username, _, _ = get_host_user_info()
        return purge_containers(username)

    return launch_and_exec(args)
