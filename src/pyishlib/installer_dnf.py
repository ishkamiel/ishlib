#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for dnf package installing tasks"""

import logging
import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Sequence

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerDnf(InstallerBase):
    """Helper class for managing dnf packages"""

    INSTALLER_NAME: str = "dnf"

    def _tool_cmd(self) -> str:
        return "dnf"

    def _pkg_key(self) -> str:
        return "dnf"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a dnf package is installed via rpm -q"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("dnf not available for %s", pkg.get("name"))
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["rpm", "-q", pkg["dnf"]],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return result.returncode == 0
        except CalledProcessError as e:
            log.debug("rpm -q non-zero exit for %s: %s", pkg["name"], e)
            return False

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of dnf packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Sequence[str] = [pkg["dnf"] for pkg in pkgs]

        log.info("Installing with dnf: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run_sudo(
                ["dnf", "install", "-y"] + list(pkg_list)
            )
            return res.returncode == 0
        except CalledProcessError as e:
            log.critical("dnf error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def update_pkgs(self) -> bool:
        """Update all installed dnf packages"""
        assert self.can_install()

        log.info("Updating dnf packages")
        try:
            self.runner.run_sudo(["dnf", "upgrade", "-y"])
            return True
        except CalledProcessError as e:
            log.critical("dnf error updating packages: %s", e)
            raise e

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update dnf packages, then install new dnf pkgs"""
        self.update_pkgs()
        self.install_pkgs(pkgs)
