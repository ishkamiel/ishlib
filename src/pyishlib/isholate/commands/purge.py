# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``isholate purge`` -- delete the user's isholate containers."""

from __future__ import annotations

import argparse

from ...cli_command import CliCommand
from ..container import get_host_user_info, purge_containers


class PurgeCommand(CliCommand):
    """Delete isholate containers for the current user."""

    NAME = "purge"
    HELP = "Delete isholate containers for the current user"
    DESCRIPTION = (
        "Delete isholate containers belonging to the current user.  "
        "By default only ephemeral containers are deleted; pass "
        "--bases (or --all) to also delete persistent base containers."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        purge_group = parser.add_mutually_exclusive_group()
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

    def run(self, args: argparse.Namespace) -> int:
        username, _home, _cwd = get_host_user_info()
        include_bases = args.bases or args.bases_alias
        return purge_containers(
            username,
            quiet=args.quiet,
            include_bases=include_bases,
        )
