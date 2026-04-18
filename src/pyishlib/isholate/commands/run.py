# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``isholate run`` -- launch a container and exec a command (or interactive shell)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional

from ...cli_command import CliCommand
from ..claude import _preflight_claude_host_tools
from ..config import (
    discover_host_ishfiles_source,
    discover_project_overlay,
    load_project_config,
    resolve_default_shell,
)
from ..container import get_host_user_info, launch_and_exec

log = logging.getLogger(__name__)

DEFAULT_IMAGE = "images:ubuntu/24.04"
DEFAULT_SHELL = "/bin/bash"


class RunCommand(CliCommand):
    """Launch a container and run a command (or shell)."""

    NAME = "run"
    HELP = "Launch a container and run a command (or shell)"
    DESCRIPTION = (
        "Launch an Incus container with the host user mirrored and run "
        "a command inside it.  When no command is given, an interactive "
        "shell is started."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
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

        claude_group = parser.add_mutually_exclusive_group()
        claude_group.add_argument(
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
        claude_group.add_argument(
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

    def run(self, args: argparse.Namespace) -> int:
        _username, home, cwd = get_host_user_info()
        return _run_subcommand(args, home, cwd)


def _run_subcommand(args: argparse.Namespace, home: Path, cwd: Path) -> int:
    """Dispatch the ``run`` subcommand — the main container-launch pipeline."""
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

    project_cfg = load_project_config(project_root_path)
    overlay_dir = discover_project_overlay(project_root_path)

    if project_cfg.get("image") and args.image == DEFAULT_IMAGE:
        args.image = project_cfg["image"]

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

    if args.no_network and (args.claude or args.claude_base):
        tools_msg = _preflight_claude_host_tools()
        if tools_msg is not None:
            log.error("%s", tools_msg)
            return 1

    if args.no_ishfiles:
        args.no_host_ishfiles = True
        args.no_project_ishfiles = True

    if args.rebuild:
        args.rebuild_base = True
        args.rebuild_project_base = True

    if args.rebuild_base:
        args.rebuild_project_base = True

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
