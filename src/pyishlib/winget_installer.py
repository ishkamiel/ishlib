# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import logging
import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Any, Optional, Iterable
from .command_runner import CommandRunner


class WingetInstaller:
    """Helper class for managing packages via winget (Windows Package Manager)"""

    INSTALLER_NAME: str = "winget"

    def __init__(self, log: logging.Logger, runner: CommandRunner) -> None:
        self.log: logging.Logger = log
        self.runner: CommandRunner = runner
        self._winget_checked: bool = False
        self._has_winget: bool = False

    @property
    def has_winget(self) -> bool:
        """Check if winget is available"""
        if not self._winget_checked:
            self._has_winget = self.runner.which("winget") is not None
            self._winget_checked = True
        return self._has_winget

    @property
    def namespace(self):
        """Get the common Namespace for installer commands"""

        # pylint: disable=R0903
        class Namespace:
            """Namespace for winget commands"""

            can_install = self.can_use_winget
            install = self.install_winget_pkgs
            install_unless_found = self.install_winget_pkg_unless_found
            is_installed = self.is_winget_pkg_installed
            update = self.update_winget_pkgs
            update_and_install_all = self.update_and_install_winget_pkgs

        return Namespace()

    def can_use_winget(self, pkg: Optional[Any] = None) -> bool:
        """Check if winget is available, and optionally, if pkg can use it"""
        if pkg is not None and "winget" not in pkg:
            return False
        return self.has_winget

    def get_winget_pkgs(self, pkgs) -> Iterable[dict]:
        """Get the winget packages from a list of packages"""
        return [pkg for pkg in pkgs if self.can_use_winget(pkg)]

    def is_winget_pkg_installed(self, pkg) -> bool:
        """Check if a winget package is installed"""
        if not self.can_use_winget():
            self.log.debug("winget not available")
            return False
        if not self.can_use_winget(pkg):
            self.log.debug("winget pkg not available for %s", pkg["name"])
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["winget", "list", "--id", pkg["winget"], "--exact"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output = result.stdout
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return pkg["winget"] in output
        except CalledProcessError as e:
            self.log.debug("winget error checking %s: %s", pkg["name"], e)
            return False

    def install_winget_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of winget packages"""
        assert isinstance(pkgs, Iterable) and all(
            isinstance(pkg, dict) for pkg in pkgs
        ), "pkgs should be an iterable of dictionaries"
        assert all(self.can_use_winget(p) for p in pkgs)

        for pkg in pkgs:
            pkg_id: str = pkg["winget"]
            self.log.info("Installing with winget: %s", pkg_id)
            try:
                res: CompletedProcess = self.runner.run(
                    [
                        "winget",
                        "install",
                        "--id",
                        pkg_id,
                        "--exact",
                        "--accept-source-agreements",
                        "--accept-package-agreements",
                    ]
                )
                if res.returncode != 0:
                    self.log.critical(
                        "winget error installing %s: returncode %d",
                        pkg_id,
                        res.returncode,
                    )
                    return False
            except CalledProcessError as e:
                self.log.critical("winget error installing %s: %s", pkg_id, e)
                raise e
        return True

    def install_winget_pkg(self, pkg) -> bool:
        """Install a winget package"""
        return self.install_winget_pkgs([pkg])

    def install_winget_pkg_unless_found(self, pkg) -> bool:
        """Install a winget package unless it is already installed"""
        if not self.is_winget_pkg_installed(pkg):
            return self.install_winget_pkg(pkg)
        return True

    def update_winget_pkgs(self) -> bool:
        """Update all installed winget packages"""
        assert self.can_use_winget()

        self.runner.run(
            [
                "winget",
                "upgrade",
                "--all",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        )
        return True

    def update_and_install_winget_pkgs(self, pkgs):
        """Update winget packages, then install new winget pkgs"""
        assert self.can_use_winget()

        self.update_winget_pkgs()
        self.install_winget_pkgs(pkgs)
