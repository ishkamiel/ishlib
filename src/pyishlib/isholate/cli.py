# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Command-line interface for isholate.

Entry point for the ``isholate`` tool.  Exposes four subcommands:

* ``run``   — launch a container and exec a command (or interactive shell).
* ``purge`` — delete the user's isholate containers.
* ``list``  — print a table of isholate containers.
* ``stop``  — stop running isholate containers.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from ..container.incus import check_incus_available
from ..environment import is_linux
from ..ish_logging import setup_logging
from .claude import _preflight_claude_host_tools
from .config import (
    discover_host_ishfiles_source,
    discover_project_overlay,
    load_project_config,
    resolve_default_shell,
)
from .container import (
    get_host_user_info,
    launch_and_exec,
    list_containers,
    purge_containers,
    stop_containers,
)

DEFAULT_IMAGE = "images:ubuntu/24.04"
DEFAULT_SHELL = "/bin/bash"

log = logging.getLogger(__name__)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add ``-v/-q`` to *parser* in a consistent way.

    Attached to each subparser individually — NOT to the top-level parser,
    because argparse subparser namespace defaults silently overwrite
    top-level values.
    """
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


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    """Attach all ``run``-subcommand arguments to *parser*."""
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
            "Expose ~/.claude/.credentials.json and inject a synthetic "
            "~/.claude.json carrying the host's oauthAccount (and userID / "
            "firstStartTime when present), plus a hard-coded "
            "hasCompletedOnboarding, so Claude Code inside the container "
            "recognises the host credentials without sharing the host's full "
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

    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help=(
            "Command (and args) to run inside the container. Use `--` before "
            "the command if it contains flags that collide with isholate's. "
            "Default when omitted: interactive shell."
        ),
    )


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
    # -v/-q live on each subparser (not the top-level parser) because argparse
    # subparsers overwrite parent namespace values with their own defaults,
    # which would silently discard flags placed before the subcommand.

    sub = parser.add_subparsers(dest="subcommand", required=True, metavar="COMMAND")

    # --- run ---
    p_run = sub.add_parser(
        "run",
        help="Launch a container and run a command (or shell)",
        description=(
            "Launch an Incus container with the host user mirrored and run "
            "a command inside it.  When no command is given, an interactive "
            "shell is started."
        ),
    )
    _add_common_args(p_run)
    _add_run_args(p_run)

    # --- purge ---
    p_purge = sub.add_parser(
        "purge",
        help="Delete isholate containers for the current user",
        description=(
            "Delete isholate containers belonging to the current user.  "
            "By default only ephemeral containers are deleted; pass "
            "--bases (or --all) to also delete persistent base containers."
        ),
    )
    _add_common_args(p_purge)
    purge_group = p_purge.add_mutually_exclusive_group()
    purge_group.add_argument(
        "--bases",
        action="store_true",
        default=False,
        help=(
            "Also delete persistent base containers "
            "(isholate-base-* and isholate-pbase-*)"
        ),
    )
    purge_group.add_argument(
        "--all",
        action="store_true",
        default=False,
        dest="bases_alias",
        help="Alias of --bases (delete everything isholate created)",
    )

    # --- list ---
    p_list = sub.add_parser(
        "list",
        help="List isholate containers",
        description="Print a table of isholate containers (ephemerals and bases).",
    )
    _add_common_args(p_list)
    p_list.add_argument(
        "--running",
        action="store_true",
        default=False,
        help="Only show containers whose state is Running",
    )
    p_list.add_argument(
        "--all-users",
        action="store_true",
        default=False,
        help="Show containers for all users (adds a USER column)",
    )
    p_list.add_argument(
        "--no-bases",
        action="store_true",
        default=False,
        help="Hide persistent base containers (shown by default)",
    )

    # --- stop ---
    p_stop = sub.add_parser(
        "stop",
        help="Stop running isholate containers",
        description=(
            "Stop running isholate containers.  With no names, stops every "
            "running ephemeral belonging to the current user.  Pass --all to "
            "also stop running base containers."
        ),
    )
    _add_common_args(p_stop)
    p_stop.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help=(
            "Container name(s) to stop.  With no names, every running "
            "ephemeral belonging to the current user is stopped."
        ),
    )
    p_stop.add_argument(
        "--all",
        action="store_true",
        default=False,
        dest="include_bases",
        help=(
            "When no names are given, also stop running base containers "
            "(otherwise only ephemerals are stopped)"
        ),
    )

    return parser


def _configure_logging_from_args(args: argparse.Namespace) -> None:
    """Reconfigure logging based on parsed ``-v/-q`` flags."""
    if args.verbose >= 2:
        setup_logging(logging.DEBUG, quiet=args.quiet)
    elif args.verbose >= 1:
        setup_logging(logging.INFO, quiet=args.quiet)
    else:
        setup_logging(logging.WARNING, quiet=args.quiet)


def _run_subcommand(args: argparse.Namespace, home: Path, cwd: Path) -> int:
    """Dispatch the ``run`` subcommand — the main container-launch pipeline."""
    # Resolve project root (dir that may contain .ishlib/).
    if args.project_root is not None:
        project_root_path = Path(args.project_root).resolve()
        if not project_root_path.is_dir():
            log.error(
                "--project-root '%s' is not an existing directory",
                args.project_root,
            )
            return 2
    else:
        project_root_path = cwd.resolve()

    # Load project config so image/shell overrides from
    # .ishlib/isholate/config.toml can fill in any CLI defaults the user
    # didn't override.  CLI flags still take precedence.
    project_cfg = load_project_config(project_root_path)
    overlay_dir = discover_project_overlay(project_root_path)

    if project_cfg.get("image") and args.image == DEFAULT_IMAGE:
        args.image = project_cfg["image"]

    # Shell default resolution — lowest to highest priority:
    #   1. ishfiles default_shell (from project overlay / host user / repo config)
    #   2. isholate project config shell (.ishlib/isholate/config.toml)
    #   3. --shell CLI flag (user override)
    # We only apply lower-priority sources when the user hasn't set --shell.
    if args.shell == DEFAULT_SHELL:
        ishfiles_shell = resolve_default_shell(
            home,
            discover_host_ishfiles_source(home),
            overlay_dir,
        )
        if project_cfg.get("shell"):
            args.shell = project_cfg["shell"]
        elif ishfiles_shell:
            args.shell = ishfiles_shell

    # Check host tool dependencies for --no-network --claude before creating
    # any container or Incus network state.
    if args.no_network and (args.claude or args.claude_base):
        tools_msg = _preflight_claude_host_tools()
        if tools_msg is not None:
            log.error("%s", tools_msg)
            return 1

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
        project_root = project_root_path

    return launch_and_exec(
        args,
        host_ishfiles_source=host_source,
        project_overlay=resolved_overlay,
        project_root=project_root,
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code.
    """
    setup_logging(logging.WARNING)

    if not is_linux():
        log.critical("isholate is only supported on Linux")
        return 1

    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["run"]
    args = parser.parse_args(argv)

    _configure_logging_from_args(args)

    # Run the incus preflight after argparse so that `--help` still works on
    # hosts without a healthy incus setup.
    incus_guidance = check_incus_available()
    if incus_guidance is not None:
        log.error("%s", incus_guidance)
        return 1

    username, home, cwd = get_host_user_info()

    if args.subcommand == "purge":
        include_bases = args.bases or args.bases_alias
        return purge_containers(username, quiet=args.quiet, include_bases=include_bases)

    if args.subcommand == "list":
        return list_containers(
            username,
            all_users=args.all_users,
            running_only=args.running,
            include_bases=not args.no_bases,
        )

    if args.subcommand == "stop":
        return stop_containers(
            username,
            names=list(args.names) if args.names else None,
            include_bases=args.include_bases,
        )

    if args.subcommand == "run":
        return _run_subcommand(args, home, cwd)

    # argparse enforces required=True, so we should never get here.
    parser.error(f"unknown subcommand: {args.subcommand}")
    return 2  # pragma: no cover
