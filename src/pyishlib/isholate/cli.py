#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for isholate.

Entry point for the ``isholate`` tool.  Launches an Incus container with
the host user mirrored and optional bind mounts.  Uses a three-tier
persistent-base caching model to avoid re-running apt and ishfiles on every
invocation.
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
            "Persistent base containers cache expensive provisioning steps so "
            "subsequent runs start in seconds."
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
        help="Ephemeral container name (auto-generated if omitted)",
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

    # --- ishfiles provisioning control ---
    parser.add_argument(
        "--no-ishfiles",
        action="store_true",
        default=False,
        help="Skip all ishfiles provisioning (host dotfiles and project ishfiles)",
    )
    parser.add_argument(
        "--no-host-ishfiles",
        action="store_true",
        default=False,
        help="Skip applying the host user's ishfiles inside the container",
    )
    parser.add_argument(
        "--no-project-ishfiles",
        action="store_true",
        default=False,
        help="Skip applying the project .ishfiles/ source tree inside the container",
    )

    # --- Cache / rebuild control ---
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help=(
            "Skip persistent bases; provision a fresh container on every run "
            "(original one-shot behaviour, useful for debugging or CI)"
        ),
    )
    rebuild_group = parser.add_mutually_exclusive_group()
    rebuild_group.add_argument(
        "--rebuild",
        action="store_true",
        default=False,
        help="Force rebuild of both the host base and the project base",
    )
    rebuild_group.add_argument(
        "--rebuild-base",
        action="store_true",
        default=False,
        help="Force rebuild of the host-ishfiles base (implies --rebuild-project-base)",
    )
    rebuild_group.add_argument(
        "--rebuild-project-base",
        action="store_true",
        default=False,
        help="Force rebuild of the project-overlay base only",
    )

    # --- Purge control ---
    purge_group = parser.add_mutually_exclusive_group()
    purge_group.add_argument(
        "--purge",
        action="store_true",
        default=False,
        help=(
            "Delete ephemeral isholate containers belonging to the current user "
            "(persistent bases are preserved)"
        ),
    )
    purge_group.add_argument(
        "--purge-bases",
        action="store_true",
        default=False,
        help=(
            "Delete ephemeral containers AND persistent base containers "
            "(isholate-base-* and isholate-pbase-*)"
        ),
    )
    purge_group.add_argument(
        "--purge-all",
        action="store_true",
        default=False,
        help="Alias for --purge-bases (delete everything isholate created)",
    )

    # --- Verbosity ---
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
    # image/shell overrides from .ishfiles/ishconfig/isholate.toml can be
    # applied as argparse defaults (CLI flags still take precedence).
    overlay_dir = discover_project_overlay(cwd)
    project_cfg = load_project_config(overlay_dir) if overlay_dir is not None else {}

    parser = build_parser()
    if project_cfg.get("image"):
        parser.set_defaults(image=project_cfg["image"])
    if project_cfg.get("shell"):
        parser.set_defaults(shell=project_cfg["shell"])

    args = parser.parse_args(argv)

    # --- Purge handling ---
    include_bases = args.purge_bases or args.purge_all
    if args.purge or include_bases:
        username, _, _ = get_host_user_info()
        return purge_containers(username, quiet=args.quiet, include_bases=include_bases)

    # --no-ishfiles is a shorthand that implies both granular skip flags.
    if args.no_ishfiles:
        args.no_host_ishfiles = True
        args.no_project_ishfiles = True

    # --rebuild implies both rebuild flags.
    if args.rebuild:
        args.rebuild_base = True
        args.rebuild_project_base = True

    # --rebuild-base cascades to the project base.
    if args.rebuild_base:
        args.rebuild_project_base = True

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
    if not args.no_project_ishfiles and overlay_dir is not None:
        resolved_overlay = overlay_dir

    return launch_and_exec(
        args,
        host_ishfiles_source=host_source,
        project_overlay=resolved_overlay,
    )
