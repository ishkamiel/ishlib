# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``install`` subcommand -- install packages from the ishfiles config."""

from __future__ import annotations

import argparse

from ...cli_command import CliCommand
from ..installer_helper import run_install


class InstallCommand(CliCommand):
    """Install packages defined in the ishfiles package config."""

    NAME = "install"
    HELP = "Install packages defined in the ishfiles package config"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "packages",
            nargs="*",
            default=None,
            help="Restrict to specific package names (default: all)",
        )

    def run(self) -> int:
        packages = self.cfg.get_opt("packages") or None
        return run_install(self.cfg, packages=packages)
