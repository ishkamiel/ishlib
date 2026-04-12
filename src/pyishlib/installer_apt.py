#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for apt package installing tasks"""

import logging
import subprocess
from subprocess import CalledProcessError
from typing import Sequence

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerApt(InstallerBase):
    """Helper class for managing apt packages"""

    INSTALLER_NAME: str = "apt"

    def _tool_cmd(self) -> str:
        return "apt"

    def _pkg_key(self) -> str:
        return "apt"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if an apt package is installed"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("apt not available for %s", pkg.get("name"))
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
            log.debug("dpkg non-zero exit for %s: %s", pkg["name"], e)
            return False

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of apt packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Sequence[str] = [pkg["apt"] for pkg in pkgs]

        log.info("Installing with apt: %s", " ".join(pkg_list))
        res = self._run_cmd(
            ["apt", "install", "-y", *pkg_list], sudo=True, action="installing"
        )
        return res.returncode == 0

    def update_pkgs(self) -> bool:
        """Update all installed apt packages"""
        self._require_available()

        log.info("Updating apt packages")
        self._run_cmd(["apt", "update"], sudo=True, action="updating")
        self._run_cmd(["apt", "upgrade", "-y"], sudo=True, action="updating")
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update apt packages, then install new apt pkgs"""
        self.update_pkgs()
        self.install_pkgs(pkgs)
