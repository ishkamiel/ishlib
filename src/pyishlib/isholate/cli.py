#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Command-line interface for isholate.

Entry point for the ``isholate`` tool.  Launches an Incus container with
the host user mirrored and optional bind mounts.  Uses a three-tier
persistent-base caching model to avoid re-running apt and ishfiles on every
invocation.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import List, Optional

from ..environment import is_linux
from ..ish_logging import setup_logging
from .config import (
    discover_host_ishfiles_source,
    discover_project_overlay,
    load_project_config,
)
from .container import (
    _check_incus_available,
    _preflight_claude_host_tools,
    get_host_user_info,
    launch_and_exec,
    purge_containers,
)

DEFAULT_IMAGE = "images:ubuntu/24.04"
DEFAULT_SHELL = "/bin/bash"

log = logging.getLogger(__name__)


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

    _claude_group = parser.add_mutually_exclusive_group()
    _claude_group.add_argument(
        "--claude",
        action="store_true",
        default=False,
        help=(
            "Expose the host's Claude session (~/.claude/ and ~/.claude.json) "
            "read-write so the in-container Claude CLI shares live state "
            "(sessions, projects) with the host. For credentials-only access "
            "use --claude-base."
        ),
    )
    _claude_group.add_argument(
        "--claude-base",
        action="store_true",
        default=False,
        help=(
            "Expose only ~/.claude/.credentials.json so the container can "
            "authenticate to the Claude API without sharing the host's full "
            "session state. Mutually exclusive with --claude."
        ),
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        default=False,
        help=(
            "Block all network traffic from the ephemeral container (applied "
            "after provisioning, so apt and ishfiles still run). Without "
            "--claude or --claude-base, eth0 is detached entirely at the Incus "
            "layer. When combined with --claude or --claude-base, the "
            "container's eth0 is switched to a dedicated Incus managed network "
            "bridge (isholate-claude); the bridge's dnsmasq only resolves "
            "Claude API domains (anthropic.com, claude.ai, statsig.com, "
            "statsigapi.net, sentry.io — including all subdomains) and "
            "populates a host ipset on every lookup. A host iptables chain on "
            "the bridge's FORWARD traffic then allows TCP/443 only to IPs in "
            "that ipset, so a malicious process in the container cannot bypass "
            "DNS by hard-coding an IP. First use prompts once for sudo to "
            "install the ipset, iptables chain, and a systemd unit that "
            "restores them on boot; subsequent runs skip sudo entirely."
        ),
    )

    # --- ishfiles provisioning control ---
    parser.add_argument(
        "--project-root",
        metavar="PATH",
        default=None,
        help=(
            "Directory to treat as the project root when looking for "
            ".ishlib/ishfiles/ and .ishlib/isholate/config.toml. "
            "Defaults to the current working directory. The lookup is "
            "not recursive — only the given directory is checked."
        ),
    )

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
        help="Skip applying the project .ishlib/ishfiles/ source tree inside the container",
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
        "-r",
        "--run",
        nargs=argparse.REMAINDER,
        default=None,
        metavar="CMD",
        help=(
            "Run CMD inside the container and exit. If --run appears before "
            "any positional command tokens, everything after it is treated "
            "as the command and its arguments. If positional command parsing "
            "has already started, --run is treated as part of the command, "
            "so all isholate flags must appear before the command or before "
            "--run."
        ),
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help=(
            "Positional command to run inside the container (default: "
            "interactive shell). Prefer --run for unambiguous parsing."
        ),
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    # Set up logging early with a default level; re-configure after argparse.
    setup_logging(logging.WARNING)

    if not is_linux():
        log.critical("isholate is only supported on Linux")
        return 1

    _, home, cwd = get_host_user_info()

    # Build the parser first so we can do a pre-parse to extract
    # --project-root before loading project config (project config
    # influences argparse defaults, so it must be loaded before the full
    # parse_args call).
    parser = build_parser()

    # Pre-parse to extract --project-root only.  parse_known_args ignores
    # unknown tokens so positional/remainder arguments don't interfere.
    pre_args, _ = parser.parse_known_args(argv)

    if pre_args.project_root is not None:
        project_root_path = Path(pre_args.project_root).resolve()
        if not project_root_path.is_dir():
            log.error(
                "--project-root '%s' is not an existing directory",
                pre_args.project_root,
            )
            return 2
    else:
        project_root_path = cwd.resolve()

    # Discover the project overlay (if any) before the full parse so that
    # image/shell overrides from .ishlib/isholate/config.toml can be
    # applied as argparse defaults (CLI flags still take precedence).
    # The isholate config and the ishfiles overlay are independent — either
    # may be present without the other.
    project_cfg = load_project_config(project_root_path)
    overlay_dir = discover_project_overlay(project_root_path)

    if project_cfg.get("image"):
        parser.set_defaults(image=project_cfg["image"])
    if project_cfg.get("shell"):
        parser.set_defaults(shell=project_cfg["shell"])

    args = parser.parse_args(argv)

    # Reconfigure logging now that we know the user's verbosity preference.
    if args.verbose >= 2:
        setup_logging(logging.DEBUG, quiet=args.quiet)
    elif args.verbose >= 1:
        setup_logging(logging.INFO, quiet=args.quiet)
    else:
        setup_logging(logging.WARNING, quiet=args.quiet)

    # Run the incus preflight after argparse so that `--help` / `--version`
    # still work on hosts without a healthy incus setup (argparse exits
    # inside parse_args before we get here in those cases).
    incus_guidance = _check_incus_available()
    if incus_guidance is not None:
        log.error("%s", incus_guidance)
        return 1

    # Check host tool dependencies for --no-network --claude before creating
    # any container or Incus network state.  Without this, a missing 'ipset'
    # or 'iptables' package produces a raw Python traceback mid-run after
    # the ephemeral container and the isholate-claude bridge already exist.
    if args.no_network and args.claude:
        tools_msg = _preflight_claude_host_tools()
        if tools_msg is not None:
            log.error("%s", tools_msg)
            return 1

    # --run takes precedence over the positional command form: everything
    # after --run is the command to run inside the container.
    if args.run is not None:
        if not args.run:
            log.error("--run requires a command to execute")
            return 2
        if args.command:
            log.error(
                "--run cannot be combined with a positional command; "
                "put all command arguments after --run"
            )
            return 2
        args.command = list(args.run)

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
            log.warning("host ishfiles source not found; skipping pass 1")

    resolved_overlay: Optional[Path] = None
    project_root: Optional[Path] = None
    if not args.no_project_ishfiles and overlay_dir is not None:
        resolved_overlay = overlay_dir
        # Project root is the directory that contains the .ishlib/ umbrella
        # — used for stable project-base container naming (independent of
        # the overlay's path within .ishlib/ and of the invocation cwd).
        project_root = project_root_path

    return launch_and_exec(
        args,
        host_ishfiles_source=host_source,
        project_overlay=resolved_overlay,
        project_root=project_root,
    )
