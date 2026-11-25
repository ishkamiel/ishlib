# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``isholate dump-script`` -- emit a standalone bash script for the container."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ...cli_command import CliCommand
from ..config import load_project_config
from ..container import (
    _SANDBOX_RUNTIME_VERSION,
    _sanitize_for_name,
    get_host_user_info,
)
from ..dump_script_template import render_dump_script
from .run import DEFAULT_IMAGE

log = logging.getLogger(__name__)

DEFAULT_DUMP_SHELL = "/usr/bin/zsh"


class DumpScriptCommand(CliCommand):
    """Print a standalone bash script that re-creates an isholate container."""

    NAME = "dump-script"
    HELP = "Print a standalone bash script that re-creates an isholate container"
    DESCRIPTION = (
        "Print a self-contained bash script that needs only incus, not "
        "ishlib.  When run, the script creates and provisions the container "
        "(host user mirrored, base packages, sandbox runtime) if it does not "
        "exist yet, then enters it with a login shell.  The script takes an "
        "optional container name as its first argument.  ishfiles, Claude "
        "integration, and network isolation are not included."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--image",
            metavar="IMAGE",
            default=DEFAULT_IMAGE,
            help=(
                "Incus image baked into the script (default: project "
                f"config image, else {DEFAULT_IMAGE})"
            ),
        )
        parser.add_argument(
            "--shell",
            metavar="SHELL",
            default=DEFAULT_DUMP_SHELL,
            help=f"Login shell for the container user (default: {DEFAULT_DUMP_SHELL})",
        )
        parser.add_argument(
            "--container-name",
            metavar="NAME",
            default=None,
            help=(
                "Default container name baked into the script; the script's "
                "first argument overrides it (default: isholate-<user>-dump)"
            ),
        )
        parser.add_argument(
            "--project-root",
            metavar="PATH",
            default=None,
            help=(
                "Directory to look for .ishlib/isholate/config.toml in "
                "(default: current working directory)"
            ),
        )
        parser.add_argument(
            "-o",
            "--output",
            metavar="FILE",
            default=None,
            help="Write the script to FILE (made executable) instead of stdout",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Overwrite --output if it already exists",
        )

    def run(self) -> int:
        username, _home, cwd = get_host_user_info()
        return dump_script(self.cfg, username, cwd)


def dump_script(args: argparse.Namespace, username: str, cwd: Path) -> int:
    """Render the standalone script and write it to stdout or ``args.output``."""
    project_root = Path(args.project_root) if args.project_root else cwd
    if not project_root.is_dir():
        log.error("--project-root '%s' is not an existing directory", project_root)
        return 2

    image = args.image
    if image == DEFAULT_IMAGE:
        image = load_project_config(project_root.resolve()).get("image") or image

    default_name = (
        args.container_name or f"isholate-{_sanitize_for_name(username)}-dump"
    )
    output = Path(args.output) if args.output else None

    script = render_dump_script(
        image=image,
        shell=args.shell,
        username=username,
        default_name=default_name,
        sandbox_runtime_version=_SANDBOX_RUNTIME_VERSION,
        script_name=output.name if output else "isholate.sh",
    )

    if output is None:
        print(script, end="")
        return 0

    if output.exists() and not args.force:
        log.error("'%s' already exists; pass --force to overwrite", output)
        return 1
    output.write_text(script, encoding="utf-8")
    output.chmod(0o755)
    log.info("wrote %s", output)
    return 0
