#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for isholate.

Entry point for the ``isholate`` tool.  Launches an ephemeral Incus
container with the host user mirrored and optional bind mounts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from ..environment import is_linux
from .config import (
    discover_host_ishfiles_source,
    discover_project_overlay,
    load_project_config,
)
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
        "--no-host-ishfiles",
        action="store_true",
        default=False,
        help="Skip applying the host user's ishfiles inside the container",
    )
    parser.add_argument(
        "--no-project-overlay",
        action="store_true",
        default=False,
        help=("Skip applying the project .isholate/ overlay inside the container"),
    )

    parser.add_argument(
        "--purge",
        action="store_true",
        default=False,
        help="Delete all isholate containers belonging to the current user",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "Show output from apt and ishfiles during provisioning. "
            "Repeat (-vv) to enable ishfiles --debug."
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress isholate's own progress messages",
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
    if not is_linux():
        print("isholate: error: isholate is only supported on Linux", file=sys.stderr)
        return 1

    _, home, cwd = get_host_user_info()

    # Discover the project overlay (if any) before parsing args so that
    # image/shell overrides from .isholate/ishconfig/isholate.toml can be
    # applied as argparse defaults (CLI flags still take precedence).
    overlay_dir = discover_project_overlay(cwd)
    project_cfg = load_project_config(overlay_dir) if overlay_dir is not None else {}

    parser = build_parser()
    if project_cfg.get("image"):
        parser.set_defaults(image=project_cfg["image"])
    if project_cfg.get("shell"):
        parser.set_defaults(shell=project_cfg["shell"])

    args = parser.parse_args(argv)

    if args.purge:
        username, _, _ = get_host_user_info()
        return purge_containers(username, quiet=args.quiet)

    # Resolve provisioning sources (skip if the respective --no-* flag is set).
    host_source: Optional[Path] = None
    if not args.no_host_ishfiles:
        host_source = discover_host_ishfiles_source(home)
        if host_source is None:
            print(
                "isholate: host ishfiles source not found; skipping pass 1",
                file=sys.stderr,
            )

    resolved_overlay: Optional[Path] = None
    if not args.no_project_overlay and overlay_dir is not None:
        resolved_overlay = overlay_dir

    return launch_and_exec(
        args,
        host_ishfiles_source=host_source,
        project_overlay=resolved_overlay,
    )
