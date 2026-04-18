# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``isholate stop`` -- stop running isholate containers."""

from __future__ import annotations

import argparse

from ...cli_command import CliCommand
from ..container import get_host_user_info, stop_containers


class StopCommand(CliCommand):
    """Stop running isholate containers."""

    NAME = "stop"
    HELP = "Stop running isholate containers"
    DESCRIPTION = (
        "Stop running isholate containers.  With no names, stops every "
        "running ephemeral belonging to the current user.  Pass --all to "
        "also stop running base containers."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "names",
            nargs="*",
            metavar="NAME",
            help=(
                "Container name(s) to stop.  With no names, every running "
                "ephemeral belonging to the current user is stopped."
            ),
        )
        parser.add_argument(
            "--all",
            action="store_true",
            default=False,
            dest="include_bases",
            help=(
                "When no names are given, also stop running base containers "
                "(otherwise only ephemerals are stopped)"
            ),
        )

    def run(self, args: argparse.Namespace) -> int:
        username, _home, _cwd = get_host_user_info()
        return stop_containers(
            username,
            names=list(args.names) if args.names else None,
            include_bases=args.include_bases,
        )
