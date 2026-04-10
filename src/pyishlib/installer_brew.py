#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import logging
import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Iterable

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerBrew(InstallerBase):
    """Helper class for managing packages via Homebrew"""

    INSTALLER_NAME: str = "brew"

    def _tool_cmd(self) -> str:
        return "brew"

    def _pkg_key(self) -> str:
        return "brew"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a Homebrew package is installed"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("Homebrew not available for %s", pkg.get("name"))
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
            log.debug("Homebrew error checking %s: %s", pkg["name"], e)
            return False

    def install_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of Homebrew packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Iterable[str] = [pkg["brew"] for pkg in pkgs]

        log.info("Installing with Homebrew: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run(["brew", "install"] + pkg_list)
            return res.returncode == 0
        except CalledProcessError as e:
            log.critical("Homebrew error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def update_pkgs(self) -> bool:
        """Update all installed Homebrew packages"""
        assert self.can_install()

        self.runner.run(["brew", "update"])
        self.runner.run(["brew", "upgrade"])
        return True

    def update_and_install_all(self, pkgs: Iterable[dict]) -> None:
        """Update Homebrew and Homebrew packages, then install new Homebrew pkgs"""
        assert self.can_install()

        self.update_pkgs()
        self.install_pkgs(pkgs)
