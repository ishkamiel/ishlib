# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Any, Optional, Iterable
from .command_runner import CommandRunner
from .ish_comp import IshComp


class BrewInstaller:
    """Helper class for managing packages via Homebrew"""

    def __init__(self) -> None:
        self._brew_checked: bool = False
        self._has_brew: bool = False
        assert isinstance(self, IshComp)
        self.log = getattr(self, "log", None)
        self.runner: CommandRunner = getattr(self, "runner", None)

    @property
    def has_brew(self) -> bool:
        """Check if Homebrew is available"""
        if not self._brew_checked:
            self._has_brew = self.runner.which("brew") is not None
            self._brew_checked = True
        return self._has_brew

    @property
    def brew(self) -> bool:
        """Get the common Namespace for installer commands"""

        # pylint: disable=R0903
        class Namespace:
            """Namespace for brew commands"""

            can_install = self.can_use_brew
            install = self.install_brew_pkgs
            install_unless_found = self.install_brew_pkg_unless_found
            is_installed = self.is_brew_pkg_installed
            update = self.update_brew_pkgs
            update_and_install_all = self.update_and_install_brew_pkgs

        return Namespace

    def can_use_brew(self, pkg: Optional[Any] = None) -> bool:
        """Check if Homebrew is available, and optionally, if pkg can use it"""
        if pkg is not None and "brew" not in pkg:
            return False
        return self.has_brew

    def get_brew_pkgs(self, pkgs) -> Iterable[dict]:
        """Get the Homebrew packages from a list of packages"""
        return [pkg for pkg in pkgs if self.can_use_brew(pkg)]

    def is_brew_pkg_installed(self, pkg) -> bool:
        """Check if a Homebrew package is installed"""
        if not self.can_use_brew():
            self.log.debug("Homebrew not available")
            return False
        if not self.can_use_brew(pkg):
            self.log.debug("Homebrew pkg not available for %s", pkg["name"])
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["brew", "list", "--formula"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return pkg["brew"] in result.stdout.decode("utf-8")
        except CalledProcessError as e:
            self.log.critical("Homebrew error checking %s: %s", pkg["name"], e)
            raise e

    def install_brew_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of Homebrew packages"""
        assert isinstance(pkgs, Iterable) and all(
            isinstance(pkg, dict) for pkg in pkgs
        ), "pkgs should be an iterable of dictionaries"
        assert all(self.can_use_brew(p) for p in pkgs)

        pkg_list: Iterable[str] = [pkg["brew"] for pkg in pkgs]

        self.log.info("Installing with Homebrew: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run(["brew", "install"] + pkg_list)
            return res.returncode == 0
        except CalledProcessError as e:
            self.log.critical("Homebrew error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def install_brew_pkg(self, pkg) -> bool:
        """Install a Homebrew package"""
        self.install_brew_pkgs([pkg])

    def install_brew_pkg_unless_found(self, pkg) -> bool:
        """Install a Homebrew package unless it is already installed"""
        if not self.is_brew_pkg_installed(pkg):
            self.install_brew_pkg(pkg)

    def update_brew_pkgs(self) -> bool:
        """Update all installed Homebrew packages"""
        assert self.can_use_brew()

        self.runner.run(["brew", "update"])
        self.runner.run(["brew", "upgrade"])

    def update_and_install_brew_pkgs(self, pkgs):
        """Update Homebrew and Homebrew packages, then install new Homebrew pkgs"""
        assert self.can_use_brew()

        self.update_brew_pkgs()
        self.install_brew_pkgs(pkgs)
