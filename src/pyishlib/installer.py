# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

from typing import Any, Optional
import shutil
from .ish_comp import IshComp
from .command_runner import CommandRunner


class Installer(IshComp):
    """Installer class for installing packages."""

    def __init__(self, runner: Optional[CommandRunner] = None, **kwargs: Any) -> None:
        self._runner: CommandRunner | None = runner
        super().__init__(**kwargs)

    @property
    def runner(self) -> CommandRunner:
        """Get the command runner."""
        if self._runner is None:
            self._runner = CommandRunner(
                args=self._args,
                conf=self._conf,
                dry_run=self._dry_run,
                quiet=self._quiet,
            )
        return self._runner

    def check_command(self, command: str) -> bool:
        """Check if a command is available."""
        return shutil.which(command) is not None

    def install(self, *packages, force_sudo: Optional[bool] = False) -> bool:
        """Install a package."""

    def install_apt(self, *packages, sudo: Optional[bool] = True, **kwargs) -> bool:
        """Install a package using apt."""
        return self.runner.run(["apt", "install", *packages], sudo=sudo, **kwargs)

    def install_cargo(self, *packages: list[str], **kwargs) -> bool:
        """Install a package using cargo."""
        return self.runner.run(["cargo", "install", *packages], **kwargs)
