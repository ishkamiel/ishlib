# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for apt package installing tasks"""

# Standard imports
import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Any, Optional, Iterable
from .command_runner import CommandRunner
from .ish_comp import IshComp


class AptInstaller:
    """Helper class for managing apt packages"""

    def __init__(self) -> None:
        self._apt_checked: bool = False
        self._has_apt: bool = False
        assert isinstance(self, IshComp)
        self.log = getattr(self, "log", None)
        self.runner: CommandRunner = getattr(self, "runner", None)

    @property
    def has_apt(self) -> bool:
        """Check if apt is available"""
        if not self._apt_checked:
            self._has_apt = self.runner.which("apt") is not None
            self.log.debug("has_apt: %s", self._has_apt)
            self._apt_checked = True
        return self._has_apt

    @property
    def apt(self) -> bool:
        """Get the common Namespace for installer commands"""

        # pylint: disable=R0903
        class Namespace:
            """Namespace for apt commands"""

            can_install = self.can_use_apt
            install = self.install_apt_pkgs
            install_unless_found = self.install_apt_pkg_unless_found
            is_installed = self.is_apt_pkg_installed
            update = self.update_apt_pkgs
            update_and_install_all = self.update_and_install_all

        return Namespace()

    def can_use_apt(self, pkg: Optional[Any] = None) -> bool:
        """Check if apt is available, and optionally, if pkg can use it"""
        if pkg is not None and not "apt" in pkg:
            self.log.debug("apt not available for %s", pkg["name"])
            return False
        return self.has_apt

    def get_apt_pkgs(self, pkgs) -> Iterable[dict]:
        """Get the apt packages from a list of packages"""
        return [pkg for pkg in pkgs if self.can_use_apt(pkg)]

    def is_apt_pkg_installed(self, pkg) -> bool:
        """Check if an apt package is installed"""
        if not self.can_use_apt():
            self.log.debug("apt not available")
            return False
        if not self.can_use_apt(pkg):
            self.log.debug("apt pkg not available for %s", pkg["name"])
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["dpkg", "-s", pkg["apt"]],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return "Status: install ok installed" in result.stdout.decode("utf-8")
        except CalledProcessError as e:
            self.log.critical("apt error checking %s: %s", pkg["name"], e)
            raise e

    def install_apt_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of apt packages"""
        assert isinstance(pkgs, Iterable) and all(
            isinstance(pkg, dict) for pkg in pkgs
        ), "pkgs should be an iterable of dictionaries"
        assert all(self.can_use_apt(p) for p in pkgs)

        pkg_list: Iterable[str] = [pkg["apt"] for pkg in pkgs]

        self.log.info("Installing with apt: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run_sudo(
                ["apt", "install", "-y"] + pkg_list
            )
            return res.returncode == 0
        except CalledProcessError as e:
            self.log.critical("apt error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def install_apt_pkg(self, pkg) -> bool:
        """Install an apt package"""
        return self.install_apt_pkgs([pkg])

    def install_apt_pkg_unless_found(self, pkg) -> bool:
        """Install an apt package unless it is already installed"""
        if not self.is_apt_pkg_installed(pkg):
            self.install_apt_pkg(pkg)

    def update_apt_pkgs(self) -> bool:
        """Update all installed apt packages"""
        assert self.can_use_apt()

        self.log.info("Updating apt packages")
        try:
            self.runner.run_sudo(["apt", "update"])
            self.runner.run_sudo(["apt", "upgrade", "-y"])
        except CalledProcessError as e:
            self.log.critical("apt error updating packages: %s", e)
            raise e

    def update_and_install_all(self, pkgs):
        """Update apt packages, then install new apt pkgs"""
        self.update_apt_pkgs()
        self.install_apt_pkgs(pkgs)
