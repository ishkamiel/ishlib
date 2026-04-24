# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``isholate list`` -- print a table of isholate containers."""

from __future__ import annotations

import argparse

from ...cli_command import CliCommand
from ..container import get_host_user_info, list_containers


class ListCommand(CliCommand):
    """List isholate containers."""

    NAME = "list"
    HELP = "List isholate containers"
    DESCRIPTION = "Print a table of isholate containers (ephemerals and bases)."

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--running",
            action="store_true",
            default=False,
            help="Only show containers whose state is Running",
        )
        parser.add_argument(
            "--all-users",
            action="store_true",
            default=False,
            help="Show containers for all users (adds a USER column)",
        )
        parser.add_argument(
            "--no-bases",
            action="store_true",
            default=False,
            help="Hide persistent base containers (shown by default)",
        )

    def run(self) -> int:
        username, _home, _cwd = get_host_user_info()
        return list_containers(
            username,
            all_users=self.cfg.all_users,
            running_only=self.cfg.running,
            include_bases=not self.cfg.no_bases,
        )
