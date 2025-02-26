# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Any, Optional, Iterable, Mapping
from .command_runner import CommandRunner
from .ish_comp import IshComp


class PipInstaller:
    """Helper class for managing python packages via pip"""

    PIP_UPDATE_PKG: Mapping[str, str] = {
        "name": "pip",
        "pip": "pip",
    }

    PIP_INSTALL_CMD: Iterable[str] = ["pip3", "install", "--user"]

    def __init__(self) -> None:
        self._pip_checked: bool = False
        self._has_pip: bool = False
        assert isinstance(self, IshComp)
        self.log = getattr(self, "log", None)
        self.runner: CommandRunner = getattr(self, "runner", None)

    @property
    def has_pip(self) -> bool:
        """Check if pip is available"""

        if not self._pip_checked:
            self._has_pip = self.runner.which("pip3") is not None
            self._pip_checked = True
        return self._has_pip

    @property
    def pip(self) -> bool:
        """Get the common Namespace for installer commands"""

        # pylint: disable=R0903
        class Namespace:
            """Namespace for pip commands"""

            can_install = self.can_use_pip
            install = self.install_pip_pkgs
            install_unless_found = self.install_pip_pkg_unless_found
            is_installed = self.is_pip_pkg_installed
            update = self.update_pip_pkgs
            update_and_install_all = self.update_and_install_pip_pkgs

        return Namespace

    def can_use_pip(self, pkg: Optional[Any] = None) -> bool:
        """Check if pip is available, and optionally, if pkg can use it"""

        if pkg is not None and "pip" not in pkg:
            return False
        return self.has_pip

    def get_pip_pkgs(self, pkgs) -> Iterable[dict]:
        """Get the pip packages from a list of packages"""
        return [pkg for pkg in pkgs if self.can_use_pip(pkg)]

    def is_pip_pkg_installed(self, pkg) -> bool:
        """Check if a pip package is installed"""

        if not self.can_use_pip():
            self.log.debug("Pip not available")
            return False
        if not self.can_use_pip(pkg):
            self.log.debug("Pip pkg not available for %s", pkg["name"])
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["pip3", "list"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return pkg["pip"] in result.stdout.decode("utf-8")
        except CalledProcessError as e:
            self.log.critical("Pip error checking %s: %s", pkg["name"], e)
            raise e

    def install_pip_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of pip packages"""

        assert isinstance(pkgs, Iterable) and all(
            isinstance(pkg, dict) for pkg in pkgs
        ), "pkgs should be an iterable of dictionaries"
        assert all(self.can_use_pip(p) for p in pkgs)

        pkg_list: Iterable[str] = [pkg["pip"] for pkg in pkgs]

        self.log.info("Installing with pip: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run(self.PIP_INSTALL_CMD + pkg_list)
            return res.returncode == 0
        except CalledProcessError as e:
            self.log.critical("Pip error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def install_pip_pkg(self, pkg) -> bool:
        """Install a pip package"""
        self.install_pip_pkgs([pkg])

    def install_pip_pkg_unless_found(self, pkg) -> bool:
        """Install a pip package unless it is already installed"""

        if not self.is_pip_pkg_installed(pkg):
            self.install_pip_pkg(pkg)

    def update_pip_pkgs(self) -> bool:
        """Update all installed pip packages"""
        assert self.can_use_pip()

        self.install_pip_pkg_unless_found(self.PIP_UPDATE_PKG)
        self.runner.run(["pip3", "install", "--upgrade", "pip"])
        self.log.warning("pip update not implemented (only updates pip itself)")

    def update_and_install_pip_pkgs(self, pkgs):
        """Update python, pip and pip packages, then install new pip pkgs"""
        assert self.can_use_pip()

        self.update_pip_pkgs()
        self.install_pip_pkgs(pkgs)
